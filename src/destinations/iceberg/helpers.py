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
    preserving existing IDs when a table already exists.
    """

    def __init__(self, catalog: Optional[Catalog] = None):
        """
        Initialize the assigner.

        Args:
            catalog: Optional Iceberg catalog. If provided, can look up existing
                    table schemas to preserve field ID mappings.
        """
        self.catalog = catalog

    def assign_field_ids(
        self,
        avro_schema: Dict[str, Any],
        table_identifier: Optional[str] = None,
        start_id: int = 1,
    ) -> Dict[str, Any]:
        """
        Assign field IDs to an Avro schema.

        If a table identifier is provided and the table exists, uses the existing
        field IDs from the table schema. Otherwise, assigns sequential IDs.

        Args:
            avro_schema: Avro schema dict without field IDs
            table_identifier: Optional table identifier to look up existing IDs
            start_id: Starting ID for new assignments (default: 1)

        Returns:
            Avro schema dict with field IDs added
        """
        if "fields" not in avro_schema:
            return avro_schema

        existing_mapping = {}
        if table_identifier and self.catalog:
            existing_mapping = self._get_existing_field_mapping(table_identifier)

        enriched_schema = self._enrich_schema_with_field_ids(
            avro_schema,
            existing_mapping=existing_mapping,
            next_field_id=[start_id],
        )

        if existing_mapping:
            logger.info(
                f"Preserved {len(existing_mapping)} existing field IDs from table {table_identifier}"
            )
        else:
            logger.info(f"Assigned sequential field IDs starting from {start_id}")

        return enriched_schema

    def _get_existing_field_mapping(self, table_identifier: str) -> Dict[str, int]:
        """
        Get field name to ID mapping from an existing table.

        Args:
            table_identifier: Table identifier (e.g., "namespace.table_name")

        Returns:
            Dict mapping field names to their IDs
        """
        try:
            if not self.catalog:
                return {}

            table = self.catalog.load_table(table_identifier)
            schema = table.schema()

            mapping = {}
            for field in schema.fields:
                mapping[field.name] = field.field_id

            logger.debug(
                f"Loaded {len(mapping)} field mappings from existing table {table_identifier}"
            )
            return mapping

        except NoSuchTableError:
            logger.debug(
                f"Table {table_identifier} does not exist, will assign new IDs"
            )
            return {}
        except Exception as e:
            logger.warning(
                f"Failed to load existing field mapping from {table_identifier}: {e}"
            )
            raise e

    def _enrich_schema_with_field_ids(
        self,
        avro_schema: Dict[str, Any],
        existing_mapping: Dict[str, int],
        next_field_id: List[int],
    ) -> Dict[str, Any]:
        """
        Recursively add field IDs to schema fields.

        Args:
            avro_schema: Avro schema dict
            existing_mapping: Existing field name to ID mapping
            next_field_id: Mutable list with current next ID (for sequential assignment)

        Returns:
            Enriched Avro schema with field IDs
        """
        result = avro_schema.copy()

        if "fields" in avro_schema:
            enriched_fields = []
            for field in avro_schema["fields"]:
                enriched_field = self._enrich_field(
                    field=field,
                    existing_mapping=existing_mapping,
                    next_field_id=next_field_id,
                )
                enriched_fields.append(enriched_field)
            result["fields"] = enriched_fields

        return result

    def _enrich_field(
        self,
        field: Dict[str, Any],
        existing_mapping: Dict[str, int],
        next_field_id: List[int],
    ) -> Dict[str, Any]:
        """
        Enrich a single field with field ID.

        Args:
            field: Field definition dict
            existing_mapping: Existing field name to ID mapping
            next_field_id: Mutable list with current next ID

        Returns:
            Enriched field with field_id added
        """
        field_name = field.get("name", "")

        enriched = field.copy()

        if field_name in existing_mapping:
            enriched["field-id"] = existing_mapping[field_name]
        else:
            enriched["field-id"] = next_field_id[0]
            next_field_id[0] += 1

        self._enrich_field_type(enriched, existing_mapping, next_field_id)

        return enriched

    def _enrich_field_type(
        self,
        field: Dict[str, Any],
        existing_mapping: Dict[str, int],
        next_field_id: List[int],
    ) -> None:
        """
        Recursively enrich the field's type and nested types.

        Args:
            field: Field dict (will be modified in place)
            existing_mapping: Existing field name to ID mapping
            next_field_id: Mutable list with current next ID
        """
        field_type = field.get("type")

        if isinstance(field_type, list):
            for i, union_member in enumerate(field_type):
                if isinstance(union_member, dict):
                    field["type"][i] = self._enrich_type_def(
                        union_member, existing_mapping, next_field_id
                    )
        elif isinstance(field_type, dict):
            field["type"] = self._enrich_type_def(
                field_type, existing_mapping, next_field_id
            )

    def _enrich_type_def(
        self,
        type_def: Dict[str, Any],
        existing_mapping: Dict[str, int],
        next_field_id: List[int],
    ) -> Dict[str, Any]:
        """
        Enrich a type definition dict.

        Args:
            type_def: Type definition dict (will be modified in place)
            existing_mapping: Existing field name to ID mapping
            next_field_id: Mutable list with current next ID

        Returns:
            Enriched type definition (may be the same object or a new one)
        """
        if "fields" in type_def:
            return self._enrich_schema_with_field_ids(
                type_def,
                existing_mapping=existing_mapping,
                next_field_id=next_field_id,
            )
        elif type_def.get("type") == "array":
            self._enrich_array_type(type_def, existing_mapping, next_field_id)
            return type_def
        elif type_def.get("type") == "map":
            self._enrich_map_type(type_def, existing_mapping, next_field_id)
            return type_def
        elif type_def.get("type") == "record":
            return self._enrich_field(
                type_def,
                existing_mapping=existing_mapping,
                next_field_id=next_field_id,
            )
        return type_def

    def _enrich_array_type(
        self,
        type_def: Dict[str, Any],
        existing_mapping: Dict[str, int],
        next_field_id: List[int],
    ) -> None:
        """
        Enrich an array type definition.

        Args:
            type_def: Type definition dict with 'type': 'array'
            existing_mapping: Existing field name to ID mapping
            next_field_id: Mutable list with current next ID
        """
        type_def["element-id"] = next_field_id[0]

        items = type_def.get("items")
        if isinstance(items, dict):
            if "fields" in items:
                type_def["items"] = self._enrich_schema_with_field_ids(
                    items,
                    existing_mapping=existing_mapping,
                    next_field_id=next_field_id,
                )
            elif items.get("type") == "array":
                self._enrich_array_type(items, existing_mapping, next_field_id)
            elif items.get("type") == "map":
                self._enrich_map_type(items, existing_mapping, next_field_id)
            elif items.get("type") == "record":
                type_def["items"] = self._enrich_field(
                    items,
                    existing_mapping=existing_mapping,
                    next_field_id=next_field_id,
                )

    def _enrich_map_type(
        self,
        type_def: Dict[str, Any],
        existing_mapping: Dict[str, int],
        next_field_id: List[int],
    ) -> None:
        """
        Enrich a map type definition.

        Args:
            type_def: Type definition dict with 'type': 'map'
            existing_mapping: Existing field name to ID mapping
            next_field_id: Mutable list with current next ID
        """
        values = type_def.get("values")
        if isinstance(values, dict):
            if "fields" in values:
                type_def["values"] = self._enrich_schema_with_field_ids(
                    values,
                    existing_mapping=existing_mapping,
                    next_field_id=next_field_id,
                )
            elif values.get("type") == "array":
                self._enrich_array_type(values, existing_mapping, next_field_id)
            elif values.get("type") == "map":
                self._enrich_map_type(values, existing_mapping, next_field_id)
            elif values.get("type") == "record":
                type_def["values"] = self._enrich_field(
                    values,
                    existing_mapping=existing_mapping,
                    next_field_id=next_field_id,
                )
