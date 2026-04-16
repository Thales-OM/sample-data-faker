import asyncio
from typing import Any, Dict, Optional, Union
from dataclasses import dataclass
import pandas as pd
import pyarrow as pa
from pyiceberg.io.pyarrow import pyarrow_to_schema
from pyiceberg.catalog import Catalog, load_catalog
from pyiceberg.table import Table
from pyiceberg.exceptions import NoSuchTableError, CommitFailedException
from pyiceberg.schema import Schema
from pyiceberg.utils.schema_conversion import AvroSchemaConversion
from src.config import HMSS3DestinationConfig
from src.logger import LoggerFactory
from ..base import BaseDestination, BaseDestinationResponse
from .helpers import AvroSchemaFieldIdAssigner


logger = LoggerFactory.getLogger(__name__)


@dataclass
class IcebergDestinationResponse(BaseDestinationResponse):
    """Response object containing metadata about the write operation."""

    table_identifier: str
    rows_written: int
    snapshot_id: Optional[int]
    created_new_table: bool
    s3_location: str


class IcebergDestinationError(Exception):
    """Raised when Iceberg destination operation fails"""

    def __init__(
        self,
        message: str,
        cause: Optional[Exception] = None,
        table_identifier: Optional[str] = None,
        operation: Optional[str] = None,
    ):
        super().__init__(message)
        self.cause = cause
        self.table_identifier = table_identifier
        self.operation = operation  # e.g., "create_table", "load_table", "write_data"


