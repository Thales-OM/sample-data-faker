import asyncio
from typing import Any, Dict, Optional, Union, Literal
from dataclasses import dataclass
import pandas as pd
import pyarrow as pa
from pydantic import Field, PrivateAttr
from pyiceberg.io.pyarrow import pyarrow_to_schema, schema_to_pyarrow
from pyiceberg.catalog import Catalog, load_catalog
from pyiceberg.table import Table
from pyiceberg.exceptions import (
    NoSuchTableError,
    CommitFailedException,
    NamespaceAlreadyExistsError,
)
from pyiceberg.schema import Schema
from src.config import HMSS3DestinationConfig
from src.logger import LoggerFactory
from ..base import BaseDestination, BaseDestinationResponse, BaseDestinationConfig
from .helpers import ArrowSchemaFieldIdAssigner


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
        self.message = message
        self.cause = cause
        self.table_identifier = table_identifier
        self.operation = operation  # e.g., "create_table", "load_table", "write_data"

    def __str__(self) -> str:
        return str(
            {
                "message": self.message,
                "cause": self.cause,
                "table_identifier": self.table_identifier,
                "operation": self.operation,
            }
        )


class IcebergDestinationConfig(BaseDestinationConfig, HMSS3DestinationConfig):
    table_name: str
    namespace: str = "default"
    avro_schema: Optional[Dict[str, Any]] = None
    iceberg_schema: Optional[Union[Schema, Dict[str, Any]]] = None
    partition_spec: Optional[Any] = None
    write_properties: Dict[str, str] = Field(default_factory=dict)


class IcebergDestination(BaseDestination):
    """
    Asynchronous destination class that writes Pandas DataFrames to Apache Iceberg tables.
    Supports HMS catalog and S3 storage. Handles schema reconciliation.

    S3 Storage Organization:
    - Tables are stored in: s3://{bucket}/{warehouse-path}/{namespace}.db/{title}/
    - Data files: s3://.../{namespace}.db/{title}/data/*.parquet
    - Metadata: s3://.../{namespace}.db/{title}/metadata/*.json
    """

    type: Literal["iceberg"]
    config: IcebergDestinationConfig

    # Lazy load catalog
    _catalog: Optional[Catalog] = PrivateAttr(None)

    @property
    def catalog(self) -> Catalog:
        if self._catalog is None:
            catalog_conn_properties = self.config.model_dump_with_secrets(
                mode="json", by_alias=True
            )
            self._catalog = load_catalog(**catalog_conn_properties)
        return self._catalog

    async def submit(
        self,
        data: Union[pd.DataFrame, pa.Table],
    ) -> IcebergDestinationResponse:
        """
        Submit data to the configured Iceberg destination.

        Args:
            data (Union[pd.DataFrame, pa.Table]): Dataframe or table to write

        Raises:
            IcebergDestinationError: Error occurred during preprocessing or upload

        Returns:
            IcebergDestinationResponse: Info about resulting table
        """
        # Build table identifier
        resolved_table_id = self._build_table_identifier(
            table_name=self.config.table_name, namespace=self.config.namespace
        )

        # Get S3 location for response
        s3_location = self._get_s3_location(
            table_name=self.config.table_name, namespace=self.config.namespace
        )

        try:
            # Offload blocking I/O to a thread
            response = await asyncio.to_thread(
                self._submit_sync,
                data,
                resolved_table_id,
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

    @staticmethod
    def _build_table_identifier(
        table_name: str,
        namespace: str,
    ) -> str:
        return f"{namespace}.{table_name}"

    def _get_s3_location(
        self,
        table_name: str,
        namespace: str,
    ) -> str:
        """
        Construct the S3 location where Iceberg table data is stored.

        Returns:
            Human-readable S3 path for documentation/logging
        """
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
        s3_location = f"s3://{bucket}/{warehouse_path}{namespace}.db/{table_name}/"
        return s3_location

    def _submit_sync(
        self,
        data: Union[pd.DataFrame, pa.Table],
        table_identifier: str,
        s3_location: Optional[str] = None,
    ) -> IcebergDestinationResponse:
        """
        Synchronous core logic for schema reconciliation and writing.
        """
        try:
            # Convert pandas to Arrow
            if isinstance(data, pd.DataFrame):
                data = pa.Table.from_pandas(data, preserve_index=False)

            # Assign IDs if missing, ValueError from PyIceberg otherwise
            idd_arrow_schema = ArrowSchemaFieldIdAssigner(
                catalog=self.catalog
            ).assign_field_ids(
                schema=data.schema,
                table_identifier=table_identifier,
                preserve_existing_ids=True,
                enrich_from_catalog=True,
            )
            # data = data.cast(idd_arrow_schema, safe=False)
            # logger.info(f"PyArrow schema:\n{data.schema}")
            # TODO: parametrize format_version / add to config 
            # iceberg_schema = pyarrow_to_schema(idd_arrow_schema)
            # logger.info(f"PyIceberg schema:\n{iceberg_schema}")
            # new_arrow_schema = schema_to_pyarrow(iceberg_schema)
            # data = data.cast(new_arrow_schema, safe=False)
            namespace = table_identifier.split(".")[0]
            try:
                self.catalog.create_namespace(namespace=namespace)
            except NamespaceAlreadyExistsError:
                pass

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
                    iceberg_schema=data.schema,
                )
                created_new_table = True

            # Write data in a single transaction (atomic: schema + data)
            try:
                with table.transaction() as txn:
                    if not created_new_table:
                        # Update schema within the same transaction as data write
                        # This ensures atomicity: both succeed or both fail
                        # Note: .update_schema() skips metadata update if schemas are identical
                        txn.update_schema(
                            allow_incompatible_changes=False, case_sensitive=True
                        ).union_by_name(new_schema=data.schema, format_version=3)

                    # Append for new tables, overwrite for existing
                    if created_new_table:
                        txn.append(data)
                        logger.info(
                            f"Appended {data.num_rows} rows to new table {table_identifier}"
                        )
                    else:
                        txn.overwrite(data)
                        logger.info(
                            f"Overwrote table {table_identifier} with {data.num_rows} rows"
                        )
            except CommitFailedException as e:
                if created_new_table:
                    self.catalog.drop_table(table_identifier)
                    logger.info(f"Deleted created table: {table_identifier}")
                raise IcebergDestinationError(
                    message=f"Commit failed for table {table_identifier}",
                    cause=e,
                    table_identifier=table_identifier,
                    operation="write_data",
                ) from e                    
            except Exception as e:
                if created_new_table:
                    self.catalog.drop_table(table_identifier)
                    logger.info(f"Deleted created table: {table_identifier}")
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
                rows_written=data.num_rows,
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
            # If given None for partition_spec .create_table() raises an error
            create_kwargs: dict = {
                "identifier": table_identifier,
                "schema": iceberg_schema,
            }
            if self.config.partition_spec is not None:
                create_kwargs["partition_spec"] = self.config.partition_spec
            if self.config.write_properties is not None:
                create_kwargs["properties"] = self.config.write_properties

            table = self.catalog.create_table(**create_kwargs)
            logger.info(f"Created new table: {table_identifier}")
            return table
        except Exception as e:
            raise IcebergDestinationError(
                message=f"Failed to create table {table_identifier}",
                cause=e,
                table_identifier=table_identifier,
                operation="create_table",
            ) from e
