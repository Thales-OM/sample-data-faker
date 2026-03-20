import asyncio
from typing import Any, Dict, Optional
from dataclasses import dataclass
import pandas as pd
import pyarrow as pa
from pyiceberg.io.pyarrow import pyarrow_to_schema
from pyiceberg.catalog import Catalog, load_catalog
from pyiceberg.table import Table
from pyiceberg.exceptions import NoSuchTableError
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
        catalog_name: str,
        table_identifier: str,
        catalog_conf: Optional[Dict[str, Any]] = None,
        partition_spec: Optional[Any] = None,
        write_properties: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize the Iceberg Destination.

        Args:
            catalog_name: Name of the Iceberg catalog (e.g., 'hive', 'rest').
            table_identifier: Fully qualified table name (e.g., 'namespace.table_name').
            catalog_conf: Configuration dictionary for the catalog (uri, warehouse, s3 endpoint, etc.).
            partition_spec: Optional Iceberg partition spec.
            write_properties: Optional properties for the write operation (e.g., commit.manifest.target-size-bytes).
        """
        self.catalog_name = catalog_name
        self.table_identifier = table_identifier
        self.catalog_conf = catalog_conf or {}
        self.partition_spec = partition_spec
        self.write_properties = write_properties or {}

        # Lazy load catalog
        self._catalog: Optional[Catalog] = None

    @property
    def catalog(self) -> Catalog:
        if self._catalog is None:
            self._catalog = load_catalog(self.catalog_name, **self.catalog_conf)
        return self._catalog

    async def submit(self, df: pd.DataFrame) -> IcebergDestinationResponse:
        """
        Submit data to the configured Iceberg destination.

        This method is async, but the underlying I/O is synchronous.
        It is offloaded to a thread to prevent blocking the event loop.
        """
        try:
            # Offload blocking I/O to a thread
            response = await asyncio.to_thread(self._submit_sync, df)
            return response
        except Exception as e:
            logger.error(
                f"Failed to write to Iceberg table {self.table_identifier}: {e}"
            )
            raise

    def _submit_sync(self, df: pd.DataFrame) -> IcebergDestinationResponse:
        """
        Synchronous core logic for schema reconciliation and writing.
        """
        # 1. Check if table exists
        table = None
        created_new_table = False

        try:
            table = self.catalog.load_table(self.table_identifier)
            logger.info(f"Loaded existing table: {self.table_identifier}")
        except NoSuchTableError:
            logger.info(
                f"Table {self.table_identifier} does not exist. Creating new table."
            )
            created_new_table = True

        # 2. Schema Reconciliation & Conversion to PyArrow
        # We convert to PyArrow early to handle complex types (structs, lists) better than Pandas
        arrow_table = pa.Table.from_pandas(df, preserve_index=False)

        if table:
            # Table Exists: Align DataFrame to Table Schema
            arrow_table = self._reconcile_to_existing_schema(arrow_table, table)
        else:
            # Table New: Create Table based on DataFrame Schema
            # We derive Iceberg schema from the Arrow schema inferred from DF
            table = self._create_new_table(arrow_table)

        # 3. Write to Iceberg
        # Use overwrite or append logic as needed. Here we use 'append' by default.
        transaction = table.transaction()
        writer = (
            transaction.append_overwrite()
            if not created_new_table
            else transaction.append()
        )

        # Note: pyiceberg 0.6+ supports write_dataframe directly, but using arrow_table
        # gives us more control over the schema we verified above.
        writer.write_arrow(arrow_table)
        transaction.commit_transaction()

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

    def _reconcile_to_existing_schema(
        self, arrow_table: pa.Table, table: Table
    ) -> pa.Table:
        """
        Aligns the incoming Arrow table to the existing Iceberg table schema.

        Rules:
        1. If column exists in Iceberg but not in DF: Fill with Nulls (if nullable).
        2. If column exists in DF but not in Iceberg: Drop it.
        3. If types mismatch: Attempt safe cast, else raise.
        """
        iceberg_schema = table.schema()
        incoming_schema = arrow_table.schema

        target_fields = []
        new_arrays = []

        # Map incoming columns for quick lookup
        incoming_field_map = {field.name: field for field in incoming_schema}

        for field in iceberg_schema.fields:
            field_name = field.name

            # Check if field exists in incoming data
            if field_name in incoming_field_map:
                incoming_field = incoming_field_map[field_name]

                # Type Check (Simplified: rely on PyArrow cast capabilities)
                # In production, you might want stricter type checking here
                if incoming_field.type != field.field_type:
                    try:
                        # Attempt to cast the column to the target Iceberg type
                        column = arrow_table.column(field_name).cast(field.field_type)
                        new_arrays.append(column)
                    except pa.ArrowInvalid as e:
                        raise ValueError(
                            f"Schema mismatch for column '{field_name}': "
                            f"Cannot cast {incoming_field.type} to {field.field_type}. Error: {e}"
                        )
                else:
                    new_arrays.append(arrow_table.column(field_name))

                target_fields.append(incoming_field)
            else:
                # Column missing in DF. Check if nullable in Iceberg.
                if field.optional:
                    logger.warning(
                        f"Column '{field_name}' missing in source data. Filling with NULLs."
                    )
                    # Create an array of nulls with the correct type and length
                    null_array = pa.nulls(arrow_table.num_rows, type=field.field_type)
                    new_arrays.append(null_array)
                    # We need to construct a PyArrow field that matches the Iceberg field definition
                    # PyArrow field name, type, nullable
                    pa_field = pa.field(
                        field_name, field.field_type, nullable=field.optional
                    )
                    target_fields.append(pa_field)
                else:
                    raise ValueError(
                        f"Non-nullable column '{field_name}' is missing from source DataFrame "
                        f"and cannot be filled with NULLs."
                    )

        # Reorder columns to match Iceberg schema order exactly
        # (PyArrow table creation requires fields and arrays to match index)
        # Note: target_fields here are PyArrow fields constructed/selected to match iceberg order
        # We need to ensure the names match the iceberg schema exactly for the final table
        final_schema = pa.schema(
            [
                pa.field(f.name, f.type, nullable=f.optional)
                for f in iceberg_schema.fields
            ]
        )

        # We need to map the new_arrays back to the exact order of iceberg_schema.fields
        # The loop above iterated iceberg_schema.fields, so new_arrays is already in correct order
        final_table = pa.Table.from_arrays(new_arrays, schema=final_schema)

        return final_table

    def _create_new_table(self, arrow_table: pa.Table) -> Table:
        """
        Creates a new Iceberg table based on the schema of the provided Arrow table.
        """
        # Convert PyArrow schema to Iceberg Schema
        # pyiceberg provides a utility for this

        # Infer Iceberg Schema from PyArrow
        iceberg_schema = pyarrow_to_schema(arrow_table.schema)

        table = self.catalog.create_table(
            identifier=self.table_identifier,
            schema=iceberg_schema,
            partition_spec=self.partition_spec,
            properties=self.write_properties,
        )
        return table
