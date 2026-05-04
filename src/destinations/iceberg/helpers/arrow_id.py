from typing import Optional, Dict
import pyarrow as pa
from pyiceberg.catalog import Catalog
from pyiceberg.exceptions import NoSuchTableError
from src.logger import LoggerFactory

logger = LoggerFactory.getLogger(__name__)

PARQUET_FIELD_ID_META_KEY = "PARQUET:field_id"


class ArrowSchemaFieldIdAssigner:
    """
    Smart field ID assigner for PyArrow schemas.

    Assigns field IDs to PyArrow schemas for Iceberg/Parquet compatibility.
    """

    def __init__(self, catalog: Optional[Catalog] = None):
        self.catalog = catalog

    def assign_field_ids(
        self,
        schema: pa.Schema,
        table_identifier: Optional[str] = None,
        start_id: int = 1,
        preserve_existing_ids: bool = True,
        enrich_from_catalog: bool = True,
    ) -> pa.Schema:
        """
        Assign field IDs to a PyArrow table's schema.\n
        Priority order:\n
            1. Existing ID in schema/metadata (highest priority, if preserve_existing_ids=True)
            2. ID from catalog lookup (if enrich_from_catalog=True)
            3. New sequential ID from start_id (lowest priority)

        Args:
            schema: PyArrow Schema without field IDs in metadata
            table_identifier: Optional table identifier to look up existing IDs
            start_id: Starting ID for new assignments (default: 1)
            preserve_existing_ids: If True, preserve IDs already in field metadata (default: True)
            enrich_from_catalog: If True, query catalog for existing field ID mappings (default: True)

        Returns:
            PyArrow Schema with field IDs added to field metadata
        """
        existing_mapping: Dict[str, int] = {}
        if enrich_from_catalog and table_identifier and self.catalog:
            existing_mapping = self._get_existing_field_mapping(table_identifier)

        enriched_schema = self._enrich_schema_with_field_ids(
            schema,
            existing_mapping=existing_mapping,
            next_field_id=[start_id],
            preserve_existing_ids=preserve_existing_ids,
        )
        return enriched_schema

    def _get_existing_field_mapping(self, table_identifier: str) -> Dict[str, int]:
        try:
            if not self.catalog:
                return {}
            table = self.catalog.load_table(table_identifier)
            schema = table.schema()
            mapping = {field.name: field.field_id for field in schema.fields}
            logger.debug(
                f"Loaded {len(mapping)} field mappings from {table_identifier}"
            )
            return mapping
        except NoSuchTableError:
            logger.debug(f"Table {table_identifier} does not exist")
            return {}
        except Exception as e:
            logger.warning(f"Failed to load mapping from {table_identifier}: {e}")
            raise

    def _enrich_schema_with_field_ids(
        self,
        schema: pa.Schema,
        existing_mapping: Dict[str, int],
        next_field_id: list[int],
        preserve_existing_ids: bool,
    ) -> pa.Schema:
        enriched_fields = [
            self._enrich_field(
                field, existing_mapping, next_field_id, preserve_existing_ids
            )
            for field in schema
        ]
        return pa.schema(enriched_fields, metadata=schema.metadata)

    def _enrich_field(
        self,
        field: pa.Field,
        existing_mapping: Dict[str, int],
        next_field_id: list[int],
        preserve_existing_ids: bool,
    ) -> pa.Field:
        field_name = field.name

        # Priority 1: Preserve existing ID from metadata
        if preserve_existing_ids:
            meta = self._normalize_metadata(field.metadata)
            if PARQUET_FIELD_ID_META_KEY in meta:
                logger.debug(
                    f"Preserved existing ID {meta[PARQUET_FIELD_ID_META_KEY]} for '{field_name}'"
                )
                enriched_type = self._enrich_type(
                    field.type, existing_mapping, next_field_id, preserve_existing_ids
                )
                return field.with_type(enriched_type)

        # Priority 2: Catalog mapping
        if field_name in existing_mapping:
            field_id = existing_mapping[field_name]
            logger.debug(f"Using catalog ID {field_id} for '{field_name}'")
        else:
            # Priority 3: New sequential ID
            field_id = next_field_id[0]
            next_field_id[0] += 1
            logger.debug(f"Assigned new ID {field_id} for '{field_name}'")

        metadata = self._normalize_metadata(field.metadata)
        metadata[PARQUET_FIELD_ID_META_KEY] = str(field_id)
        enriched_type = self._enrich_type(
            field.type, existing_mapping, next_field_id, preserve_existing_ids
        )
        return field.with_type(enriched_type).with_metadata(metadata)

    def _normalize_metadata(self, meta: Optional[Dict]) -> Dict[str, str]:
        if meta is None:
            return {}
        result = {}
        for k, v in meta.items():
            key = k.decode() if isinstance(k, bytes) else str(k)
            value = v.decode() if isinstance(v, bytes) else str(v)
            result[key] = value
        return result

    def _enrich_type(
        self,
        data_type: pa.DataType,
        existing_mapping: Dict[str, int],
        next_field_id: list[int],
        preserve_existing_ids: bool,
    ) -> pa.DataType:
        if pa.types.is_struct(data_type):
            return self._enrich_struct_type(
                data_type, existing_mapping, next_field_id, preserve_existing_ids
            )
        elif pa.types.is_list(data_type):
            return self._enrich_list_type(
                data_type, existing_mapping, next_field_id, preserve_existing_ids
            )
        elif pa.types.is_map(data_type):
            return self._enrich_map_type(
                data_type, existing_mapping, next_field_id, preserve_existing_ids
            )
        return data_type

    def _enrich_struct_type(
        self,
        struct_type: pa.StructType,
        existing_mapping: Dict[str, int],
        next_field_id: list[int],
        preserve_existing_ids: bool,
    ) -> pa.StructType:
        enriched_fields = [
            self._enrich_field(
                f, existing_mapping, next_field_id, preserve_existing_ids
            )
            for f in struct_type
        ]
        return pa.struct(enriched_fields)

    def _enrich_list_type(
        self,
        list_type: pa.ListType,
        existing_mapping: Dict[str, int],
        next_field_id: list[int],
        preserve_existing_ids: bool,
    ) -> pa.ListType:
        """Enrich list: the value_field gets field-id metadata."""
        enriched_value = self._enrich_field(
            list_type.value_field,
            existing_mapping,
            next_field_id,
            preserve_existing_ids,
        )
        return pa.list_(enriched_value)

    def _enrich_map_type(
        self,
        map_type: pa.MapType,
        existing_mapping: Dict[str, int],
        next_field_id: list[int],
        preserve_existing_ids: bool,
    ) -> pa.MapType:
        """Enrich map: both key_field and item_field get field-id metadata."""
        enriched_key = self._enrich_field(
            map_type.key_field, existing_mapping, next_field_id, preserve_existing_ids
        )
        enriched_item = self._enrich_field(
            map_type.item_field, existing_mapping, next_field_id, preserve_existing_ids
        )
        return pa.map_(
            enriched_key.type, enriched_item.type, keys_sorted=map_type.keys_sorted
        )
