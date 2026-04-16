"""
Unit tests for DataFrameFlattener array handling functionality.
"""

import pytest
import pandas as pd
import numpy as np

from src.core.flatten import DataFrameFlattener, SchemaNode, NodeType


@pytest.mark.unit
class TestDataFrameFlattenerArrays:
    """Tests for DataFrameFlattener array handling."""

    def test_flatten_array_into_indexed_columns(self):
        """Test that arrays are flattened into indexed columns."""
        flattener = DataFrameFlattener()
        df = pd.DataFrame({"id": [1, 2, 3], "values": [[1, 2, 3], [4, 5], [6]]})

        flat_df = flattener.flatten(df)

        assert "values[0]" in flat_df.columns
        assert "values[1]" in flat_df.columns
        assert "values[2]" in flat_df.columns
        assert flat_df["values[0]"].tolist() == [1, 4, 6]
        assert flat_df["values[1]"].iloc[0] == 2
        assert flat_df["values[1]"].iloc[1] == 5
        assert pd.isna(flat_df["values[1]"].iloc[2])
        assert flat_df["values[2]"].iloc[0] == 3
        assert pd.isna(flat_df["values[2]"].iloc[1])
        assert pd.isna(flat_df["values[2]"].iloc[2])

    def test_schema_stores_max_elements(self):
        """Test that schema stores max_elements for arrays."""
        flattener = DataFrameFlattener()
        df = pd.DataFrame({"id": [1, 2, 3], "values": [[1, 2, 3], [4, 5], [6]]})

        flattener.flatten(df)

        schema = flattener.schema["values"].root_node
        assert schema.node_type == NodeType.ARRAY
        assert schema.max_elements == 3

    def test_schema_detects_nullable_elements(self):
        """Test that schema detects nullable elements."""
        flattener = DataFrameFlattener()
        df = pd.DataFrame({"id": [1, 2], "values": [[1, 2, None], [4, 5, 6]]})

        flattener.flatten(df)

        schema = flattener.schema["values"].root_node
        assert schema.nullable_elements is True

    def test_schema_detects_non_nullable_elements(self):
        """Test that schema detects non-nullable elements."""
        flattener = DataFrameFlattener()
        df = pd.DataFrame({"id": [1, 2, 3], "values": [[1, 2, 3], [4, 5], [6]]})

        flattener.flatten(df)

        schema = flattener.schema["values"].root_node
        assert schema.nullable_elements is False

    def test_schema_detects_nullable_array(self):
        """Test that schema detects nullable arrays."""
        flattener = DataFrameFlattener()
        df = pd.DataFrame({"id": [1, 2, 3], "values": [[1, 2, 3], [], None]})

        flattener.flatten(df)

        schema = flattener.schema["values"].root_node
        assert schema.nullable_array is True
        assert "values._is_null" in flattener.flatten(df).columns

    def test_schema_detects_non_nullable_array(self):
        """Test that schema detects non-nullable arrays."""
        flattener = DataFrameFlattener()
        df = pd.DataFrame({"id": [1, 2, 3], "values": [[1, 2, 3], [4, 5], [6]]})

        flattener.flatten(df)

        schema = flattener.schema["values"].root_node
        assert schema.nullable_array is False

    def test_unflatten_filters_null_elements_for_non_nullable(self):
        """Test that unflatten filters null elements when nullable_elements=False."""
        flattener = DataFrameFlattener()
        df = pd.DataFrame({"id": [1, 2], "values": [[1, 2, 3], [4, 5, 6]]})

        flat_df = flattener.flatten(df)
        flat_df.loc[1, "values[1]"] = None

        unflat_df = flattener.unflatten(flat_df)

        assert unflat_df.loc[0, "values"] == [1, 2, 3]
        assert unflat_df.loc[1, "values"] == [4, 6]

    def test_unflatten_nullable_array_returns_none(self):
        """Test that unflatten returns None for nullable arrays marked as null."""
        flattener = DataFrameFlattener()
        df = pd.DataFrame({"id": [1, 2, 3], "values": [[1, 2, 3], [], None]})

        flat_df = flattener.flatten(df)
        unflat_df = flattener.unflatten(flat_df)

        assert unflat_df.loc[0, "values"] == [1, 2, 3]
        assert unflat_df.loc[1, "values"] == []
        assert unflat_df.loc[2, "values"] is None

    def test_unflatten_empty_array(self):
        """Test that unflatten returns empty list for empty arrays."""
        flattener = DataFrameFlattener()
        df = pd.DataFrame({"id": [1, 2], "values": [[1, 2, 3], []]})

        flat_df = flattener.flatten(df)
        unflat_df = flattener.unflatten(flat_df)

        assert unflat_df.loc[0, "values"] == [1, 2, 3]
        assert unflat_df.loc[1, "values"] == []

    def test_nested_array_flatten_unflatten(self):
        """Test flatten/unflatten for arrays of arrays."""
        flattener = DataFrameFlattener()
        df = pd.DataFrame({"id": [1, 2], "matrix": [[[1, 2], [3, 4]], [[5, 6, 7]]]})

        flat_df = flattener.flatten(df)
        unflat_df = flattener.unflatten(flat_df)

        assert unflat_df.loc[0, "matrix"] == [[1, 2], [3, 4]]
        assert unflat_df.loc[1, "matrix"] == [[5, 6, 7]]

    def test_dict_with_array_flatten_unflatten(self):
        """Test flatten/unflatten for dict containing arrays."""
        flattener = DataFrameFlattener()
        df = pd.DataFrame(
            {
                "user_id": [1, 2],
                "profile": [
                    {"name": "Alice", "scores": [95, 87, 92]},
                    {"name": "Bob", "scores": [78, 85]},
                ],
            }
        )

        flat_df = flattener.flatten(df)
        unflat_df = flattener.unflatten(flat_df)

        assert unflat_df.loc[0, "profile"] == {"name": "Alice", "scores": [95, 87, 92]}
        assert unflat_df.loc[1, "profile"] == {"name": "Bob", "scores": [78, 85]}

    def test_array_with_dict_elements(self):
        """Test flatten/unflatten for array of dicts."""
        flattener = DataFrameFlattener()
        df = pd.DataFrame(
            {
                "order_id": [1001],
                "items": [
                    [
                        {"product_id": "P-123", "quantity": 2, "price": 29.99},
                        {"product_id": "P-456", "quantity": 1, "price": 99.99},
                    ]
                ],
            }
        )

        flat_df = flattener.flatten(df)
        unflat_df = flattener.unflatten(flat_df)

        assert len(unflat_df.loc[0, "items"]) == 2
        assert unflat_df.loc[0, "items"][0]["product_id"] == "P-123"
        assert unflat_df.loc[0, "items"][1]["price"] == 99.99

    def test_deeply_nested_structure(self):
        """Test flatten/unflatten for deeply nested structures."""
        flattener = DataFrameFlattener()
        df = pd.DataFrame(
            {
                "user_id": [1, 2],
                "profile": [
                    {
                        "name": "Alice",
                        "metadata": {"tags": ["admin", "active"], "scores": [95, 87]},
                    },
                    {"name": "Bob", "metadata": {"tags": ["user"], "scores": [78]}},
                ],
            }
        )

        flat_df = flattener.flatten(df)
        unflat_df = flattener.unflatten(flat_df)

        assert unflat_df.loc[0, "profile"] == {
            "name": "Alice",
            "metadata": {"tags": ["admin", "active"], "scores": [95, 87]},
        }
        assert unflat_df.loc[1, "profile"] == {
            "name": "Bob",
            "metadata": {"tags": ["user"], "scores": [78]},
        }