class IcebergDestination(BaseDestination):
    """
    Asynchronous destination class that writes Pandas DataFrames to Apache Iceberg tables.
    Supports HMS catalog and S3 storage. Handles schema reconciliation.

    S3 Storage Organization:
    - Tables are stored in: s3://{bucket}/{warehouse-path}/{namespace}.db/{title}/
    - Data files: s3://.../{namespace}.db/{title}/data/*.parquet
    - Metadata: s3://.../{namespace}.db/{title}/metadata/*.json

    Usage:
        # Option 1: Using namespace and title (recommended for consistency with S3Destination)
        dest = IcebergDestination(config)
        await dest.submit(df, namespace="ecommerce", title="users")
        # → Table: "ecommerce.users"
        # → S3: s3://bucket/iceberg-tables/ecommerce.db/users/

        # Option 2: Direct table identifier
        await dest.submit(df, table_identifier="ecommerce.users")
    """

    def __init__(
        self,
        config: HMSS3DestinationConfig,
        partition_spec: Optional[Any] = None,
        write_properties: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize the Iceberg Destination.

        Args:
            config: Config to connect to Hive Metastore with S3 storage
            partition_spec: Optional Iceberg partition spec.
            write_properties: Optional properties for the write operation.
        """
        self.config = config
        self.partition_spec = partition_spec
        self.write_properties = write_properties or {}

        # Lazy load catalog
        self._catalog: Optional[Catalog] = None

    @property
    def catalog(self) -> Catalog:
        if self._catalog is None:
            catalog_conn_properties = self.config.model_dump_with_secrets(
                mode="json", by_alias=True
            )
            self._catalog = load_catalog(**catalog_conn_properties)
        return self._catalog

    def _build_table_identifier(
        self,
        namespace: Optional[str] = None,
        title: Optional[str] = None,
        table_identifier: Optional[str] = None,
    ) -> str:
        """
        Build table identifier from namespace/title or use provided identifier.

        Args:
            namespace: Optional namespace (e.g., "ecommerce")
            title: Optional table title (e.g., "users")
            table_identifier: Direct table identifier (e.g., "ecommerce.users")

        Returns:
            Table identifier in format "namespace.title"
        """
        if table_identifier:
            return table_identifier

        if namespace and title:
            return f"{namespace}.{title}"

        if title:
            return title

        raise ValueError(
            "Either (namespace, title) or table_identifier must be provided"
        )

    def _get_s3_location(
        self,
        namespace: Optional[str] = None,
        title: Optional[str] = None,
        table_identifier: Optional[str] = None,
    ) -> str:
        """
        Construct the S3 location where Iceberg table data is stored.

        Returns:
            Human-readable S3 path for documentation/logging
        """
        # Parse namespace and title from table_identifier if needed
        if not namespace or not title:
            if table_identifier and "." in table_identifier:
                parts = table_identifier.split(".")
                namespace = parts[0]
                title = parts[1]
            elif table_identifier:
                namespace = "default"
                title = table_identifier
            else:
                namespace = namespace or "default"
                title = title or "unknown"

        # Extract bucket and warehouse from config
        warehouse_url = self.config.warehouse  # e.g., "s3://my-bucket/iceberg-tables/"
        if warehouse_url.startswith("s3://"):
            # Remove "s3://" and split bucket from path
            without_scheme = warehouse_url[5:]  # "my-bucket/iceberg-tables/"
            if "/" in without_scheme:
                bucket, warehouse_path = without_scheme.split("/", 1)
                # Ensure warehouse_path ends with /
                if not warehouse_path.endswith("/"):
                    warehouse_path += "/"
            else:
                bucket = without_scheme
                warehouse_path = ""
        else:
            return f"Unknown (invalid warehouse URL: {warehouse_url})"

        # Construct readable path
        s3_location = f"s3://{bucket}/{warehouse_path}{namespace}.db/{title}/"
        return s3_location

    async def submit(
        self,
        df: pd.DataFrame,
        namespace: Optional[str] = None,
        title: Optional[str] = None,
        table_identifier: Optional[str] = None,
        avro_schema: Optional[Dict[str, Any]] = None,
        iceberg_schema: Optional[Union[Schema, Dict[str, Any]]] = None,
    ) -> IcebergDestinationResponse:
        """
        Submit data to the configured Iceberg destination.

        Args:
            df: DataFrame with data to write
            namespace: Optional namespace for table (e.g., "ecommerce")
            title: Optional table name (e.g., "users")
            table_identifier: Direct table identifier (e.g., "ecommerce.users")
                              Takes precedence over namespace/title if provided
            avro_schema: Optional Avro schema for schema reconciliation
            iceberg_schema: Optional Iceberg schema for schema reconciliation

        Returns:
            IcebergDestinationResponse with metadata about the write operation

        Examples:
            # Using namespace/title (matches S3Destination pattern)
            await dest.submit(df, namespace="ecommerce", title="users")

            # Using direct identifier
            await dest.submit(df, table_identifier="ecommerce.users")
        """
        # Build table identifier
        resolved_table_id = self._build_table_identifier(
            namespace=namespace, title=title, table_identifier=table_identifier
        )

        # Get S3 location for response
        s3_location = self._get_s3_location(
            namespace=namespace, title=title, table_identifier=table_identifier
        )

        try:
            # Offload blocking I/O to a thread
            response = await asyncio.to_thread(
                self._submit_sync,
                df,
                resolved_table_id,
                avro_schema,
                iceberg_schema,
                s3_location,
            )
            return response
        except IcebergDestinationError:
            # Re-raise custom exceptions as-is
            raise
        except Exception as e:
            logger.error(f"Failed to write to Iceberg table {resolved_table_id}: {e}")
            raise IcebergDestinationError(
                message=f"Failed to write to Iceberg table {resolved_table_id}",
                cause=e,
                table_identifier=resolved_table_id,
                operation="submit",
            ) from e

    def _submit_sync(
        self,
        df: pd.DataFrame,
        table_identifier: str,
        avro_schema: Optional[Dict[str, Any]] = None,
        iceberg_schema: Optional[Union[Schema, Dict[str, Any]]] = None,
        s3_location: Optional[str] = None,
    ) -> IcebergDestinationResponse:
        """
        Synchronous core logic for schema reconciliation and writing.
        """
        try:
            # Generate schema
            if avro_schema:
                if iceberg_schema:
                    logger.warning(
                        "Both avro_schema and iceberg_schema were provided. iceberg_schema takes precedence."
                    )
                else:
                    enriched_avro_schema = AvroSchemaFieldIdAssigner(
                        catalog=self.catalog
                    ).assign_field_ids(
                        avro_schema=avro_schema,
                        table_identifier=table_identifier,
                        start_id=1,
                    )
                    iceberg_schema = AvroSchemaConversion().avro_to_iceberg(
                        avro_schema=enriched_avro_schema
                    )
            if isinstance(iceberg_schema, dict):
                iceberg_schema = Schema.model_validate(iceberg_schema)

            arrow_table = pa.Table.from_pandas(df, preserve_index=False)
            # No Schema was provided in args - extract from pyarrow
            if not iceberg_schema:
                iceberg_schema = pyarrow_to_schema(arrow_table.schema)

            # Check if table exists
            created_new_table = False
            try:
                table = self.catalog.load_table(table_identifier)
                logger.info(f"Loaded existing table: {table_identifier}")
            except NoSuchTableError:
                logger.info(
                    f"Table {table_identifier} does not exist. Creating new table."
                )
                table = self._create_new_table(
                    table_identifier=table_identifier,
                    iceberg_schema=iceberg_schema,
                )
                created_new_table = True

            # Write data in a single transaction (atomic: schema + data)
            try:
                with table.transaction() as txn:
                    if not created_new_table and iceberg_schema:
                        # Update schema within the same transaction as data write
                        # This ensures atomicity: both succeed or both fail
                        txn.update_schema().union_by_name(new_schema=iceberg_schema)

                    # Append for new tables, overwrite for existing
                    if created_new_table:
                        txn.append(arrow_table)
                        logger.info(
                            f"Appended {arrow_table.num_rows} rows to new table {table_identifier}"
                        )
                    else:
                        txn.overwrite(arrow_table)
                        logger.info(
                            f"Overwrote table {table_identifier} with {arrow_table.num_rows} rows"
                        )
            except CommitFailedException as e:
                raise IcebergDestinationError(
                    message=f"Commit failed for table {table_identifier}",
                    cause=e,
                    table_identifier=table_identifier,
                    operation="write_data",
                ) from e
            except Exception as e:
                raise IcebergDestinationError(
                    message=f"Failed to write data to table {table_identifier}",
                    cause=e,
                    table_identifier=table_identifier,
                    operation="write_data",
                ) from e

            # Retrieve snapshot info
            table.refresh()
            current_snapshot = table.current_snapshot()
            snapshot_id = current_snapshot.snapshot_id if current_snapshot else None

            return IcebergDestinationResponse(
                table_identifier=table_identifier,
                rows_written=arrow_table.num_rows,
                snapshot_id=snapshot_id,
                created_new_table=created_new_table,
                s3_location=s3_location or "unknown",
            )
        except IcebergDestinationError:
            raise
        except Exception as e:
            raise IcebergDestinationError(
                message=f"Failed to submit data to Iceberg table {table_identifier}",
                cause=e,
                table_identifier=table_identifier,
                operation="submit_sync",
            ) from e

    def _create_new_table(
        self,
        table_identifier: str,
        iceberg_schema: Optional[Schema] = None,
    ) -> Table:
        """
        Creates a new Iceberg table with given schema or inferred from Arrow table.
        """
        try:
            table = self.catalog.create_table(
                identifier=table_identifier,
                schema=iceberg_schema,
                partition_spec=self.partition_spec,
                properties=self.write_properties,
            )
            logger.info(f"Created new table: {table_identifier}")
            return table
        except Exception as e:
            raise IcebergDestinationError(
                message=f"Failed to create table {table_identifier}",
                cause=e,
                table_identifier=table_identifier,
                operation="create_table",
            ) from e
