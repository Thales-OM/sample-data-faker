import pandas as pd
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union, overload


class NodeType(Enum):
    SCALAR = "scalar"
    DICT = "dict"
    ARRAY = "array"


@dataclass
class SchemaNode:
    node_type: NodeType
    dtype: Optional[str] = None
    children: Dict[str, "SchemaNode"] = field(default_factory=dict)
    element_schema: Optional["SchemaNode"] = None
    nullable_elements: bool = False
    nullable_array: bool = False
    max_elements: int = 0
    has_null_elements: bool = False

    def to_dict(self) -> Dict[str, Any]:
        result = {"node_type": self.node_type.value}
        if self.dtype is not None:
            result["dtype"] = self.dtype
        if self.children:
            result["children"] = {k: v.to_dict() for k, v in self.children.items()}
        if self.element_schema is not None:
            result["element_schema"] = self.element_schema.to_dict()
        if self.nullable_elements:
            result["nullable_elements"] = self.nullable_elements
        result["nullable_array"] = self.nullable_array
        if self.max_elements > 0:
            result["max_elements"] = self.max_elements
        if self.has_null_elements:
            result["has_null_elements"] = self.has_null_elements
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SchemaNode":
        node_type = NodeType(data["node_type"])
        children = {}
        if "children" in data:
            children = {k: cls.from_dict(v) for k, v in data["children"].items()}
        element_schema = None
        if "element_schema" in data:
            element_schema = cls.from_dict(data["element_schema"])
        return cls(
            node_type=node_type,
            dtype=data.get("dtype"),
            children=children,
            element_schema=element_schema,
            nullable_elements=data.get("nullable_elements", False),
            nullable_array=data.get("nullable_array", False),
            max_elements=data.get("max_elements", 0),
            has_null_elements=data.get("has_null_elements", False),
        )


@dataclass
class ColumnSchema:
    """Represents the schema for a single column."""

    name: str
    root_node: SchemaNode

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "root_node": self.root_node.to_dict()}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ColumnSchema":
        return cls(name=data["name"], root_node=SchemaNode.from_dict(data["root_node"]))


