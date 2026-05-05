"""
Unit tests for DataFrameFlattener array handling functionality.
"""

import pytest
import pandas as pd
import pyarrow as pa
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


@pytest.mark.unit
class TestPyArrowSupport:
    """Tests for PyArrow Table support."""

    def test_flatten_struct_column(self):
        """Test that struct columns are flattened correctly."""
        flattener = DataFrameFlattener()
        table = pa.table(
            {
                "id": [1, 2],
                "user": pa.array(
                    [
                        {"name": "Alice", "age": 30},
                        {"name": "Bob", "age": 25},
                    ]
                ),
            }
        )

        flat_table = flattener.flatten(table)

        assert "id" in flat_table.column_names
        assert "user.name" in flat_table.column_names
        assert "user.age" in flat_table.column_names
        assert flat_table["user.name"].to_pylist() == ["Alice", "Bob"]
        assert flat_table["user.age"].to_pylist() == [30, 25]

    def test_flatten_nested_struct(self):
        """Test that nested struct columns are flattened correctly."""
        flattener = DataFrameFlattener()
        table = pa.table(
            {
                "id": [1, 2],
                "profile": pa.array(
                    [
                        {
                            "name": "Alice",
                            "address": {"city": "NYC", "zip": "10001"},
                        },
                        {
                            "name": "Bob",
                            "address": {"city": "LA", "zip": "90001"},
                        },
                    ]
                ),
            }
        )

        flat_table = flattener.flatten(table)

        assert "id" in flat_table.column_names
        assert "profile.name" in flat_table.column_names
        assert "profile.address.city" in flat_table.column_names
        assert "profile.address.zip" in flat_table.column_names
        assert flat_table["profile.name"].to_pylist() == ["Alice", "Bob"]
        assert flat_table["profile.address.city"].to_pylist() == ["NYC", "LA"]

    def test_unflatten_struct_column(self):
        """Test that struct columns are unflattened correctly."""
        flattener = DataFrameFlattener()
        table = pa.table(
            {
                "id": [1, 2],
                "user": pa.array(
                    [
                        {"name": "Alice", "age": 30},
                        {"name": "Bob", "age": 25},
                    ]
                ),
            }
        )

        flat_table = flattener.flatten(table)
        unflat_table = flattener.unflatten(flat_table)

        assert "user" in unflat_table.column_names
        user_values = unflat_table["user"].to_pylist()
        assert user_values[0] == {"name": "Alice", "age": 30}
        assert user_values[1] == {"name": "Bob", "age": 25}

    def test_unflatten_nested_struct(self):
        """Test that nested struct columns are unflattened correctly."""
        flattener = DataFrameFlattener()
        table = pa.table(
            {
                "id": [1, 2],
                "profile": pa.array(
                    [
                        {
                            "name": "Alice",
                            "address": {"city": "NYC", "zip": "10001"},
                        },
                        {
                            "name": "Bob",
                            "address": {"city": "LA", "zip": "90001"},
                        },
                    ]
                ),
            }
        )

        flat_table = flattener.flatten(table)
        unflat_table = flattener.unflatten(flat_table)

        assert "profile" in unflat_table.column_names
        profile_values = unflat_table["profile"].to_pylist()
        assert profile_values[0]["name"] == "Alice"
        assert profile_values[0]["address"]["city"] == "NYC"
        assert profile_values[1]["name"] == "Bob"
        assert profile_values[1]["address"]["zip"] == "90001"

    def test_roundtrip_struct_with_nulls(self):
        """Test struct with null values roundtrip."""
        flattener = DataFrameFlattener()
        table = pa.table(
            {
                "id": [1, 2],
                "user": pa.array([{"name": "Alice", "age": 30}, None]),
            }
        )

        flat_table = flattener.flatten(table)
        unflat_table = flattener.unflatten(flat_table)

        user_values = unflat_table["user"].to_pylist()
        assert user_values[0] == {"name": "Alice", "age": 30}

    def test_flatten_list_of_structs(self):
        """Test that array of structs is flattened correctly."""
        flattener = DataFrameFlattener()
        table = pa.table(
            {
                "id": [1],
                "items": pa.array(
                    [[{"product": "A", "qty": 1}, {"product": "B", "qty": 2}]]
                )
            }
        )

        flat_table = flattener.flatten(table)

        assert "id" in flat_table.column_names
        assert "items[0]" in flat_table.column_names
        assert "items[1]" in flat_table.column_names
        items_0_struct = flat_table["items[0]"].to_pylist()
        assert items_0_struct[0]["product"] == "A"
        assert items_0_struct[0]["qty"] == 1

    def test_unflatten_list_of_structs(self):
        """Test that array of structs is unflattened correctly."""
        flattener = DataFrameFlattener()
        table = pa.table(
            {
                "id": [1],
                "items": pa.array(
                    [[{"product": "A", "qty": 1}, {"product": "B", "qty": 2}]]
                )
            }
        )

        flat_table = flattener.flatten(table)
        unflat_table = flattener.unflatten(flat_table)

        items_values = unflat_table["items"].to_pylist()
        assert items_values[0][0] == {"product": "A", "qty": 1}
        assert items_values[0][1] == {"product": "B", "qty": 2}

    def test_scalar_column_roundtrip(self):
        """Test that scalar columns work with PyArrow."""
        flattener = DataFrameFlattener()
        table = pa.table(
            {
                "id": [1, 2, 3],
                "name": ["Alice", "Bob", "Charlie"],
                "value": [10.5, 20.5, 30.5],
            }
        )

        flat_table = flattener.flatten(table)
        unflat_table = flattener.unflatten(flat_table)

        assert unflat_table["id"].to_pylist() == [1, 2, 3]
        assert unflat_table["name"].to_pylist() == ["Alice", "Bob", "Charlie"]
        assert unflat_table["value"].to_pylist() == [10.5, 20.5, 30.5]

    def test_schema_from_pyarrow_table(self):
        """Test that schema is correctly built from PyArrow table."""
        flattener = DataFrameFlattener()
        table = pa.table(
            {
                "id": [1, 2],
                "user": pa.array(
                    [
                        {"name": "Alice", "scores": [90, 85]},
                        {"name": "Bob", "scores": [75]},
                    ]
                ),
            }
        )

        flattener.flatten(table)

        assert "id" in flattener.schema
        assert "user" in flattener.schema
        assert flattener.schema["id"].root_node.node_type == NodeType.SCALAR
        assert flattener.schema["user"].root_node.node_type == NodeType.DICT
        assert "name" in flattener.schema["user"].root_node.children
        assert "scores" in flattener.schema["user"].root_node.children
        assert flattener.schema["user"].root_node.children["scores"].node_type == NodeType.ARRAY

    def test_schema_serialization_with_pyarrow(self):
        """Test schema serialization works after PyArrow flatten."""
        flattener = DataFrameFlattener()
        table = pa.table(
            {
                "id": [1, 2],
                "user": pa.array(
                    [
                        {"name": "Alice", "age": 30},
                        {"name": "Bob", "age": 25},
                    ]
                ),
            }
        )

        flattener.flatten(table)
        schema_dict = flattener.schema_to_dict()

        assert "columns" in schema_dict
        assert "user" in schema_dict["columns"]
        assert schema_dict["columns"]["user"]["root_node"]["node_type"] == "dict"
        assert "name" in schema_dict["columns"]["user"]["root_node"]["children"]
        assert "age" in schema_dict["columns"]["user"]["root_node"]["children"]

    def test_load_schema_and_unflatten(self):
        """Test loading schema and unflattening with new data."""
        flattener1 = DataFrameFlattener()
        table1 = pa.table(
            {
                "id": [1, 2],
                "user": pa.array(
                    [
                        {"name": "Alice", "age": 30},
                        {"name": "Bob", "age": 25},
                    ]
                ),
            }
        )
        flattener1.flatten(table1)
        schema_dict = flattener1.schema_to_dict()

        flat_data = {
            "id": [3, 4],
            "user.name": ["Charlie", "David"],
            "user.age": [35, 40],
        }
        flat_table = pa.table(flat_data)

        flattener2 = DataFrameFlattener()
        flattener2.load_schema_from_dict(schema_dict)
        unflat_table = flattener2.unflatten(flat_table)

        user_values = unflat_table["user"].to_pylist()
        assert user_values[0] == {"name": "Charlie", "age": 35}
        assert user_values[1] == {"name": "David", "age": 40}

    def test_timestamp_column_handling(self):
        """Test that timestamp columns are handled correctly in flatten/unflatten."""
        flattener = DataFrameFlattener()
        table = pa.table(
            {
                "id": [1, 2],
                "event_time": pa.array(
                    [
                        {"seconds": 1234567890, "nanos": 0},
                        {"seconds": 987654321, "nanos": 123456789},
                    ],
                    type=pa.struct([("seconds", pa.int64()), ("nanos", pa.int64())]),
                ),
            }
        )

        flat_table = flattener.flatten(table)
        unflat_table = flattener.unflatten(flat_table)

        assert "event_time.seconds" in flat_table.column_names
        assert "event_time.nanos" in flat_table.column_names

    def test_out_of_range_timestamps_in_struct(self):
        """Test that out-of-range timestamps in nested structs are handled."""
        import datetime
        flattener = DataFrameFlattener()
        
        old_timestamp = datetime.datetime(1800, 1, 1, 0, 0, 0)
        future_timestamp = datetime.datetime(2500, 12, 31, 23, 59, 59)
        
        table = pa.table(
            {
                "id": [1, 2],
                "event": pa.array(
                    [
                        {"ts": old_timestamp, "name": "old_event"},
                        {"ts": future_timestamp, "name": "future_event"},
                    ]
                ),
            }
        )

        flat_table = flattener.flatten(table)
        
        assert "id" in flat_table.column_names
        assert "event.ts" in flat_table.column_names
        assert "event.name" in flat_table.column_names

    def test_list_of_timestamps(self):
        """Test that arrays of timestamps are handled correctly."""
        import datetime
        flattener = DataFrameFlattener()
        
        ts1 = datetime.datetime(2020, 1, 1, 12, 0, 0)
        ts2 = datetime.datetime(2021, 6, 15, 18, 30, 0)
        ts3 = datetime.datetime(2022, 12, 25, 9, 0, 0)
        
        table = pa.table(
            {
                "id": [1, 2],
                "timestamps": pa.array(
                    [[ts1, ts2, ts3], [ts2, ts3]]
                )
            }
        )

        flat_table = flattener.flatten(table)
        
        assert "id" in flat_table.column_names
        assert "timestamps[0]" in flat_table.column_names
        assert "timestamps[1]" in flat_table.column_names
        assert "timestamps[2]" in flat_table.column_names