@pytest.mark.unit
class TestSchemaSerialization:
    """Tests for schema serialization/deserialization."""

    def test_schema_to_dict(self):
        """Test schema serialization to dict."""
        flattener = DataFrameFlattener()
        df = pd.DataFrame({"id": [1, 2], "values": [[1, 2], [3, 4, 5]]})

        flattener.flatten(df)
        schema_dict = flattener.schema_to_dict()

        assert "columns" in schema_dict
        assert "original_columns" in schema_dict
        assert "id" in schema_dict["columns"]
        assert "values" in schema_dict["columns"]

    def test_schema_to_dict_preserves_nullable_flags(self):
        """Test that serialized schema preserves nullable flags."""
        flattener = DataFrameFlattener()
        df = pd.DataFrame(
            {
                "id": [1, 2, 3],
                "nullable_array": [[1, 2], None, [3]],
                "non_nullable_array": [[1, 2, 3], [4, 5], [6]],
                "nullable_elements": [[1, None, 3], [4, 5], [6]],
            }
        )

        flattener.flatten(df)
        schema_dict = flattener.schema_to_dict()

        nullable_schema = schema_dict["columns"]["nullable_array"]["root_node"]
        assert nullable_schema["nullable_array"] is True

        non_nullable_schema = schema_dict["columns"]["non_nullable_array"]["root_node"]
        assert non_nullable_schema["nullable_array"] is False

        nullable_elements_schema = schema_dict["columns"]["nullable_elements"][
            "root_node"
        ]
        assert nullable_elements_schema["nullable_elements"] is True

    def test_load_schema_from_dict(self):
        """Test schema deserialization from dict."""
        flattener1 = DataFrameFlattener()
        df = pd.DataFrame({"id": [1, 2], "values": [[1, 2], [3, 4, 5]]})

        flattener1.flatten(df)
        schema_dict = flattener1.schema_to_dict()

        flattener2 = DataFrameFlattener()
        flattener2.load_schema_from_dict(schema_dict)

        assert "values" in flattener2.schema
        assert flattener2.schema["values"].root_node.node_type == NodeType.ARRAY
        assert flattener2.schema["values"].root_node.max_elements == 3


