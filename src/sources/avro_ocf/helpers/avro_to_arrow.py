import pyarrow as pa
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from pyiceberg.catalog import Catalog
from pyiceberg.utils.schema_conversion import AvroSchemaConversion
from src.logger import LoggerFactory
from .avro_id import AvroSchemaFieldIdAssigner


logger = LoggerFactory.getLogger(__name__)


class AvroToArrowConverter:
    """
    Converts an Avro schema and data records to a PyArrow.
    Uses PyIceberg's standard pipeline to convert schema,
    then patches field types based on custom 'format' attributes (e.g., RFC3339Nano, uint64).
    Data is cast accordingly, clamps datetime values if not fitting into PyArrow timestamp[ns].
    """

    # Default mapping from custom Avro formats to PyArrow types
    _DEFAULT_FORMAT_MAPPING: Dict[str, pa.DataType] = {
        "RFC3339Nano": pa.timestamp("ns", tz="Europe/Moscow"),
        "ISO8601": pa.timestamp("ns", tz="Europe/Moscow"),
        "ISO8601Date": pa.date32(),
        "uint64": pa.uint64(),
    }

    # PyArrow timestamp[ns] int64 bounds (nanoseconds since epoch)
    _NS_MIN = -(2**63)  # -9223372036854775808 → 1677-09-21T00:12:43.145224193
    _NS_MAX = (2**63) - 1  # 9223372036854775807 → 2262-04-11T23:47:16.854775807

    def __init__(
        self,
        catalog: Optional[Catalog] = None,
        format_mapping: Optional[Dict[str, pa.DataType]] = None,
    ):
        """
        Args:
            catalog (Optional[Catalog], optional): Pyiceberg catalog to match column IDs. Defaults to None.
            format_mapping (Optional[Dict[str, pa.DataType]], optional): Custom "format" attribute type mapping. Defaults to None.
        """
        self.catalog = catalog
        self.format_mapping = format_mapping or self._DEFAULT_FORMAT_MAPPING

    def convert_schema(self, avro_schema: Dict[str, Any]) -> pa.Schema:
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

        return self._normalize_pyarrow_schema(schema=pa.schema(fixed_fields))

    @classmethod
    def records_to_table(
        cls, records: List[Dict[str, Any]], arrow_schema: pa.Schema, default_tz_offset: str = "+03:00"
    ) -> pa.Table:
        """Apply necessary data transforms to conform to arrow and create a Table.

        Args:
            records (List[Dict[str, Any]]): Records read by fastavro.
            arrow_schema (pa.Schema): Correct PyArrow schema.
            default_tz_offset (str, optional): Timezone to use with naive datetime values. Defaults to "+03:00".

        Returns:
            pa.Table: PyArrow Table.
        """
        arrays = [
            cls._build_array(
                [r.get(f.name) for r in records], f, default_tz_offset=default_tz_offset
            )
            for f in arrow_schema
        ]
        return pa.Table.from_arrays(arrays, schema=arrow_schema)

    def avro_to_table(self, records: List[Dict[str, Any]], avro_schema: Dict[str, Any], default_tz_offset: str = "+03:00") -> pa.Table:
        """Joint method to convert Apache Avro data records and schema into compatible PyArrow Table.

        Args:
            records (List[Dict[str, Any]]): Records read by fastavro.
            avro_schema (Dict[str, Any]): Apache Avro schema.
            default_tz_offset (str, optional): Timezone to use with naive datetime values.. Defaults to "+03:00".

        Returns:
            pa.Table: PyArrow Table.
        """
        arrow_schema = self.convert_schema(avro_schema=avro_schema)
        return self.records_to_table(records=records, arrow_schema=arrow_schema, default_tz_offset=default_tz_offset)

    @staticmethod
    def _sanitize_value(
        value: Any, dtype: pa.DataType, path: str = "", default_tz_offset: str = "+03:00"
    ) -> Any:
        if value is None:
            return None

        # UUID -> 16-byte binary
        if isinstance(value, uuid.UUID):
            return value.bytes
        if (
            isinstance(value, str)
            and len(value) == 36
            and value[8] == "-"
            and value[13] == "-"
        ):
            try:
                return uuid.UUID(value).bytes
            except ValueError:
                pass

        # uint64: strict string -> int
        if pa.types.is_uint64(dtype):
            if isinstance(value, str):
                try:
                    return int(value)
                except ValueError as e:
                    raise ValueError(
                        f"Cannot convert '{value}' to uint64 at '{path}'"
                    ) from e
            return value

        # Timestamp: append default offset if naive
        if pa.types.is_timestamp(dtype) and dtype.tz is not None:
            if isinstance(value, str):
                # Check for explicit timezone (ends with 'Z' or +/-HH:MM)
                has_tz = value.endswith("Z") or (len(value) >= 6 and value[-6] in "+-")
                if not has_tz:
                    return f"{value}{default_tz_offset}"  # Assign MSK offset
            return value

        # Date32: strip time if present
        if pa.types.is_date(dtype):
            if isinstance(value, str) and "T" in value:
                return value[:10]
            return value

        return value

    @classmethod
    def _parse_iso_to_epoch_ns_clamped(
        cls, value: str, target_tz: str, default_tz_offset: str = "+03:00"
    ) -> int:
        """
        Parse ISO8601/RFC3339 string to epoch nanoseconds, clamping to PyArrow's int64 bounds.

        Business logic:
        - Naive strings (no timezone) are assigned MSK (+03:00)
        - Explicit timezones are preserved
        - Out-of-range values are clamped to min/max timestamp[ns] bounds
        """
        if not isinstance(value, str):
            return None

        # Handle 'Z' suffix → UTC
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"

        # Detect explicit timezone offset (+HH:MM or -HH:MM at end)
        has_tz = len(value) >= 6 and value[-6] in "+-" and ":" in value[-3:]

        if not has_tz:
            # Naive string: assign MSK offset per business logic
            value = value + default_tz_offset

        try:
            # Parse with Python's reliable ISO parser
            dt = datetime.fromisoformat(value)

            # Convert to epoch nanoseconds
            epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
            delta = dt - epoch
            total_seconds = delta.total_seconds()
            epoch_ns = int(total_seconds * 1_000_000_000 + delta.microseconds * 1000)

        except (ValueError, OverflowError):
            # If parsing fails entirely, clamp to min (safe fallback)
            return cls._NS_MIN

        # CLAMP to PyArrow timestamp[ns] int64 bounds
        if epoch_ns < cls._NS_MIN:
            return cls._NS_MIN
        if epoch_ns > cls._NS_MAX:
            return cls._NS_MAX

        return epoch_ns

    @classmethod
    def _build_array(
        cls,
        col_data: List[Any],
        field: pa.Field,
        path: str = "",
        default_tz_offset: str = "+03:00",
    ) -> pa.Array:
        dtype = field.type
        current_path = f"{path}.{field.name}" if path else field.name

        # Extension Types
        if hasattr(dtype, "storage_type"):
            clean_data = [
                cls._sanitize_value(v, dtype, current_path, default_tz_offset) for v in col_data
            ]
            storage_field = pa.field(field.name, dtype.storage_type, field.nullable)
            storage_arr = cls._build_array(
                clean_data, storage_field, f"{current_path}__storage", default_tz_offset
            )
            try:
                return pa.ExtensionArray.from_storage(dtype, storage_arr)
            except pa.ArrowInvalid:
                return storage_arr

        # List / LargeList
        if pa.types.is_list(dtype) or pa.types.is_large_list(dtype):
            is_large = pa.types.is_large_list(dtype)
            offsets = [0]
            values = []
            for item in col_data:
                if item is None:
                    offsets.append(offsets[-1])
                else:
                    offsets.append(offsets[-1] + len(item))
                    values.extend(item)

            value_field = pa.field("item", dtype.value_type, dtype.value_field.nullable)
            child_array = cls._build_array(
                values, value_field, f"{current_path}[]", default_tz_offset
            )
            offsets_type = pa.int64() if is_large else pa.int32()
            return (
                pa.LargeListArray.from_arrays(
                    pa.array(offsets, type=offsets_type), child_array
                )
                if is_large
                else pa.ListArray.from_arrays(
                    pa.array(offsets, type=offsets_type), child_array
                )
            )

        # Struct
        if pa.types.is_struct(dtype):
            struct_rows = [rec if isinstance(rec, dict) else {} for rec in col_data]
            sub_arrays = []
            for sub_field in dtype:
                sub_data = [
                    cls._sanitize_value(
                        row.get(sub_field.name),
                        sub_field.type,
                        f"{current_path}.{sub_field.name}",
                        default_tz_offset,
                    )
                    for row in struct_rows
                ]
                sub_arrays.append(
                    cls._build_array(sub_data, sub_field, current_path, default_tz_offset)
                )
            return pa.StructArray.from_arrays(sub_arrays, fields=list(dtype))

        # Primitives
        clean_data = [
            cls._sanitize_value(v, dtype, current_path, default_tz_offset) for v in col_data
        ]

        if not clean_data:
            return pa.array([], type=dtype)

        # TIMESTAMP: Parse with clamping → epoch ns → PyArrow array
        if pa.types.is_timestamp(dtype):
            target_tz = dtype.tz
            epoch_values = []
            for v in clean_data:
                if v is None:
                    epoch_values.append(None)
                elif isinstance(v, (int, float)):
                    # Already epoch nanoseconds: clamp if out of bounds
                    val = int(v)
                    if val < cls._NS_MIN:
                        epoch_values.append(cls._NS_MIN)
                    elif val > cls._NS_MAX:
                        epoch_values.append(cls._NS_MAX)
                    else:
                        epoch_values.append(val)
                elif isinstance(v, str):
                    try:
                        epoch_values.append(
                            cls._parse_iso_to_epoch_ns_clamped(v, target_tz, default_tz_offset)
                        )
                    except Exception as e:
                        logger.warning(
                            f"⚠️ Warning: Clamping invalid timestamp '{v}' at '{current_path}': {e}"
                        )
                        epoch_values.append(cls._NS_MIN)
                else:
                    epoch_values.append(None)

            # Create array from int64 epoch values, then attach timezone metadata
            arr = pa.array(epoch_values, type=pa.int64())
            return arr.cast(pa.timestamp("ns", tz=target_tz))

        # DATE32: Strip time, parse to date, cast
        if pa.types.is_date(dtype):
            date_values = []
            for v in clean_data:
                if v is None:
                    date_values.append(None)
                elif isinstance(v, str):
                    date_str = v[:10] if "T" in v else v
                    date_values.append(date_str)
                else:
                    date_values.append(v)
            return pa.array(date_values, type=pa.string()).cast(dtype)

        # uint64: Already handled in _sanitize_value
        if pa.types.is_uint64(dtype):
            return pa.array(clean_data, type=dtype)

        # Other primitives
        return pa.array(clean_data, type=dtype)

    @staticmethod
    def _normalize_pyarrow_schema(schema: pa.Schema) -> pa.Schema:
        """Fix Pyiceberg/Pyarrow array element/item incompatibility.

        Args:
            schema (pa.Schema): Pyiceberg generated Arrow schema.

        Returns:
            pa.Schema: Fixed Arrow schema.
        """
        def _fix_type(dtype):
            if pa.types.is_list(dtype):
                vf = dtype.value_field
                return pa.list_(pa.field("item", vf.type, nullable=True))
            elif pa.types.is_large_list(dtype):
                vf = dtype.value_field
                return pa.large_list(pa.field("item", vf.type, nullable=True))
            elif pa.types.is_struct(dtype):
                new_fields = [
                    pa.field(f.name, _fix_type(f.type), f.nullable) for f in dtype
                ]
                return pa.struct(new_fields)
            return dtype

        return pa.schema([pa.field(f.name, _fix_type(f.type), f.nullable) for f in schema])

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