class DataFrameFlattener:
    def __init__(self):
        self._schema: Dict[str, ColumnSchema] = {}
        self._original_columns: List[str] = []
        self._input_is_pyarrow: bool = False
        self._array_metadata: Dict[str, Dict[str, Any]] = {}

    @property
    def schema(self) -> Dict[str, ColumnSchema]:
        return self._schema

    def schema_to_dict(self) -> Dict[str, Any]:
        return {
            "columns": {name: cs.to_dict() for name, cs in self._schema.items()},
            "original_columns": self._original_columns,
        }

    def load_schema_from_dict(self, data: Dict[str, Any]) -> None:
        self._schema = {
            name: ColumnSchema.from_dict(cs_data)
            for name, cs_data in data["columns"].items()
        }
        self._original_columns = data["original_columns"]

    @overload
    def flatten(self, data: pa.Table) -> pa.Table: ...

    @overload
    def flatten(self, data: pd.DataFrame) -> pd.DataFrame: ...

    def flatten(self, data):
        if isinstance(data, pa.Table):
            return self._flatten_pyarrow(table=data)
        elif isinstance(data, pd.DataFrame):
            return self._flatten_pandas(df=data)
        raise TypeError(f"Expected pa.Table or pd.DataFrame, got {type(data)}")

    @staticmethod
    def _extract_array_metadata(
        flat_table: pa.Table,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Extract metadata about array columns from flat PyArrow table.

        This helps reconstruct arrays during unflatten.

        Args:
            flat_table: Flattened PyArrow Table

        Returns:
            Dictionary mapping array paths to their metadata
        """
        array_metadata = {}

        for col_name in flat_table.column_names:
            if "__" in col_name:
                base, idx_str = col_name.rsplit("__", 1)
                try:
                    idx = int(idx_str)
                    if base not in array_metadata:
                        array_metadata[base] = {
                            "max_index": idx,
                            "columns": [],
                        }
                    array_metadata[base]["max_index"] = max(
                        array_metadata[base]["max_index"],
                        idx,
                    )
                    array_metadata[base]["columns"].append(col_name)
                except ValueError:
                    pass

        for base in array_metadata:
            meta = array_metadata[base]
            meta["num_elements"] = meta["max_index"] + 1
            meta["columns"] = sorted(
                meta["columns"], key=lambda x: int(x.rsplit("__", 1)[1])
            )

        return array_metadata

    @staticmethod
    def _extract_array_metadata_from_dataframe(
        flat_df: pd.DataFrame,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Extract metadata about array columns from flat pandas DataFrame.

        Args:
            flat_df: Flattened pandas DataFrame

        Returns:
            Dictionary mapping array paths to their metadata
        """
        array_metadata = {}

        for col_name in flat_df.columns:
            if "__" in col_name:
                base, idx_str = col_name.rsplit("__", 1)
                try:
                    idx = int(idx_str)
                    if base not in array_metadata:
                        array_metadata[base] = {
                            "max_index": idx,
                            "columns": [],
                        }
                    array_metadata[base]["max_index"] = max(
                        array_metadata[base]["max_index"],
                        idx,
                    )
                    array_metadata[base]["columns"].append(col_name)
                except ValueError:
                    pass

        for base in array_metadata:
            meta = array_metadata[base]
            meta["num_elements"] = meta["max_index"] + 1
            meta["columns"] = sorted(
                meta["columns"], key=lambda x: int(x.rsplit("__", 1)[1])
            )

        return array_metadata

    @overload
    def unflatten(self, flat_data: pa.Table) -> pa.Table: ...

    @overload
    def unflatten(self, flat_data: pd.DataFrame) -> pd.DataFrame: ...

    def unflatten(self, flat_data):
        if isinstance(flat_data, pa.Table):
            return self._unflatten_pyarrow(flat_data)
        if isinstance(flat_data, pd.DataFrame):
            return self._unflatten_pandas(flat_data)
        raise TypeError(f"Expected pa.Table or pd.DataFrame, got {type(flat_data)}")

    def _to_pandas(self, data: Union[pd.DataFrame, pa.Table]) -> pd.DataFrame:
        if isinstance(data, pa.Table):
            return data.to_pandas()
        return data

    def _from_pandas(self, df: pd.DataFrame) -> Union[pd.DataFrame, pa.Table]:
        if self._input_is_pyarrow:
            return pa.Table.from_pandas(df)
        return df

    def _flatten_pyarrow(self, table: pa.Table) -> pa.Table:
        if table.num_rows == 0:
            self._schema = {}
            self._original_columns = table.column_names
            return table

        self._original_columns = table.column_names
        self._schema = {}
        flat_columns = {}

        col_types = {}
        for col_name in table.column_names:
            col = table.column(col_name)
            col_types[col_name] = col.type
            col_schema = self._build_column_schema_from_arrow(col_name, col)
            self._schema[col_name] = col_schema
            flat_col_data = self._flatten_column_arrow(
                col, col_schema.root_node, [col_name]
            )
            flat_columns.update(flat_col_data)

        self._input_is_pyarrow = True
        col_names = list(flat_columns.keys())
        arrays = []
        for col_name in col_names:
            values = flat_columns[col_name]
            if col_name in col_types and pa.types.is_timestamp(col_types[col_name]):
                safe_values = [v if v is None else str(v) for v in values]
                arrays.append(pa.chunked_array([safe_values], type=pa.string()))
            else:
                type_hint = None
                if col_name in self._schema:
                    root = self._schema[col_name].root_node
                    if root and root.dtype:
                        dtype = root.dtype
                        if isinstance(dtype, str) and "timestamp" in dtype.lower():
                            type_hint = pa.string()
                if type_hint:
                    safe_values = [v if v is None else str(v) for v in values]
                    arrays.append(pa.chunked_array([safe_values], type=type_hint))
                else:
                    try:
                        arrays.append(pa.chunked_array([values]))
                    except OverflowError:
                        safe_values = [
                            str(v) if v is not None else None for v in values
                        ]
                        arrays.append(pa.chunked_array([safe_values], type=pa.string()))

        flat_table = pa.Table.from_arrays(arrays, names=col_names)
        self._array_metadata = self._extract_array_metadata(flat_table=flat_table)
        return flat_table

    def _chunked_array_to_list(self, col: pa.ChunkedArray) -> List[Any]:
        if pa.types.is_timestamp(col.type):
            values = []
            for chunk in col.chunks:
                for i in range(len(chunk)):
                    if chunk[i].is_valid:
                        try:
                            ts = chunk[i].as_py()
                            values.append(ts.isoformat())
                        except Exception:
                            ts_val = chunk[i].value
                            values.append(f"TIMESTAMP_NS:{ts_val}")
                    else:
                        values.append(None)
            return values
        elif pa.types.is_struct(col.type):
            return self._struct_array_to_list(col)
        elif pa.types.is_list(col.type) or pa.types.is_large_list(col.type):
            return self._list_array_to_list(col)
        return col.to_pylist()

    def _struct_array_to_list(self, col: pa.ChunkedArray) -> List[Dict[str, Any]]:
        result = []
        for chunk in col.chunks:
            for i in range(len(chunk)):
                if not chunk[i].is_valid:
                    result.append(None)
                else:
                    result.append(self._extract_struct_value(chunk[i]))
        return result

    def _is_extension_type(self, arrow_type) -> bool:
        return hasattr(arrow_type, "storage_type")

    def _extract_struct_value(self, struct_scalar: pa.StructScalar) -> Dict[str, Any]:
        struct_dict = {}
        for j in range(len(struct_scalar)):
            field = struct_scalar.type[j]
            field_val = struct_scalar[j]
            if not field_val.is_valid:
                struct_dict[field.name] = None
            elif pa.types.is_timestamp(field.type):
                if field_val.is_valid:
                    try:
                        ts = field_val.as_py()
                        struct_dict[field.name] = ts.isoformat()
                    except Exception:
                        ts_val = field_val.value
                        struct_dict[field.name] = f"TIMESTAMP_NS:{ts_val}"
                else:
                    struct_dict[field.name] = None
            elif self._is_extension_type(field.type):
                storage_type = field.type.storage_type
                if pa.types.is_timestamp(storage_type):
                    if field_val.is_valid:
                        try:
                            ts = field_val.as_py()
                            struct_dict[field.name] = ts.isoformat()
                        except Exception:
                            ts_val = field_val.value
                            struct_dict[field.name] = f"TIMESTAMP_NS:{ts_val}"
                    else:
                        struct_dict[field.name] = None
                else:
                    struct_dict[field.name] = str(field_val.as_py())
            elif pa.types.is_struct(field.type):
                struct_dict[field.name] = self._extract_struct_value(field_val)
            elif pa.types.is_list(field.type) or pa.types.is_large_list(field.type):
                struct_dict[field.name] = self._extract_list_value(field_val)
            else:
                struct_dict[field.name] = field_val.as_py()
        return struct_dict

    def _extract_list_value(self, list_scalar: pa.ListScalar) -> List[Any]:
        list_vals = []
        item_type = list_scalar.type.value_type
        for j in range(len(list_scalar)):
            item = list_scalar[j]
            if not item.is_valid:
                list_vals.append(None)
            elif pa.types.is_timestamp(item_type):
                if item.is_valid:
                    try:
                        ts = item.as_py()
                        list_vals.append(ts.isoformat())
                    except Exception:
                        ts_val = item.value
                        list_vals.append(f"TIMESTAMP_NS:{ts_val}")
                else:
                    list_vals.append(None)
            elif self._is_extension_type(item_type):
                storage_type = item_type.storage_type
                if pa.types.is_timestamp(storage_type):
                    if item.is_valid:
                        try:
                            ts = item.as_py()
                            list_vals.append(ts.isoformat())
                        except Exception:
                            ts_val = item.value
                            list_vals.append(f"TIMESTAMP_NS:{ts_val}")
                    else:
                        list_vals.append(None)
                else:
                    list_vals.append(str(item.as_py()))
            elif pa.types.is_struct(item_type):
                list_vals.append(self._extract_struct_value(item))
            elif pa.types.is_list(item_type) or pa.types.is_large_list(item_type):
                list_vals.append(self._extract_list_value(item))
            else:
                list_vals.append(item.as_py())
        return list_vals

    def _list_array_to_list(self, col: pa.ChunkedArray) -> List[List[Any]]:
        result = []
        for chunk in col.chunks:
            for i in range(len(chunk)):
                if not chunk[i].is_valid:
                    result.append(None)
                else:
                    result.append(self._extract_list_value(chunk[i]))
        return result

    def _flatten_pandas(self, df: pd.DataFrame) -> pd.DataFrame:
        self._input_is_pyarrow = False
        if df.empty:
            self._schema = {}
            self._original_columns = df.columns.tolist()
            return df.copy()

        self._original_columns = df.columns.tolist()
        self._schema = {}
        flat_data = {}

        for col in df.columns:
            series = df[col]
            col_schema = self._build_column_schema(col, series)
            self._schema[col] = col_schema
            flat_col_data = self._flatten_column(series, col_schema.root_node, [col])
            flat_data.update(flat_col_data)

        flat_df = pd.DataFrame(flat_data, index=df.index)
        self._array_metadata = self._extract_array_metadata_from_dataframe(
            flat_df=flat_df
        )
        return flat_df

    def _unflatten_pyarrow(self, flat_table: pa.Table) -> pa.Table:
        if not self._schema:
            raise ValueError(
                "Call flatten() first or load schema via load_schema_from_dict()"
            )
        if flat_table.num_rows == 0:
            return pa.Table.from_pydict({col: [] for col in self._original_columns})

        result = {}
        for col_name, col_schema in self._schema.items():
            root_dtype = col_schema.root_node.dtype
            
            if col_schema.root_node.node_type == NodeType.SCALAR:
                if col_name in flat_table.column_names:
                    result[col_name] = flat_table.column(col_name)
                elif root_dtype == "null":
                    null_arr = pa.array([None] * flat_table.num_rows, type=pa.null())
                    result[col_name] = pa.chunked_array([null_arr])
                else:
                    result[col_name] = flat_table.column(col_name)
            else:
                result[col_name] = self._unflatten_column_arrow(flat_table, col_schema)

        self._input_is_pyarrow = True
        table = pa.Table.from_pydict(result)
        return table

    def _unflatten_pandas(self, flat_df: pd.DataFrame) -> pd.DataFrame:
        self._input_is_pyarrow = False
        if not self._schema:
            raise ValueError(
                "Call flatten() first or load schema via load_schema_from_dict()"
            )
        if flat_df.empty:
            return pd.DataFrame(columns=self._original_columns)

        result = {}
        for col_name, col_schema in self._schema.items():
            if col_schema.root_node.node_type == NodeType.SCALAR:
                result[col_name] = flat_df[col_name]
            else:
                result[col_name] = self._unflatten_column(flat_df, col_schema)
        return pd.DataFrame(result, index=flat_df.index)

    def _build_column_schema(self, col_name: str, series: pd.Series) -> ColumnSchema:
        values = series.tolist()
        non_null_values = [
            v
            for v in values
            if v is not None and not (isinstance(v, float) and np.isnan(v))
        ]

        if not non_null_values:
            return ColumnSchema(
                name=col_name,
                root_node=SchemaNode(
                    node_type=NodeType.SCALAR, dtype=str(series.dtype)
                ),
            )

        root_node = self._infer_schema_from_values(values)
        return ColumnSchema(name=col_name, root_node=root_node)

    def _build_column_schema_from_arrow(
        self, col_name: str, col: pa.ChunkedArray
    ) -> ColumnSchema:
        col_type = col.type

        if pa.types.is_struct(col_type):
            values = self._struct_array_to_list(col)
            root_node = self._infer_schema_from_values_arrow(values, col_type)
            return ColumnSchema(name=col_name, root_node=root_node)

        if pa.types.is_list(col_type) or pa.types.is_large_list(col_type):
            values = self._list_array_to_list(col)
            root_node = self._infer_schema_from_values_arrow(values, col_type)
            return ColumnSchema(name=col_name, root_node=root_node)

        if pa.types.is_null(col_type):
            return ColumnSchema(
                name=col_name,
                root_node=SchemaNode(node_type=NodeType.SCALAR, dtype="null"),
            )

        non_null = col.filter(pc.not_equal(col, None)).to_pylist()
        non_null = [v for v in non_null if v is not None]

        if not non_null:
            return ColumnSchema(
                name=col_name,
                root_node=SchemaNode(node_type=NodeType.SCALAR, dtype=str(col_type)),
            )

        root_node = self._infer_schema_from_values_arrow(non_null, col_type)
        return ColumnSchema(name=col_name, root_node=root_node)

    def _infer_schema_from_values_arrow(
        self, values: List[Any], pa_type: pa.DataType
    ) -> SchemaNode:
        if pa.types.is_list(pa_type) or pa.types.is_large_list(pa_type):
            element_type = pa_type.value_type
            max_len = 0
            has_nulls = False
            has_null_elements = False
            element_values = []

            for v in values:
                if v is None:
                    has_nulls = True
                    continue
                max_len = max(max_len, len(v))
                for item in v:
                    if item is None:
                        has_null_elements = True
                        has_nulls = True
                    else:
                        element_values.append(item)

            if not element_values:
                element_schema = SchemaNode(node_type=NodeType.SCALAR, dtype="object")
            else:
                element_schema = self._infer_schema_from_values_arrow(
                    element_values, element_type
                )

            return SchemaNode(
                node_type=NodeType.ARRAY,
                element_schema=element_schema,
                nullable_elements=has_nulls,
                nullable_array=False,
                max_elements=max_len,
                has_null_elements=has_null_elements,
            )
        elif pa.types.is_struct(pa_type):
            children = {}
            for i, pa_field in enumerate(pa_type):
                field_name = pa_field.name
                field_values = []
                for v in values:
                    if isinstance(v, dict):
                        field_values.append(v.get(field_name))
                    elif hasattr(v, field_name):
                        field_values.append(getattr(v, field_name))
                    else:
                        field_values.append(None)
                children[field_name] = self._infer_schema_from_values_arrow(
                    field_values, pa_field.type
                )
            return SchemaNode(node_type=NodeType.DICT, children=children)
        else:
            dtype = self._pa_type_to_dtype(pa_type)
            return SchemaNode(node_type=NodeType.SCALAR, dtype=dtype)

    def _pa_type_to_dtype(self, pa_type: pa.DataType) -> str:
        if pa.types.is_integer(pa_type):
            return "int64"
        elif pa.types.is_floating(pa_type):
            return "float64"
        elif pa.types.is_boolean(pa_type):
            return "bool"
        elif pa.types.is_string(pa_type) or pa.types.is_large_string(pa_type):
            return "object"
        else:
            return "object"

    def _flatten_column_arrow(
        self, col: pa.ChunkedArray, schema_node: SchemaNode, path: List[str]
    ) -> Dict[str, List[Any]]:
        result = {}
        col_name = ".".join(path)

        if schema_node.node_type == NodeType.SCALAR:
            result[col_name] = self._chunked_array_to_list(col)

        elif schema_node.node_type == NodeType.DICT:
            for key, child_schema in schema_node.children.items():
                child_path = path + [key]
                child_col_data: List[Any] = []
                py_list = self._chunked_array_to_list(col)
                for v in py_list:
                    if v is None:
                        child_col_data.append(None)
                    elif isinstance(v, dict):
                        child_col_data.append(v.get(key))
                    else:
                        child_col_data.append(None)
                child_result = self._flatten_column_arrow_plain(
                    child_col_data, child_schema, child_path
                )
                result.update(child_result)

        elif schema_node.node_type == NodeType.ARRAY:
            max_elements = schema_node.max_elements if schema_node.max_elements else 1
            py_list = self._chunked_array_to_list(col)
            element_schema = schema_node.element_schema

            if schema_node.nullable_array:
                result[f"{col_name}._is_null"] = [v is None for v in py_list]

            if element_schema and element_schema.node_type == NodeType.DICT:
                child_fields = element_schema.children
                for i in range(max_elements):
                    for field_name, field_schema in child_fields.items():
                        field_values = []
                        for v in py_list:
                            if v is None:
                                field_values.append(None)
                            elif isinstance(v, list) and i < len(v):
                                elem = v[i]
                                if isinstance(elem, dict):
                                    field_values.append(elem.get(field_name))
                                else:
                                    field_values.append(None)
                            else:
                                field_values.append(None)
                        result[f"{col_name}__{i}.{field_name}"] = field_values
            else:
                for i in range(max_elements):
                    element_values = []
                    for v in py_list:
                        if v is None:
                            element_values.append(None)
                        elif isinstance(v, list):
                            if i < len(v):
                                element_values.append(v[i])
                            else:
                                element_values.append(None)
                        else:
                            element_values.append(None)
                    result[f"{col_name}__{i}"] = element_values

        return result

    def _flatten_column_arrow_plain(
        self, col_data: List[Any], schema_node: SchemaNode, path: List[str]
    ) -> Dict[str, List[Any]]:
        result = {}
        col_name = ".".join(path)

        if schema_node.node_type == NodeType.SCALAR:
            result[col_name] = col_data

        elif schema_node.node_type == NodeType.DICT:
            for key, child_schema in schema_node.children.items():
                child_path = path + [key]
                child_col_data: List[Any] = []
                for v in col_data:
                    if v is None:
                        child_col_data.append(None)
                    elif isinstance(v, dict):
                        child_col_data.append(v.get(key))
                    else:
                        child_col_data.append(None)
                child_result = self._flatten_column_arrow_plain(
                    child_col_data, child_schema, child_path
                )
                result.update(child_result)

        elif schema_node.node_type == NodeType.ARRAY:
            max_elements = schema_node.max_elements if schema_node.max_elements else 1

            for i in range(max_elements):
                element_values = []
                for v in col_data:
                    if v is None:
                        element_values.append(None)
                    elif isinstance(v, list):
                        if i < len(v):
                            element_values.append(v[i])
                        else:
                            element_values.append(None)
                    else:
                        element_values.append(None)
                result[f"{col_name}__{i}"] = element_values

        return result

    def _build_struct_fields(self, schema_node: SchemaNode) -> List[pa.Field]:
        """Build PyArrow struct fields from SchemaNode children."""
        if schema_node.node_type != NodeType.DICT:
            return []
        fields = []
        for key, child_schema in schema_node.children.items():
            field_type = self._schema_node_to_pyarrow_type(child_schema)
            fields.append(pa.field(key, field_type, nullable=True))
        return fields

    def _schema_node_to_pyarrow_type(self, schema_node: SchemaNode) -> pa.DataType:
        """Convert a SchemaNode to PyArrow type."""
        if schema_node.node_type == NodeType.SCALAR:
            dtype = schema_node.dtype
            if dtype == "int64":
                return pa.int64()
            elif dtype == "float64":
                return pa.float64()
            elif dtype == "bool":
                return pa.bool()
            elif dtype == "object":
                return pa.string()
            elif dtype == "null":
                return pa.null()
            else:
                return pa.string()
        elif schema_node.node_type == NodeType.DICT:
            child_fields = []
            for key, child_schema in schema_node.children.items():
                child_type = self._schema_node_to_pyarrow_type(child_schema)
                child_fields.append(pa.field(key, child_type, nullable=True))
            return pa.struct(child_fields)
        elif schema_node.node_type == NodeType.ARRAY:
            element_type = self._schema_node_to_pyarrow_type(schema_node.element_schema) if schema_node.element_schema else pa.string()
            return pa.list_(element_type)
        return pa.string()

    def _unflatten_dict_column_arrow(
        self, flat_table: pa.Table, col_schema: ColumnSchema, schema_node: SchemaNode
    ) -> pa.Array:
        col_name = col_schema.name
        num_rows = flat_table.num_rows
        result_dicts: List[Dict[str, Any]] = [{} for _ in range(num_rows)]

        for key, child_schema in schema_node.children.items():
            child_col_name = f"{col_name}.{key}"
            child_col_schema = ColumnSchema(name=child_col_name, root_node=child_schema)
            child_array = self._unflatten_column_arrow(flat_table, child_col_schema)
            child_values = child_array.to_pylist()
            for i, val in enumerate(child_values):
                result_dicts[i][key] = val

        try:
            result_array = pa.array(result_dicts)
        except pa.ArrowInvalid:
            result_array = pa.array(result_dicts, type=pa.string())
        return pa.chunked_array([result_array])

    def _unflatten_column_arrow(
        self, flat_table: pa.Table, col_schema: ColumnSchema
    ) -> pa.Array:
        schema_node = col_schema.root_node

        if schema_node.node_type == NodeType.SCALAR:
            if col_schema.name in flat_table.column_names:
                return flat_table.column(col_schema.name)
            return flat_table.column(col_schema.name)

        elif schema_node.node_type == NodeType.DICT:
            return self._unflatten_dict_column_arrow(
                flat_table, col_schema, schema_node
            )

        elif schema_node.node_type == NodeType.ARRAY:
            return self._unflatten_array_column_arrow(
                flat_table, col_schema, schema_node
            )

        return flat_table.column(col_schema.name)

    def _unflatten_array_column_arrow(
        self, flat_table: pa.Table, col_schema: ColumnSchema, schema_node: SchemaNode
    ) -> pa.Array:
        col_name = col_schema.name
        max_elements = schema_node.max_elements if schema_node.max_elements else 1
        num_rows = flat_table.num_rows
        element_schema = schema_node.element_schema
        nullable_elements = schema_node.nullable_elements
        has_null_elements = getattr(schema_node, 'has_null_elements', False)

        if element_schema and element_schema.node_type == NodeType.DICT:
            child_fields = element_schema.children
            result_lists = [[] for _ in range(num_rows)]
            for row_idx in range(num_rows):
                row_items = []
                for i in range(max_elements):
                    struct_dict = {}
                    found_any = False
                    for field_name in child_fields.keys():
                        indexed_col_name = f"{col_name}__{i}.{field_name}"
                        if indexed_col_name in flat_table.column_names:
                            col = flat_table.column(indexed_col_name)
                            raw_val = col.to_pylist()[row_idx]
                            if raw_val is None or (isinstance(raw_val, float) and np.isnan(raw_val)):
                                val = None
                            else:
                                val = raw_val
                            struct_dict[field_name] = val
                            found_any = True
                        else:
                            struct_dict[field_name] = None
                    if found_any:
                        if not nullable_elements:
                            row_items.append(struct_dict)
                        else:
                            has_null_in_struct = any(
                                v is None or (isinstance(v, float) and np.isnan(v))
                                for v in struct_dict.values()
                            )
                            if not has_null_in_struct:
                                row_items.append(struct_dict)
                            elif has_null_elements:
                                row_items.append(struct_dict)
                    else:
                        if not nullable_elements:
                            pass
                        else:
                            if has_null_elements:
                                row_items.append(None)
                result_lists[row_idx] = row_items

            if result_lists and result_lists[0]:
                first_item = result_lists[0][0]
                if first_item is not None:
                    nested_fields = []
                    for field_name in child_fields.keys():
                        field_val = first_item.get(field_name)
                        if field_val is None or (isinstance(field_val, float) and np.isnan(field_val)):
                            field_type = pa.string()
                        elif isinstance(field_val, bool):
                            field_type = pa.bool_()
                        elif isinstance(field_val, int):
                            field_type = pa.int64()
                        elif isinstance(field_val, float):
                            field_type = pa.float64()
                        else:
                            field_type = pa.string()
                        nested_fields.append(pa.field(field_name, field_type, nullable=True))
                    element_type = pa.struct(nested_fields)
                    list_type = pa.list_(element_type)
                    try:
                        result_array = pa.array(result_lists, type=list_type)
                    except (pa.ArrowInvalid, pa.ArrowTypeError):
                        string_lists = [[str(item) if item is not None else None for item in row] for row in result_lists]
                        result_array = pa.array(string_lists, type=pa.list_(pa.string()))
                    return pa.chunked_array([result_array])

            empty_type = pa.list_(pa.string())
            result_array = pa.array(result_lists, type=empty_type)
            return pa.chunked_array([result_array])

        result_lists = [[] for _ in range(num_rows)]
        for i in range(max_elements):
            indexed_col_name = f"{col_name}__{i}"
            if indexed_col_name in flat_table.column_names:
                col = flat_table.column(indexed_col_name)
                col_values = col.to_pylist()
            else:
                col_values = [None] * num_rows
            for row_idx, raw_val in enumerate(col_values):
                is_null = raw_val is None or (isinstance(raw_val, float) and np.isnan(raw_val))
                if is_null:
                    if nullable_elements and has_null_elements:
                        result_lists[row_idx].append(None)
                else:
                    result_lists[row_idx].append(raw_val)

        if element_schema:
            element_type = self._schema_node_to_pyarrow_type(element_schema)
            list_type = pa.list_(element_type)
        else:
            list_type = pa.list_(pa.string())

        try:
            result_array = pa.array(result_lists, type=list_type)
        except (pa.ArrowInvalid, pa.ArrowTypeError):
            string_lists = [[str(item) if item is not None else None for item in row] for row in result_lists]
            result_array = pa.array(string_lists, type=pa.list_(pa.string()))
        return pa.chunked_array([result_array])

    def _infer_schema_from_values(self, values: List[Any]) -> SchemaNode:
        sample = None
        for v in values:
            if v is not None and not (isinstance(v, float) and np.isnan(v)):
                sample = v
                break

        if sample is None:
            return SchemaNode(node_type=NodeType.SCALAR, dtype="object")

        if isinstance(sample, dict):
            return self._infer_dict_schema(values)
        elif isinstance(sample, (list, np.ndarray)):
            return self._infer_array_schema(values)
        else:
            return SchemaNode(
                node_type=NodeType.SCALAR, dtype=self._infer_dtype(values)
            )

    def _infer_dict_schema(self, values: List[Any]) -> SchemaNode:
        all_keys = set()
        key_values: Dict[str, List[Any]] = {}

        for v in values:
            if isinstance(v, dict):
                for k, val in v.items():
                    all_keys.add(k)
                    key_values.setdefault(k, []).append(val)

        children = {}
        for key in all_keys:
            children[key] = self._infer_schema_from_values(key_values.get(key, []))
        return SchemaNode(node_type=NodeType.DICT, children=children)

    def _infer_array_schema(self, values: List[Any]) -> SchemaNode:
        has_nulls = False
        has_null_array = False
        has_null_elements = False
        element_values = []
        max_len = 0

        for v in values:
            if v is None or (isinstance(v, float) and np.isnan(v)):
                has_null_array = True
                continue
            if isinstance(v, np.ndarray):
                v = v.tolist()
            if isinstance(v, list):
                max_len = max(max_len, len(v))
                for item in v:
                    if item is None or (isinstance(item, float) and np.isnan(item)):
                        has_null_elements = True
                        has_nulls = True
                    else:
                        element_values.append(item)

        if not element_values:
            element_schema = SchemaNode(node_type=NodeType.SCALAR, dtype="object")
        else:
            element_schema = self._infer_schema_from_values(element_values)

        return SchemaNode(
            node_type=NodeType.ARRAY,
            element_schema=element_schema,
            nullable_elements=has_nulls,
            nullable_array=has_null_array,
            max_elements=max_len,
            has_null_elements=has_null_elements,
        )

    def _infer_dtype(self, values: List[Any]) -> str:
        cleaned = [
            v
            for v in values
            if v is not None and not (isinstance(v, float) and np.isnan(v))
        ]
        if not cleaned:
            return "object"

        sample = cleaned[0]
        if isinstance(sample, (int, np.integer)):
            return "int64"
        elif isinstance(sample, (float, np.floating)):
            return "float64"
        elif isinstance(sample, bool):
            return "bool"
        elif isinstance(sample, str):
            return "object"
        else:
            return "object"

    def _flatten_column(
        self, series: pd.Series, schema_node: SchemaNode, path: List[str]
    ) -> Dict[str, List[Any]]:
        result = {}

        if schema_node.node_type == NodeType.SCALAR:
            col_name = ".".join(path)
            result[col_name] = series.tolist()

        elif schema_node.node_type == NodeType.DICT:
            for key, child_schema in schema_node.children.items():
                child_path = path + [key]
                child_values = [
                    (
                        series.iloc[i].get(key)
                        if isinstance(series.iloc[i], dict)
                        else None
                    )
                    for i in range(len(series))
                ]
                child_series = pd.Series(child_values, index=series.index)
                child_result = self._flatten_column(
                    child_series, child_schema, child_path
                )
                result.update(child_result)

        elif schema_node.node_type == NodeType.ARRAY:
            col_name = ".".join(path)
            max_elements = schema_node.max_elements

            if schema_node.nullable_array:
                result[f"{col_name}._is_null"] = [
                    v is None or (isinstance(v, float) and np.isnan(v)) for v in series
                ]

            for i in range(max_elements):
                element_values = []
                for v in series:
                    if v is None or (isinstance(v, float) and np.isnan(v)):
                        element_values.append(None)
                    elif isinstance(v, (list, np.ndarray)):
                        if i < len(v):
                            element_values.append(v[i])
                        else:
                            element_values.append(None)
                    else:
                        element_values.append(None)
                result[f"{col_name}[{i}]"] = element_values

        return result

    def _unflatten_column(
        self, flat_df: pd.DataFrame, col_schema: ColumnSchema
    ) -> pd.Series:
        schema_node = col_schema.root_node

        if schema_node.node_type == NodeType.SCALAR:
            return flat_df[col_schema.name]

        elif schema_node.node_type == NodeType.DICT:
            return self._unflatten_dict_column(flat_df, col_schema, schema_node)

        elif schema_node.node_type == NodeType.ARRAY:
            return self._unflatten_array_column(flat_df, col_schema, schema_node)

    def _unflatten_dict_column(
        self, flat_df: pd.DataFrame, col_schema: ColumnSchema, schema_node: SchemaNode
    ) -> pd.Series:
        result = []
        for idx in flat_df.index:
            dict_value = {}
            for key, child_schema in schema_node.children.items():
                child_col_schema = ColumnSchema(
                    name=f"{col_schema.name}.{key}", root_node=child_schema
                )
                child_series = self._unflatten_column(flat_df, child_col_schema)
                dict_value[key] = child_series.get(idx, None)
            result.append(dict_value)
        return pd.Series(result, index=flat_df.index)

    def _process_nested_array(self, arr: Any, element_schema: SchemaNode) -> Any:
        if arr is None:
            return None
        if isinstance(arr, np.ndarray):
            arr = arr.tolist()
        if not isinstance(arr, list):
            return arr

        result = []
        for item in arr:
            if element_schema.node_type == NodeType.DICT and isinstance(item, dict):
                processed = {}
                for key, child_schema in element_schema.children.items():
                    child_value = item.get(key)
                    if child_schema.node_type == NodeType.DICT:
                        processed[key] = self._process_nested_dict(
                            child_value, child_schema
                        )
                    elif child_schema.node_type == NodeType.ARRAY:
                        processed[key] = self._process_nested_array(
                            child_value, child_schema.element_schema
                        )
                    else:
                        processed[key] = child_value
                result.append(processed)
            elif element_schema.node_type == NodeType.ARRAY and isinstance(
                item, (list, np.ndarray)
            ):
                result.append(
                    self._process_nested_array(item, element_schema.element_schema)
                )
            else:
                result.append(item)
        return result

    def _process_nested_dict(self, d: Any, schema_node: SchemaNode) -> Any:
        if d is None:
            return None
        if not isinstance(d, dict):
            return d
        result = {}
        for key, child_schema in schema_node.children.items():
            child_value = d.get(key)
            if child_schema.node_type == NodeType.DICT:
                result[key] = self._process_nested_dict(child_value, child_schema)
            elif child_schema.node_type == NodeType.ARRAY:
                result[key] = self._process_nested_array(
                    child_value, child_schema.element_schema
                )
            else:
                result[key] = child_value
        return result

    def _unflatten_array_column(
        self, flat_df: pd.DataFrame, col_schema: ColumnSchema, schema_node: SchemaNode
    ) -> pd.Series:
        col_name = col_schema.name
        max_elements = schema_node.max_elements
        nullable_array = schema_node.nullable_array
        nullable_elements = schema_node.nullable_elements

        is_null_col = None
        if nullable_array:
            is_null_col = flat_df.get(f"{col_name}._is_null")
            if is_null_col is None:
                is_null_col = pd.Series([False] * len(flat_df), index=flat_df.index)

        result = []
        for idx in flat_df.index:
            if nullable_array and is_null_col is not None and is_null_col.iloc[idx]:
                result.append(None)
                continue

            values = []
            for i in range(max_elements):
                element_col = flat_df.get(f"{col_name}[{i}]")
                if element_col is not None:
                    val = element_col.iloc[idx]

                    if (
                        schema_node.element_schema.node_type == NodeType.DICT
                        and isinstance(val, dict)
                    ):
                        processed = self._process_nested_dict(
                            val, schema_node.element_schema
                        )
                        if not nullable_elements and processed is None:
                            continue
                        values.append(processed)
                    elif (
                        schema_node.element_schema.node_type == NodeType.ARRAY
                        and isinstance(val, (list, np.ndarray))
                    ):
                        processed = self._process_nested_array(
                            val, schema_node.element_schema.element_schema
                        )
                        if not nullable_elements and processed is None:
                            continue
                        values.append(processed)
                    else:
                        if pd.isna(val):
                            if not nullable_elements:
                                continue
                        values.append(val)
                elif not nullable_elements:
                    pass

            result.append(values)

        return pd.Series(result, index=flat_df.index)
