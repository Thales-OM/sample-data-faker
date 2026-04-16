import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


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

    def flatten(self, df: pd.DataFrame) -> pd.DataFrame:
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

        return pd.DataFrame(flat_data, index=df.index)

    def unflatten(self, flat_df: pd.DataFrame) -> pd.DataFrame:
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
