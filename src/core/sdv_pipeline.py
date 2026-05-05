import pyarrow as pa
import pandas as pd
from enum import StrEnum
from typing import Optional, Union, Tuple, overload, Type, Dict, Any
from sdv.metadata import Metadata
from sdv.single_table.base import BaseSingleTableSynthesizer
from src.core.flatten import DataFrameFlattener
from src.logger import LoggerFactory

logger = LoggerFactory.getLogger(__name__)


class PipelineInputType(StrEnum):
    PANDAS = "pandas"
    PYARROW = "pyarrow"


# NOTE: Could be helpful to hint Generic[T] for .fit()/.sample() type connection, but may confuse pylance
class SDVPipeline:
    """
    Complete pipeline for generating synthetic data using SDV.

    Handles the full lifecycle:
    - Input: Nested PyArrow Table OR pandas DataFrame (from various sources)
    - Flatten for SDV consumption
    - Create metadata for SDV
    - Fit synthesizer
    - Generate synthetic flat data
    - Unflatten back to nested structure
    """

    def __init__(
        self,
        synthesizer_cls: Type[BaseSingleTableSynthesizer],
        model_params: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize the SDV pipeline.

        Args:
            synthesizer_cls (Type[BaseSingleTableSynthesizer]): SDV compatible single table synthesizer class.
            model_params (Optional[Dict[str, Any]], optional): Additional params for synthesizer. Defaults to None.
        """
        self._synthesizer_cls = synthesizer_cls
        self._synthesizer: Optional[BaseSingleTableSynthesizer] = None
        self._model_params: Dict[str, Any] = model_params or dict()

        self._flattener = DataFrameFlattener()
        self._metadata: Optional[Metadata] = None
        self._input_type: Optional[PipelineInputType] = None
        self._pyarrow_schema: Optional[pa.Schema] = None

    @property
    def synthesizer(self) -> BaseSingleTableSynthesizer:
        if not self._synthesizer:
            raise RuntimeError("Call .fit() before accessing .synthesizer property")
        return self._synthesizer

    @property
    def metadata(self) -> Metadata:
        if not self._metadata:
            raise RuntimeError(
                "Call .fit() or .create_metadata() before accessing .metadata property"
            )
        return self._metadata

    @overload
    def flatten(self, data: pa.Table) -> pa.Table: ...

    @overload
    def flatten(self, data: pd.DataFrame) -> pd.DataFrame: ...

    def flatten(
        self, data: Union[pa.Table, pd.DataFrame]
    ) -> Union[pa.Table, pd.DataFrame]:
        """
        Flatten a nested PyArrow Table OR pandas DataFrame for SDV consumption.

        Args:
            data (Union[pyarrow.Table, pandas.DataFrame]): Input with nested structures (either PyArrow Table or pandas DataFrame).

        Raises:
            TypeError: Unexpected input type.

        Returns:
            Union[pyarrow.Table, pandas.DataFrame]: Flattened data of the same type as input
        """
        if isinstance(data, (pa.Table, pd.DataFrame)):
            return self._flattener.flatten(data=data)
        raise TypeError(f"Expected pa.Table or pd.DataFrame, got {type(data)}")

    def create_metadata(self, df: pd.DataFrame) -> Metadata:
        self._metadata = Metadata().detect_from_dataframe(df)
        return self._metadata

    def fit(
        self,
        data: Union[pa.Table, pd.DataFrame],
    ) -> BaseSingleTableSynthesizer:
        """
        Fit an SDV synthesizer on the flat data.

        Args:
            data (Union[pa.Table, pd.DataFrame]): Flattened PyArrow Table or pandas DataFrame.

        Raises:
            TypeError: Wrong "data" argument type.

        Returns:
            BaseSingleTableSynthesizer: Fitted synthesizer instance.
        """
        if isinstance(data, pa.Table):
            self._input_type = PipelineInputType.PYARROW
            self._pyarrow_schema = data.schema
            df = data.to_pandas()
        elif isinstance(data, pd.DataFrame):
            self._input_type = PipelineInputType.PANDAS
            df = data
        else:
            raise TypeError(f"Expected pa.Table or pd.DataFrame, got {type(data)}")

        if self._metadata is None:
            self._metadata = Metadata().detect_from_dataframe(df)

        self._synthesizer = self._synthesizer_cls(
            metadata=self._metadata, enforce_min_max_values=True, **self._model_params
        )
        self._synthesizer.fit(df)
        return self._synthesizer

    def sample(
        self,
        num_rows: int,
    ) -> Union[pa.Table, pd.DataFrame]:
        """
        Sample synthetic datapoints (rows) from fitted synthesizer.

        Args:
            num_rows (int): Number of rows to generate.

        Raises:
            RuntimeError: Calling sample() before calling fit().

        Returns:
            Union[pa.Table, pd.DataFrame]: Flat data of the same type as the .fit() input (pa.Table or pd.DataFrame)
        """
        if not self._synthesizer:
            raise RuntimeError(
                "Synthesizer not fitted with training data. Call fit() first."
            )

        synth_df = self._synthesizer.sample(num_rows=num_rows)

        if self._input_type == PipelineInputType.PYARROW:
            adjusted_df = self._normalize_array_lengths(
                data=synth_df, target_rows=synth_df.shape[0]
            )
            return self._dataframe_to_pyarrow_table(adjusted_df, self._pyarrow_schema)
        return synth_df

    def _dataframe_to_pyarrow_table(
        self,
        df: pd.DataFrame,
        schema: Optional[pa.Schema] = None,
    ) -> pa.Table:
        """
        Convert a pandas DataFrame to PyArrow Table, properly handling null columns.

        Args:
            df: Input DataFrame
            schema: Optional schema to use for column types

        Returns:
            PyArrow Table
        """
        if schema is None:
            return pa.Table.from_pandas(df)

        result_arrays = []
        result_fields = []

        for field in schema:
            col_name = field.name
            expected_type = field.type

            if col_name in df.columns:
                # Use inferred type from pandas if conversion fails
                inferred_type = expected_type
                try:
                    values = df[col_name].values
                    is_all_null = df[col_name].isna().all()
                    is_any_null = df[col_name].isna().any()

                    if pa.types.is_null(expected_type):
                        if is_all_null or is_any_null:
                            inferred_type = pa.float64()
                    elif is_all_null:
                        if pa.types.is_decimal(expected_type):
                            inferred_type = pa.float64()
                    elif is_any_null:
                        if pa.types.is_decimal(expected_type):
                            inferred_type = pa.float64()
                        elif pa.types.is_integer(expected_type):
                            inferred_type = pa.float64()

                    result_arrays.append(pa.array(values, type=inferred_type))
                except Exception as e:
                    # Fallback: convert to string
                    str_vals = [
                        str(v) if pd.notna(v) else None for v in df[col_name].tolist()
                    ]
                    inferred_type = pa.string()
                    result_arrays.append(pa.array(str_vals, type=inferred_type))
            else:
                result_arrays.append(pa.array([None] * len(df), type=expected_type))
                inferred_type = expected_type

            result_fields.append(pa.field(col_name, inferred_type))

        return pa.Table.from_arrays(result_arrays, schema=pa.schema(result_fields))

    @staticmethod
    def _normalize_array_lengths(
        data: pd.DataFrame,
        target_rows: int,
    ) -> pd.DataFrame:
        """
        Normalize array column lengths to match target row count.

        SDV generates arrays with independent patterns, which can result in
        column lengths that don't match the target row count. This normalizes
        all columns to have exactly target_rows elements.

        Args:
            data: DataFrame or Table with potentially mismatched array lengths
            target_rows: Expected number of rows

        Returns:
            DataFrame with normalized column lengths
        """
        if isinstance(data, pa.Table):
            df = data.to_pandas()
        else:
            df = data

        result_df = pd.DataFrame()
        for col_name in df.columns:
            values = df[col_name].tolist()
            if len(values) != target_rows:
                if len(values) > target_rows:
                    values = values[:target_rows]
                else:
                    values = values + [None] * (target_rows - len(values))
            result_df[col_name] = values
        return result_df

    @overload
    def unflatten(self, data: pa.Table) -> pa.Table: ...

    @overload
    def unflatten(self, data: pd.DataFrame) -> pd.DataFrame: ...

    def unflatten(
        self, data: Union[pa.Table, pd.DataFrame]
    ) -> Union[pa.Table, pd.DataFrame]:
        """
        Unflatten a flat table back to nested structure.

        Args:
            data: Flattened data (from SDV generation)

        Returns:
            Nested data of the same type as original input (if it was Table),
            or DataFrame with original structure preserved
        """
        if isinstance(data, (pa.Table, pd.DataFrame)):
            return self._flattener.unflatten(flat_data=data)
        raise TypeError(f"Expected pa.Table or pd.DataFrame, got {type(data)}")

    @overload
    @classmethod
    def run_pipeline(
        cls,
        synthesizer_cls: Type[BaseSingleTableSynthesizer],
        data: pa.Table,
        model_params: Optional[Dict[str, Any]] = None,
        num_rows: int = 100,
    ) -> Tuple[pa.Table, Metadata, BaseSingleTableSynthesizer]: ...

    @overload
    @classmethod
    def run_pipeline(
        cls,
        synthesizer_cls: Type[BaseSingleTableSynthesizer],
        data: pd.DataFrame,
        model_params: Optional[Dict[str, Any]] = None,
        num_rows: int = 100,
    ) -> Tuple[pd.DataFrame, Metadata, BaseSingleTableSynthesizer]: ...

    @classmethod
    def run_pipeline(
        cls,
        synthesizer_cls: Type[BaseSingleTableSynthesizer],
        data: Union[pa.Table, pd.DataFrame],
        model_params: Optional[Dict[str, Any]] = None,
        num_rows: int = 100,
    ) -> Tuple[Union[pa.Table, pd.DataFrame], Metadata, BaseSingleTableSynthesizer]:
        """
        Create and run complete pipeline end-to-end.

        Args:
            synthesizer (BaseSingleTableSynthesizer): SDV single table synthesizer instance.
            data (Union[pa.Table, pd.DataFrame]): Input data.
            model_params (Optional[Dict[str, Any]], optional): Additional params for synthesizer. Defaults to None.
            num_rows (int, optional): Number of synthetic rows to generate. Defaults to 100.

        Returns:
            Tuple[Union[pa.Table, pd.DataFrame], Metadata]: Tuple of (generated nested data, SDV metadata)
        """
        pipeline = cls(synthesizer_cls=synthesizer_cls, model_params=model_params)

        flat_data = pipeline.flatten(data)

        pipeline.fit(flat_data)
        gen_flat = pipeline.sample(num_rows)

        gen_data = pipeline.unflatten(gen_flat)
        return gen_data, pipeline.metadata, pipeline.synthesizer
