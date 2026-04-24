import pyarrow as pa
from typing import Dict, Any, Optional
from pyiceberg.catalog import Catalog
from pyiceberg.utils.schema_conversion import AvroSchemaConversion
from src.logger import LoggerFactory
from .avro_id import AvroSchemaFieldIdAssigner


logger = LoggerFactory.getLogger(__name__)


class CustomAvroToArrowConverter:
    """
    Converts an Avro schema to a PyArrow schema using PyIceberg's standard pipeline,
    then patches field types based on custom 'format' attributes (e.g., RFC3339Nano, uint64).
    """

    # Default mapping from custom Avro formats to PyArrow types
    DEFAULT_FORMAT_MAPPING: Dict[str, pa.DataType] = {
        "RFC3339Nano": pa.timestamp("ns"),
        "ISO8601": pa.timestamp("ns"),
        "ISO8601Date": pa.date32(),
        "uint64": pa.uint64(),
    }

    def __init__(
        self,
        catalog: Optional[Catalog] = None,
        format_mapping: Optional[Dict[str, pa.DataType]] = None,
    ):
        self.catalog = catalog
        self.format_mapping = format_mapping or self.DEFAULT_FORMAT_MAPPING

    def convert(self, avro_schema: Dict[str, Any]) -> pa.Schema:
        """
        Main conversion method.
        1. Assigns field IDs to avoid Iceberg collisions.
        2. Converts Avro -> Iceberg -> PyArrow.
        3. Traverses the PyArrow schema and patches types based on custom Avro 'format' attributes.
        """
        idd_avro_schema = AvroSchemaFieldIdAssigner(
            catalog=self.catalog
        ).assign_field_ids(avro_schema=avro_schema)
        iceberg_schema = AvroSchemaConversion().avro_to_iceberg(
            avro_schema=idd_avro_schema
        )
        initial_arrow_schema = iceberg_schema.as_arrow()

        # Extract all custom formats from Avro schema into path-based map
        format_paths = self._extract_format_paths(avro_schema)

        # Traverse and patch the PyArrow schema
        fixed_fields = [
            self._fix_field_recursively(field, field.name, format_paths)
            for field in initial_arrow_schema
        ]

        return pa.schema(fixed_fields)

    def _extract_format_paths(
        self, avro_schema: Dict[str, Any], prefix: str = ""
    ) -> Dict[str, str]:
        """Flattens the Avro schema into { 'dotted.field.path': 'format_value' }"""
        formats = {}
        if not isinstance(avro_schema, dict) or avro_schema.get("type") != "record":
            return formats

        for field in avro_schema.get("fields", []):
            name = field["name"]
            path = f"{prefix}.{name}" if prefix else name

            # Capture format if explicitly defined on the field
            if "format" in field:
                formats[path] = field["format"]

            # Recurse into the type definition
            self._extract_from_type(field["type"], path, formats)

        return formats

    def _extract_from_type(
        self, avro_type: Any, path: str, formats: Dict[str, str]
    ) -> None:
        """Helper to traverse union, record, and array types."""
        if isinstance(avro_type, str):
            return  # Primitive type, nothing to recurse into
        if isinstance(avro_type, list):
            # Handle union types (e.g., ["null", actual_type])
            non_null = [t for t in avro_type if t != "null"]
            if len(non_null) == 1:
                self._extract_from_type(non_null[0], path, formats)
            return
        if isinstance(avro_type, dict):
            t = avro_type.get("type")
            if t == "record":
                formats.update(self._extract_format_paths(avro_type, prefix=path))
            elif t == "array":
                items = avro_type.get("items")
                # Track array items with a consistent placeholder to match PyArrow's structure
                item_path = f"{path}._item"
                if isinstance(items, str):
                    return  # Primitive array item
                self._extract_from_type(items, item_path, formats)

    def _fix_field_recursively(
        self, arrow_field: pa.Field, path: str, format_paths: Dict[str, str]
    ) -> pa.Field:
        """Recursively traverses PyArrow schema and applies type patches."""
        fmt = format_paths.get(path)
        current_type = arrow_field.type

        # Override type if a custom format is mapped
        if fmt and fmt in self.format_mapping:
            current_type = self.format_mapping[fmt]

        # Recursively handle nested structs
        if pa.types.is_struct(current_type):
            new_fields = []
            for i in range(current_type.num_fields):
                sub_field = current_type.field(i)
                sub_path = f"{path}.{sub_field.name}"
                new_fields.append(
                    self._fix_field_recursively(sub_field, sub_path, format_paths)
                )
            current_type = pa.struct(new_fields)

        # Recursively handle lists
        elif pa.types.is_list(current_type):
            item_path = f"{path}._item"
            temp_item_field = pa.field("_item", current_type.value_type)
            fixed_item_field = self._fix_field_recursively(
                temp_item_field, item_path, format_paths
            )
            current_type = pa.list_(fixed_item_field.type)

        # Return corrected field, preserving original name, nullability, and metadata
        return pa.field(
            name=arrow_field.name,
            type=current_type,
            nullable=arrow_field.nullable,
            metadata=arrow_field.metadata,
        )
