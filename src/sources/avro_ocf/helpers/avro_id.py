from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from pyiceberg.catalog import Catalog
from pyiceberg.exceptions import NoSuchTableError

from src.logger import LoggerFactory

logger = LoggerFactory.getLogger(__name__)


@dataclass
class FieldIdMapping:
    field_name: str
    field_id: int
    field_type: str


class AvroSchemaFieldIdAssigner:
    """
    Smart field ID assigner for Avro schemas.

    Assigns field IDs to Avro schemas for Iceberg compatibility while
    preserving existing IDs from schema fields or catalog lookups.
    """

    def __init__(self, catalog: Optional[Catalog] = None):
        self.catalog = catalog

    def assign_field_ids(
        self,
        avro_schema: Dict[str, Any],
        table_identifier: Optional[str] = None,
        start_id: int = 1,
        preserve_existing_ids: bool = True,
        enrich_from_catalog: bool = True,
    ) -> Dict[str, Any]:
        """
        Assign field IDs to an Avro schema.\n
        Priority order:\n
            1. Existing ID in schema/metadata (highest priority, if preserve_existing_ids=True)
            2. ID from catalog lookup (if enrich_from_catalog=True)
            3. New sequential ID from start_id (lowest priority)

        Args:
            avro_schema: Avro schema dict without field IDs
            table_identifier: Optional table identifier to look up existing IDs
            start_id: Starting ID for new assignments (default: 1)
            preserve_existing_ids: If True, preserve IDs already in field definitions (default: True)
            enrich_from_catalog: If True, query catalog for existing field ID mappings (default: True)

        Returns:
            Avro schema dict with field IDs added
        """

        if "fields" not in avro_schema:
            return avro_schema

        existing_mapping = {}
        if enrich_from_catalog and table_identifier and self.catalog:
            existing_mapping = self._get_existing_field_mapping(table_identifier)

        enriched_schema = self._enrich_schema_with_field_ids(
            avro_schema,
            existing_mapping=existing_mapping,
            next_field_id=[start_id],
            preserve_existing_ids=preserve_existing_ids,
        )

        if existing_mapping and enrich_from_catalog:
            logger.info(
                f"Preserved {len(existing_mapping)} existing field IDs from catalog table {table_identifier}"
            )

        return enriched_schema

    def _get_existing_field_mapping(self, table_identifier: str) -> Dict[str, int]:
        try:
            if not self.catalog:
                return {}
            table = self.catalog.load_table(table_identifier)
            schema = table.schema()
            mapping = {field.name: field.field_id for field in schema.fields}
            return mapping
        except NoSuchTableError:
            logger.warning(
                f"Table {table_identifier} does not exist, will assign new IDs"
            )
            return {}
        except Exception as e:
            logger.warning(
                f"Failed to load existing field mapping from {table_identifier}: {e}"
            )
            raise

    def _enrich_schema_with_field_ids(
        self,
        avro_schema: Dict[str, Any],
        existing_mapping: Dict[str, int],
        next_field_id: List[int],
        preserve_existing_ids: bool,
    ) -> Dict[str, Any]:
        result = avro_schema.copy()
        if "fields" in avro_schema:
            enriched_fields = []
            for field in avro_schema["fields"]:
                enriched_field = self._enrich_field(
                    field=field,
                    existing_mapping=existing_mapping,
                    next_field_id=next_field_id,
                    preserve_existing_ids=preserve_existing_ids,
                )
                enriched_fields.append(enriched_field)
            result["fields"] = enriched_fields
        return result

    def _enrich_field(
        self,
        field: Dict[str, Any],
        existing_mapping: Dict[str, int],
        next_field_id: List[int],
        preserve_existing_ids: bool,
    ) -> Dict[str, Any]:
        field_name = field.get("name", "")
        enriched = field.copy()

        # Priority 1: Preserve existing ID from field definition
        if preserve_existing_ids and "field-id" in field:
            enriched["field-id"] = field["field-id"]
        # Priority 2: Use catalog mapping
        elif field_name in existing_mapping:
            enriched["field-id"] = existing_mapping[field_name]
        # Priority 3: Assign new sequential ID
        else:
            enriched["field-id"] = next_field_id[0]
            next_field_id[0] += 1

        self._enrich_field_type(
            enriched, existing_mapping, next_field_id, preserve_existing_ids
        )
        return enriched

    def _enrich_field_type(
        self,
        field: Dict[str, Any],
        existing_mapping: Dict[str, int],
        next_field_id: List[int],
        preserve_existing_ids: bool,
    ) -> None:
        field_type = field.get("type")
        if isinstance(field_type, list):
            for i, union_member in enumerate(field_type):
                if isinstance(union_member, dict):
                    field["type"][i] = self._enrich_type_def(
                        union_member,
                        existing_mapping,
                        next_field_id,
                        preserve_existing_ids,
                    )
        elif isinstance(field_type, dict):
            field["type"] = self._enrich_type_def(
                field_type, existing_mapping, next_field_id, preserve_existing_ids
            )

    def _enrich_type_def(
        self,
        type_def: Dict[str, Any],
        existing_mapping: Dict[str, int],
        next_field_id: List[int],
        preserve_existing_ids: bool,
    ) -> Dict[str, Any]:
        """Enrich a type definition - handles nested records, arrays, maps."""
        type_name = type_def.get("type")

        if "fields" in type_def:
            # Record type with fields
            enriched_fields = [
                self._enrich_field(
                    f, existing_mapping, next_field_id, preserve_existing_ids
                )
                for f in type_def["fields"]
            ]
            result = type_def.copy()
            result["fields"] = enriched_fields
            return result
        elif type_name == "array":
            result = type_def.copy()
            self._enrich_array_type(
                result, existing_mapping, next_field_id, preserve_existing_ids
            )
            return result
        elif type_name == "map":
            result = type_def.copy()
            self._enrich_map_type(
                result, existing_mapping, next_field_id, preserve_existing_ids
            )
            return result
        elif type_name == "record":
            if "fields" in type_def:
                result = type_def.copy()
                result["fields"] = [
                    self._enrich_field(
                        f, existing_mapping, next_field_id, preserve_existing_ids
                    )
                    for f in type_def["fields"]
                ]
                return result
        return type_def

    def _enrich_array_type(
        self,
        type_def: Dict[str, Any],
        existing_mapping: Dict[str, int],
        next_field_id: List[int],
        preserve_existing_ids: bool,
    ) -> None:
        """Enrich array: assign element-id and handle nested items."""
        type_def["element-id"] = next_field_id[0]
        next_field_id[0] += 1

        items = type_def.get("items")
        if isinstance(items, dict):
            items_type = items.get("type")
            if isinstance(items_type, str) and items_type in ("record", "array", "map"):
                # Complex nested type
                type_def["items"] = self._enrich_type_def(
                    items, existing_mapping, next_field_id, preserve_existing_ids
                )
            elif "fields" in items:
                # Inline record definition
                type_def["items"] = self._enrich_type_def(
                    items, existing_mapping, next_field_id, preserve_existing_ids
                )

    def _enrich_map_type(
        self,
        type_def: Dict[str, Any],
        existing_mapping: Dict[str, int],
        next_field_id: List[int],
        preserve_existing_ids: bool,
    ) -> None:
        """Enrich map: assign key-id/value-id and handle nested values."""
        type_def["key-id"] = next_field_id[0]
        next_field_id[0] += 1
        type_def["value-id"] = next_field_id[0]
        next_field_id[0] += 1

        values = type_def.get("values")
        if isinstance(values, dict):
            values_type = values.get("type")
            if isinstance(values_type, str) and values_type in (
                "record",
                "array",
                "map",
            ):
                type_def["values"] = self._enrich_type_def(
                    values, existing_mapping, next_field_id, preserve_existing_ids
                )
            elif "fields" in values:
                type_def["values"] = self._enrich_type_def(
                    values, existing_mapping, next_field_id, preserve_existing_ids
                )
