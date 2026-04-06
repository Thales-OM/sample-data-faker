import asyncio
from typing import Any, Dict, Optional, Union
from dataclasses import dataclass
import pandas as pd
import pyarrow as pa
from pyiceberg.io.pyarrow import pyarrow_to_schema
from pyiceberg.catalog import Catalog, load_catalog
from pyiceberg.table import Table
from pyiceberg.exceptions import NoSuchTableError
from pyiceberg.schema import Schema
from pyiceberg.utils.schema_conversion import AvroSchemaConversion
from src.config import HMSS3DestinationConfig
from src.logger import LoggerFactory
from .base import BaseDestination, BaseDestinationResponse


logger = LoggerFactory.getLogger(__name__)


@dataclass
class IcebergDestinationResponse(BaseDestinationResponse):
    """Response object containing metadata about the write operation."""

    table_identifier: str
    rows_written: int
    snapshot_id: Optional[int]
    created_new_table: bool


class IcebergDestination(BaseDestination):
    """
    Asynchronous destination class that writes Pandas DataFrames to Apache Iceberg tables.
    Supports HMS catalog and S3 storage. Handles schema reconciliation (null-filling)
    but does not evolve the destination table schema.
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
            write_properties: Optional properties for the write operation (e.g., commit.manifest.target-size-bytes).
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

    async def submit(
        self,
        df: pd.DataFrame,
        table_identifier: str,
        avro_schema: Optional[Dict[str, Any]] = None,
        iceberg_schema: Optional[Union[Schema, Dict[str, Any]]] = None,
    ) -> IcebergDestinationResponse:
        """
        Submit data to the configured Iceberg destination.

        This method is async, but the underlying I/O is synchronous.
        It is offloaded to a thread to prevent blocking the event loop.
        """
        try:
            # Offload blocking I/O to a thread
            response = await asyncio.to_thread(
                self._submit_sync, df, avro_schema, iceberg_schema
            )
            return response
        except Exception as e:
            logger.error(f"Failed to write to Iceberg table {table_identifier}: {e}")
            raise

    def _submit_sync(
        self,
        df: pd.DataFrame,
        table_identifier: str,
        avro_schema: Optional[Dict[str, Any]] = None,
        iceberg_schema: Optional[Union[Schema, Dict[str, Any]]] = None,
    ) -> IcebergDestinationResponse:
        """
        Synchronous core logic for schema reconciliation and writing.
        """
        # Generate schema
        if avro_schema:
            if iceberg_schema:
                logger.warning(
                    "Both avro_schema and iceberg_schema were provided. iceberg_schema takes precedence."
                )
            else:
                iceberg_schema = AvroSchemaConversion().avro_to_iceberg(
                    avro_schema=avro_schema
                )
        if isinstance(iceberg_schema, dict):
            iceberg_schema = Schema.model_validate(iceberg_schema)

        arrow_table = pa.Table.from_pandas(df, preserve_index=False)

        # Check if table exists
        created_new_table = False
        try:
            table = self.catalog.load_table(table_identifier)
            logger.info(f"Loaded existing table: {table_identifier}")
        except NoSuchTableError:
            logger.info(f"Table {table_identifier} does not exist. Creating new table.")
            table = self._create_new_table(
                table_identifier=table_identifier,
                arrow_table=arrow_table,
                iceberg_schema=iceberg_schema,
            )
            created_new_table = True

        with table.transaction() as txn:
            if not created_new_table:
                txn.update_schema(allow_incompatible_changes=False).union_by_name(
                    new_schema=iceberg_schema
                )
                txn.overwrite(df=arrow_table)
            else:
                txn.append(df=arrow_table)

        # Retrieve snapshot info
        table.refresh()
        current_snapshot = table.current_snapshot()
        snapshot_id = current_snapshot.snapshot_id if current_snapshot else None

        return IcebergDestinationResponse(
            table_identifier=self.table_identifier,
            rows_written=arrow_table.num_rows,
            snapshot_id=snapshot_id,
            created_new_table=created_new_table,
        )

    def _create_new_table(
        self,
        table_identifier: str,
        arrow_table: pa.Table,
        iceberg_schema: Optional[Schema] = None,
    ) -> Table:
        """
        Creates a new Iceberg table based on the prior schema or the provided Arrow table.
        """
        if not iceberg_schema:
            iceberg_schema = pyarrow_to_schema(arrow_table.schema)

        table = self.catalog.create_table(
            identifier=table_identifier,
            schema=iceberg_schema,
            partition_spec=self.partition_spec,
            properties=self.write_properties,
        )
        return table
