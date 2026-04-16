"""
Unit tests for avro_schema_helpers module.
"""

import pytest
from unittest.mock import MagicMock

from src.destinations.iceberg.helpers import AvroSchemaFieldIdAssigner


@pytest.mark.unit
class TestAvroSchemaFieldIdAssigner:
    """Tests for AvroSchemaFieldIdAssigner."""

    def test_assign_field_ids_simple_schema(self):
        """Test assigning field IDs to a simple schema."""
        schema = {
            "type": "record",
            "name": "test",
            "fields": [
                {"name": "id", "type": "int"},
                {"name": "name", "type": "string"},
                {"name": "value", "type": "double"},
            ],
        }

        assigner = AvroSchemaFieldIdAssigner()
        result = assigner.assign_field_ids(schema)

        assert result["fields"][0]["field-id"] == 1
        assert result["fields"][1]["field-id"] == 2
        assert result["fields"][2]["field-id"] == 3

    def test_assign_field_ids_with_custom_start_id(self):
        """Test assigning field IDs with custom start ID."""
        schema = {
            "type": "record",
            "name": "test",
            "fields": [
                {"name": "id", "type": "int"},
                {"name": "name", "type": "string"},
            ],
        }

        assigner = AvroSchemaFieldIdAssigner()
        result = assigner.assign_field_ids(schema, start_id=100)

        assert result["fields"][0]["field-id"] == 100
        assert result["fields"][1]["field-id"] == 101

    def test_preserve_existing_field_ids(self):
        """Test that existing field IDs are preserved when table exists."""
        schema = {
            "type": "record",
            "name": "test",
            "fields": [
                {"name": "id", "type": "int"},
                {"name": "name", "type": "string"},
                {"name": "new_field", "type": "double"},
            ],
        }

        mock_table = MagicMock()
        mock_field1 = MagicMock()
        mock_field1.name = "id"
        mock_field1.field_id = 42
        mock_field2 = MagicMock()
        mock_field2.name = "name"
        mock_field2.field_id = 43
        mock_table.schema.return_value.fields = [mock_field1, mock_field2]

        mock_catalog = MagicMock()
        mock_catalog.load_table.return_value = mock_table

        assigner = AvroSchemaFieldIdAssigner(catalog=mock_catalog)
        result = assigner.assign_field_ids(schema, table_identifier="test.table")

        assert result["fields"][0]["field-id"] == 42
        assert result["fields"][1]["field-id"] == 43
        assert result["fields"][2]["field-id"] == 1

    def test_nested_record_fields(self):
        """Test assigning field IDs to nested record types."""
        schema = {
            "type": "record",
            "name": "outer",
            "fields": [
                {"name": "id", "type": "int"},
                {
                    "name": "nested",
                    "type": {
                        "type": "record",
                        "name": "inner",
                        "fields": [
                            {"name": "field1", "type": "string"},
                            {"name": "field2", "type": "int"},
                        ],
                    },
                },
            ],
        }

        assigner = AvroSchemaFieldIdAssigner()
        result = assigner.assign_field_ids(schema)

        assert result["fields"][0]["field-id"] == 1
        assert result["fields"][1]["field-id"] == 2
        assert result["fields"][1]["type"]["fields"][0]["field-id"] == 3
        assert result["fields"][1]["type"]["fields"][1]["field-id"] == 4

    def test_array_with_record_items(self):
        """Test assigning field IDs to arrays with record items."""
        schema = {
            "type": "record",
            "name": "test",
            "fields": [
                {"name": "id", "type": "int"},
                {
                    "name": "items",
                    "type": {
                        "type": "array",
                        "items": {
                            "type": "record",
                            "name": "item",
                            "fields": [
                                {"name": "item_id", "type": "int"},
                                {"name": "item_name", "type": "string"},
                            ],
                        },
                    },
                },
            ],
        }

        assigner = AvroSchemaFieldIdAssigner()
        result = assigner.assign_field_ids(schema)

        assert result["fields"][0]["field-id"] == 1
        assert result["fields"][1]["field-id"] == 2
        assert result["fields"][1]["type"]["items"]["fields"][0]["field-id"] == 3
        assert result["fields"][1]["type"]["items"]["fields"][1]["field-id"] == 4

    def test_union_types(self):
        """Test that union types are handled correctly."""
        schema = {
            "type": "record",
            "name": "test",
            "fields": [
                {"name": "id", "type": "int"},
                {"name": "optional_field", "type": ["null", "string"], "default": None},
            ],
        }

        assigner = AvroSchemaFieldIdAssigner()
        result = assigner.assign_field_ids(schema)

        assert result["fields"][0]["field-id"] == 1
        assert result["fields"][1]["field-id"] == 2

    def test_schema_without_fields(self):
        """Test that schema without fields is returned unchanged."""
        schema = {
            "type": "record",
            "name": "empty",
        }

        assigner = AvroSchemaFieldIdAssigner()
        result = assigner.assign_field_ids(schema)

        assert "fields" not in result
        assert "field-id" not in result

    def test_map_type_with_record_values(self):
        """Test assigning field IDs to map with record values."""
        schema = {
            "type": "record",
            "name": "test",
            "fields": [
                {"name": "id", "type": "int"},
                {
                    "name": "properties",
                    "type": {
                        "type": "map",
                        "values": {
                            "type": "record",
                            "name": "prop",
                            "fields": [
                                {"name": "key", "type": "string"},
                                {"name": "val", "type": "string"},
                            ],
                        },
                    },
                },
            ],
        }

        assigner = AvroSchemaFieldIdAssigner()
        result = assigner.assign_field_ids(schema)

        assert result["fields"][0]["field-id"] == 1
        assert result["fields"][1]["field-id"] == 2
        assert result["fields"][1]["type"]["values"]["fields"][0]["field-id"] == 3
        assert result["fields"][1]["type"]["values"]["fields"][1]["field-id"] == 4
