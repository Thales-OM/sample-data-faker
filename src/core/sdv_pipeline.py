import pyarrow as pa
from typing import Dict, Optional, Any, Tuple, Union
from sdv.metadata import Metadata
from sdv.single_table import (
    CTGANSynthesizer,
    GaussianCopulaSynthesizer,
)
from src.core.flatten import DataFrameFlattener
from src.logger import LoggerFactory


logger = LoggerFactory.getLogger(__name__)


class SDVPipeline:
    """
    Complete pipeline for generating synthetic data using SDV.

    Handles the full lifecycle:
    - Input: Nested PyArrow Table (from Avro or other sources)
    - Flatten for SDV consumption
    - Create metadata for SDV
    - Fit synthesizer
    - Generate synthetic flat data
    - Unflatten back to nested PyArrow Table
    """

    def __init__(
        self,
        synthesizer_class: Union[
            type[GaussianCopulaSynthesizer], type[CTGANSynthesizer]
        ],
        enforce_min_max_values: bool = True,
    ):
        """
        Initialize the SDV pipeline.

        Args:
            synthesizer_class (Union[type[GaussianCopulaSynthesizer], type[CTGANSynthesizer]]): SDV synthesizer class.
            enforce_min_max_values (bool, optional): Whether to enforce minimum/maximum values for numerical fields. Defaults to True.
        """
        self.synthesizer_class = synthesizer_class
        self.enforce_min_max_values = enforce_min_max_values

        self._flattener = DataFrameFlattener()
        self._metadata: Optional[Metadata] = None
        self._synthesizer: Optional[
            Union[GaussianCopulaSynthesizer, CTGANSynthesizer]
        ] = None
        self._array_metadata: Dict[str, Dict[str, Any]] = {}

    @property
    def metadata(self) -> Optional[Metadata]:
        return self._metadata

    def flatten(self, table: pa.Table) -> pa.Table:
        """
        Flatten a nested PyArrow Table for SDV consumption.

        Args:
            table: Input PyArrow Table with nested structures

        Returns:
            Flattened PyArrow Table
        """
        flat_table = self._flattener.flatten(data=table)

        self._array_metadata = self._extract_array_metadata(flat_table)

        return flat_table

    def _extract_array_metadata(
        self,
        flat_table: pa.Table,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Extract metadata about array columns from flat table.

        This helps us understand how to reconstruct arrays
        during unflatten.

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

    def create_metadata(
        self,
        flat_table: pa.Table,
    ) -> Metadata:
        """
        Create SDV Metadata from flat PyArrow Table.

        Args:
            flat_table: Flattened PyArrow Table

        Returns:
            SDV Metadata object
        """
        df = flat_table.to_pandas()
        self._metadata = Metadata().detect_from_dataframe(df)
        return self._metadata

    def fit(self, flat_table: pa.Table) -> None:
        """
        Fit an SDV synthesizer on the flat data.

        Args:
            flat_table: Flattened PyArrow Table

        Returns:
            self for chaining
        """

        df = flat_table.to_pandas()

        if self._metadata is None:
            self.create_metadata(flat_table)

        self._synthesizer = self.synthesizer_class(
            metadata=self._metadata, enforce_min_max_values=self.enforce_min_max_values
        )

        self._synthesizer.fit(df)

    def sample(
        self,
        num_rows: int,
    ) -> pa.Table:
        """
        Sample synthetic datapoints (rows) from fitted synthesizer.

        Args:
            num_rows (int): Number of rows to generate.

        Raises:
            RuntimeError: Calling sample() before calling fit().

        Returns:
            pa.Table: Flattened PyArrow Table with generated data.
        """
        if self._synthesizer is None:
            raise RuntimeError("Pipeline not fitted. Call fit() first.")

        synth_df = self._synthesizer.sample(num_rows=num_rows)

        return pa.Table.from_pandas(synth_df)

    def unflatten(
        self,
        flat_table: pa.Table,
    ) -> pa.Table:
        """
        Unflatten a flat table back to nested structure.

        Args:
            flat_table: Flattened PyArrow Table (from SDV generation)

        Returns:
            Nested PyArrow Table with original schema
        """
        max_num_rows = flat_table.num_rows

        if self._array_metadata:
            flat_table = self._adjust_array_lengths(
                flat_table,
                self._array_metadata,
                max_num_rows,
            )

        return self._flattener.unflatten(flat_data=flat_table)

    def _adjust_array_lengths(
        self,
        flat_table: pa.Table,
        array_metadata: Dict[str, Dict[str, Any]],
        target_rows: int,
    ) -> pa.Table:
        """
        Adjust array columns to match expected lengths.

        SDV generates arrays that may have different patterns than
        the original. This adjusts them to create valid lists.

        Args:
            flat_table: Flat table with potentially mismatched array lengths
            array_metadata: Metadata about array columns
            target_rows: Target number of rows

        Returns:
            Adjusted flat table
        """
        result_data = {}

        for col_name in flat_table.column_names:
            col = flat_table.column(col_name)
            values = col.to_pylist()

            if len(values) != target_rows:
                values = values[:target_rows]
                if len(values) < target_rows:
                    values.extend([None] * (target_rows - len(values)))

            result_data[col_name] = values

        return pa.Table.from_pydict(result_data)

    def pipeline(
        self,
        table: pa.Table,
        num_rows: int = 100,
    ) -> Tuple[pa.Table, Metadata]:
        """
        Run the complete pipeline end-to-end.

        Args:
            table (pa.Table): Input PyArrow Table
            num_rows (int, optional): Number of synthetic rows to generate. Defaults to 100.

        Returns:
            Tuple[pa.Table, Metadata]: Tuple of (generated nested table, SDV metadata)
        """
        flat_table = self.flatten(table)
        self.create_metadata(flat_table)

        self.fit(flat_table)
        gen_flat = self.sample(num_rows)

        gen_table = self.unflatten(gen_flat)
        return gen_table, self._metadata
