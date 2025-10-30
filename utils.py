import numpy as np
import pandas as pd
from typing import Any


def get_s3_iceberg_path(table_fqn: str) -> str:
    # TODO: replace with translation and OpenMetadata API verification
    return table_fqn


def to_python_native(obj: Any) -> Any:
    """
    Recursively convert NumPy/Pandas values to native Python types for JSON serialization.
    Handles scalars, arrays, lists, dicts, and None/NaN.
    """
    # Handle None first
    if obj is None:
        return None

    # Handle NumPy arrays early (before pd.isna!)
    if isinstance(obj, np.ndarray):
        return obj.tolist()  # Converts nested arrays/scalars recursively

    # Handle Pandas/NumPy scalars
    if isinstance(obj, (np.integer, np.floating, np.bool_)):
        return obj.item()  # Safely converts to Python native

    # Handle Pandas NA/NaT (scalar)
    if pd.api.types.is_scalar(obj) and pd.isna(obj):
        return None

    # Handle dicts
    if isinstance(obj, dict):
        return {k: to_python_native(v) for k, v in obj.items()}

    # Handle lists/tuples
    if isinstance(obj, (list, tuple)):
        return [to_python_native(v) for v in obj]

    # Fallback: assume it's a native type (str, bool, int, float, etc.)
    return obj
