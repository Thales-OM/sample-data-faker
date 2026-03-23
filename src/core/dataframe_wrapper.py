import pandas as pd
import numpy as np
from typing import Optional
from functools import cached_property


class DataFrameWrapper:
    """
    Wrapper for DataFrames that provides both raw and cleaned access.
    Conversion to Python types is lazy (only on first access to .df_clean).
    """

    def __init__(self, df: pd.DataFrame):
        self._df = df
        self._df_clean: Optional[pd.DataFrame] = None

    @property
    def df(self) -> pd.DataFrame:
        """Raw DataFrame with original numpy types."""
        return self._df

    @cached_property
    def df_clean(self) -> pd.DataFrame:
        """DataFrame with pure Python types (lazy conversion)."""
        return self._to_python_types(self._df)

    @staticmethod
    def _to_python_types(df: pd.DataFrame) -> pd.DataFrame:
        """Convert numpy types to pure Python types."""

        def _convert_value(val):
            if isinstance(val, np.generic):
                return val.item()
            elif isinstance(val, dict):
                return {k: _convert_value(v) for k, v in val.items()}
            elif isinstance(val, (list, tuple)):
                converted = [_convert_value(item) for item in val]
                return type(val)(converted)
            return val

        # Use map (pandas >= 2.1.0) or applymap (older)
        if hasattr(df, "map"):
            return df.map(_convert_value)
        else:
            return df.applymap(_convert_value)

    def __len__(self) -> int:
        return len(self._df)

    def __repr__(self) -> str:
        return f"DataFrameWrapper(shape={self._df.shape}, columns={list(self._df.columns)})"
