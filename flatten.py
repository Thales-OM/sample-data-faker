import pandas as pd
import numpy as np
from typing import Any, Dict, List, Tuple, Union


# FIXME: currently produces null values inside varied length arrays
class DataFrameFlattener:
    def __init__(self):
        self._schema = None
        self._original_columns = None

    def flatten(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            self._schema = {}
            self._original_columns = df.columns.tolist()
            return df.copy()

        self._original_columns = df.columns.tolist()
        flat_data = {}
        schema = {}

        for col in df.columns:
            series = df[col]
            all_paths = set()
            row_data = []

            for value in series:
                paths = self._flatten_value(value, [col])
                all_paths.update(paths.keys())
                row_data.append(paths)

            for path in sorted(all_paths):
                col_name = self._path_to_column(path)
                schema[col_name] = path
                flat_data[col_name] = [r.get(path, None) for r in row_data]

        self._schema = schema
        return pd.DataFrame(flat_data, index=df.index)

    def unflatten(self, flat_df: pd.DataFrame) -> pd.DataFrame:
        if self._schema is None:
            raise ValueError("Call flatten() first")
        if flat_df.empty:
            return pd.DataFrame(columns=self._original_columns)

        result = {}
        for root in self._original_columns:
            paths_for_root = {k: v for k, v in self._schema.items() if v[0] == root}
            if not paths_for_root:
                result[root] = flat_df.get(root, pd.Series([None] * len(flat_df)))
                continue

            sample_path = next(iter(paths_for_root.values()))
            if len(sample_path) == 1:
                result[root] = flat_df[root]
                continue

            first_key = sample_path[1]
            try:
                int(first_key)
                root_is_list = True
            except ValueError:
                root_is_list = False

            rows = []
            for idx in flat_df.index:
                if root_is_list:
                    max_idx = -1
                    for path in paths_for_root.values():
                        if len(path) > 1:
                            try:
                                k = int(path[1])
                                max_idx = max(max_idx, k)
                            except ValueError:
                                pass
                    container = [None] * (max_idx + 1) if max_idx >= 0 else []
                else:
                    container = {}

                for flat_col, path in paths_for_root.items():
                    if len(path) == 1:
                        container = flat_df.at[idx, flat_col]
                        break
                    value = (
                        flat_df.at[idx, flat_col]
                        if flat_col in flat_df.columns
                        else None
                    )
                    self._assign_path(container, path[1:], value)

                rows.append(container)
            result[root] = rows

        return pd.DataFrame(result, index=flat_df.index)

    def _flatten_value(
        self, value: Any, base_path: List[str]
    ) -> Dict[Tuple[str, ...], Any]:
        if value is None:
            return {tuple(base_path): None}
        if isinstance(value, np.ndarray):
            value = value.tolist()
        if pd.api.types.is_scalar(value):
            return {tuple(base_path): None if pd.isna(value) else value}
        if isinstance(value, dict):
            res = {}
            for k, v in value.items():
                res.update(self._flatten_value(v, base_path + [str(k)]))
            return res
        if isinstance(value, (list, tuple)):
            res = {}
            for i, v in enumerate(value):
                res.update(self._flatten_value(v, base_path + [str(i)]))
            return res
        return {tuple(base_path): value}

    def _assign_path(self, obj: Union[Dict, List], path: List[str], value: Any):
        if not path:
            return  # Guard against empty path
        current = obj
        for i, key in enumerate(path):
            is_last = i == len(path) - 1
            try:
                idx = int(key)
                is_index = str(idx) == key
            except ValueError:
                is_index = False

            if is_index:
                if not isinstance(current, list):
                    raise ValueError(
                        f"Expected list at path {path[:i]}, got {type(current)}"
                    )
                while len(current) <= idx:
                    current.append(None)
                if is_last:
                    current[idx] = value
                else:
                    if current[idx] is None:
                        next_key = path[i + 1]
                        try:
                            int(next_key)
                            current[idx] = []
                        except ValueError:
                            current[idx] = {}
                    current = current[idx]
            else:
                if not isinstance(current, dict):
                    raise ValueError(
                        f"Expected dict at path {path[:i]}, got {type(current)}"
                    )
                if is_last:
                    current[key] = value
                else:
                    if key not in current or current[key] is None:
                        next_key = path[i + 1]
                        try:
                            int(next_key)
                            current[key] = []
                        except ValueError:
                            current[key] = {}
                    current = current[key]

    def _path_to_column(self, path: Tuple[str, ...]) -> str:
        if len(path) == 1:
            return path[0]
        return path[0] + "".join(f"[{p}]" for p in path[1:])