@pytest.mark.unit
class TestSDVCompatibility:
    """Tests for SDV compatibility scenarios."""

    def test_sdv_generates_extra_nulls_filtered(self):
        """Test that SDV-generated nulls in non-nullable elements are filtered."""
        flattener = DataFrameFlattener()
        df = pd.DataFrame({"id": [1, 2], "scores": [[10, 20, 30], [40, 50, 60]]})

        flat_df = flattener.flatten(df)

        schema = flattener.schema["scores"].root_node
        assert schema.nullable_elements is False

        flat_df.loc[0, "scores[1]"] = None
        flat_df.loc[1, "scores[2]"] = None

        unflat_df = flattener.unflatten(flat_df)

        assert 20 not in unflat_df.loc[0, "scores"]
        assert 60 not in unflat_df.loc[1, "scores"]

    def test_sdv_generates_different_length_arrays(self):
        """Test that arrays with different lengths (generated by SDV) work correctly."""
        flattener = DataFrameFlattener()
        df = pd.DataFrame({"id": [1, 2, 3], "values": [[1, 2, 3], [4, 5], [6]]})

        flat_df = flattener.flatten(df)
        assert flat_df["values[0]"].tolist() == [1, 4, 6]
        assert flat_df["values[1]"].iloc[0] == 2
        assert flat_df["values[1]"].iloc[1] == 5
        assert pd.isna(flat_df["values[1]"].iloc[2])
        assert flat_df["values[2]"].iloc[0] == 3
        assert pd.isna(flat_df["values[2]"].iloc[1])
        assert pd.isna(flat_df["values[2]"].iloc[2])

    def test_strictly_typed_element_columns(self):
        """Test that element columns are strictly typed."""
        flattener = DataFrameFlattener()
        df = pd.DataFrame({"id": [1, 2], "counts": [[1, 2, 3], [4, 5, 6]]})

        flat_df = flattener.flatten(df)

        schema = flattener.schema["counts"].root_node
        assert schema.element_schema.dtype == "int64"

        assert flat_df["counts[0]"].dtype in [np.int64, np.float64, int]

    def test_mixed_types_in_array_infers_object(self):
        """Test that mixed types in array are inferred as object dtype when strings are present."""
        flattener = DataFrameFlattener()
        df = pd.DataFrame({"id": [1, 2], "mixed": [["a", "b", "c"], ["x", "y", "z"]]})

        flattener.flatten(df)

        schema = flattener.schema["mixed"].root_node
        assert schema.element_schema.dtype == "object"
        assert schema.nullable_elements is False


@pytest.mark.unit
class TestSchemaNode:
    """Tests for SchemaNode dataclass."""

    def test_schema_node_to_dict(self):
        """Test SchemaNode serialization."""
        node = SchemaNode(
            node_type=NodeType.ARRAY,
            element_schema=SchemaNode(node_type=NodeType.SCALAR, dtype="int64"),
            nullable_elements=True,
            nullable_array=True,
            max_elements=5,
        )

        result = node.to_dict()

        assert result["node_type"] == "array"
        assert result["nullable_elements"] is True
        assert result["nullable_array"] is True
        assert result["max_elements"] == 5
        assert result["element_schema"]["dtype"] == "int64"

    def test_schema_node_from_dict(self):
        """Test SchemaNode deserialization."""
        data = {
            "node_type": "array",
            "element_schema": {"node_type": "scalar", "dtype": "float64"},
            "nullable_elements": True,
            "nullable_array": False,
            "max_elements": 10,
        }

        node = SchemaNode.from_dict(data)

        assert node.node_type == NodeType.ARRAY
        assert node.element_schema.dtype == "float64"
        assert node.nullable_elements is True
        assert node.nullable_array is False
        assert node.max_elements == 10

    def test_nested_schema_node_serialization(self):
        """Test serialization of deeply nested schema."""
        node = SchemaNode(
            node_type=NodeType.DICT,
            children={
                "scores": SchemaNode(
                    node_type=NodeType.ARRAY,
                    element_schema=SchemaNode(node_type=NodeType.SCALAR, dtype="int64"),
                    max_elements=3,
                ),
                "name": SchemaNode(node_type=NodeType.SCALAR, dtype="object"),
            },
        )

        serialized = node.to_dict()
        restored = SchemaNode.from_dict(serialized)

        assert restored.children["scores"].node_type == NodeType.ARRAY
        assert restored.children["scores"].max_elements == 3
        assert restored.children["name"].dtype == "object"
