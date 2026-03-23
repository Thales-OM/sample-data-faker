"""
Unit tests for core components: SyntheticDataWorker, DataFrameFlattener, DataFrameWrapper.
"""
import pytest
import pandas as pd
import numpy as np
from concurrent.futures import Future

from src.core import SyntheticDataWorker, DataFrameFlattener, DataFrameWrapper
from src.core.exceptions import WorkerCapacityError, GenerationError
from src.sources.dummy import DummySource, DummySourceConfig
from sdv.single_table import GaussianCopulaSynthesizer, CTGANSynthesizer


@pytest.mark.unit
class TestDataFrameWrapper:
    """Tests for DataFrameWrapper class."""

    def test_init_with_dataframe(self, sample_dataframe: pd.DataFrame):
        """Test DataFrameWrapper initialization."""
        wrapper = DataFrameWrapper(df=sample_dataframe)
        assert wrapper.df is sample_dataframe
        assert len(wrapper) == len(sample_dataframe)

    def test_len_method(self, sample_dataframe: pd.DataFrame):
        """Test __len__ method."""
        wrapper = DataFrameWrapper(df=sample_dataframe)
        assert len(wrapper) == 5

    def test_df_clean_property(self):
        """Test df_clean property removes problematic columns."""
        df = pd.DataFrame({
            "col1": [1, 2, 3],
            "__type_col1": ["int", "int", "int"],  # Should be removed
            "col2": ["a", "b", "c"],
        })
        wrapper = DataFrameWrapper(df=df)
        clean_df = wrapper.df_clean
        assert "__type_col1" not in clean_df.columns
        assert "col1" in clean_df.columns
        assert "col2" in clean_df.columns

    def test_df_clean_property_no_types(self, sample_dataframe: pd.DataFrame):
        """Test df_clean when no type columns exist."""
        wrapper = DataFrameWrapper(df=sample_dataframe)
        clean_df = wrapper.df_clean
        assert list(clean_df.columns) == list(sample_dataframe.columns)


@pytest.mark.unit
class TestDataFrameFlattener:
    """Tests for DataFrameFlattener class."""

    def test_flatten_simple_dataframe(
        self, dataframe_flattener: DataFrameFlattener, sample_dataframe: pd.DataFrame
    ):
        """Test flattening a simple DataFrame without nested structures."""
        flat_df = dataframe_flattener.flatten(sample_dataframe)
        
        assert isinstance(flat_df, pd.DataFrame)
        assert len(flat_df) == len(sample_dataframe)
        assert list(flat_df.columns) == list(sample_dataframe.columns)

    def test_flatten_nested_dataframe(
        self, dataframe_flattener: DataFrameFlattener, nested_dataframe: pd.DataFrame
    ):
        """Test flattening a DataFrame with nested structures."""
        flat_df = dataframe_flattener.flatten(nested_dataframe)
        
        assert isinstance(flat_df, pd.DataFrame)
        assert len(flat_df) == len(nested_dataframe)
        # Should have flattened columns like customer[id], customer[name], etc.
        assert any("customer" in col for col in flat_df.columns)
        assert any("items" in col for col in flat_df.columns)

    def test_flatten_empty_dataframe(self, dataframe_flattener: DataFrameFlattener):
        """Test flattening an empty DataFrame."""
        empty_df = pd.DataFrame()
        flat_df = dataframe_flattener.flatten(empty_df)
        
        assert flat_df.empty
        assert dataframe_flattener._schema == {}

    def test_unflatten_after_flatten(
        self, dataframe_flattener: DataFrameFlattener, sample_dataframe: pd.DataFrame
    ):
        """Test unflattening after flattening restores original structure."""
        flat_df = dataframe_flattener.flatten(sample_dataframe)
        unflattened_df = dataframe_flattener.unflatten(flat_df)
        
        assert list(unflattened_df.columns) == list(sample_dataframe.columns)
        assert len(unflattened_df) == len(sample_dataframe)

    def test_unflatten_without_flatten_raises_error(
        self, dataframe_flattener: DataFrameFlattener, sample_dataframe: pd.DataFrame
    ):
        """Test that unflatten raises error if flatten wasn't called first."""
        with pytest.raises(ValueError, match="Call flatten\\(\\) first"):
            dataframe_flattener.unflatten(sample_dataframe)

    def test_flatten_with_null_values(
        self, dataframe_flattener: DataFrameFlattener
    ):
        """Test flattening DataFrame with null values."""
        df = pd.DataFrame({
            "id": [1, 2, 3],
            "value": [10.0, np.nan, 30.0],
            "optional": ["a", None, "c"],
        })
        flat_df = dataframe_flattener.flatten(df)
        
        assert len(flat_df) == 3
        assert "id" in flat_df.columns
        assert "value" in flat_df.columns

    def test_flatten_unflatten_nested_structures(
        self, dataframe_flattener: DataFrameFlattener, nested_dataframe: pd.DataFrame
    ):
        """Test round-trip flatten/unflatten for nested structures."""
        flat_df = dataframe_flattener.flatten(nested_dataframe)
        unflattened_df = dataframe_flattener.unflatten(flat_df)
        
        assert list(unflattened_df.columns) == list(nested_dataframe.columns)
        assert len(unflattened_df) == len(nested_dataframe)


@pytest.mark.unit
class TestSyntheticDataWorker:
    """Tests for SyntheticDataWorker class."""

    def test_init(self, synthetic_worker: SyntheticDataWorker):
        """Test worker initialization."""
        assert synthetic_worker.max_workers == 2
        assert synthetic_worker.max_pending == 3
        assert synthetic_worker.pending_count == 0
        assert synthetic_worker.available_slots == 3
        assert not synthetic_worker.is_at_capacity

    def test_submit_and_generate(
        self, synthetic_worker: SyntheticDataWorker, sample_dataframe: pd.DataFrame
    ):
        """Test submitting a generation task."""
        source = DummySource(config=DummySourceConfig(data=sample_dataframe))
        
        future = synthetic_worker.submit(
            source=source,
            output_size=10,
            synthesizer_cls=GaussianCopulaSynthesizer,
            load_limit=100,
        )
        
        result = future.result(timeout=30)
        assert isinstance(result, DataFrameWrapper)
        assert len(result) == 10

    def test_submit_at_capacity(self, sample_dataframe: pd.DataFrame):
        """Test submitting when worker is at capacity."""
        worker = SyntheticDataWorker(max_workers=1, max_pending=1)
        source = DummySource(config=DummySourceConfig(data=sample_dataframe))
        
        # Submit first task (should succeed)
        future1 = worker.submit(
            source=source,
            output_size=5,
            synthesizer_cls=GaussianCopulaSynthesizer,
        )
        
        # Worker should be at capacity now
        assert worker.is_at_capacity
        
        # Second submit should raise WorkerCapacityError
        with pytest.raises(WorkerCapacityError):
            worker.submit(
                source=source,
                output_size=5,
                synthesizer_cls=GaussianCopulaSynthesizer,
            )
        
        worker.shutdown(wait=True)

    def test_pending_count_tracking(
        self, synthetic_worker: SyntheticDataWorker, sample_dataframe: pd.DataFrame
    ):
        """Test that pending count is tracked correctly."""
        source = DummySource(config=DummySourceConfig(data=sample_dataframe))
        
        initial_count = synthetic_worker.pending_count
        
        future = synthetic_worker.submit(
            source=source,
            output_size=5,
            synthesizer_cls=GaussianCopulaSynthesizer,
        )
        
        # Count should increase during task execution
        # Note: This may be 0 if task completes very quickly
        
        future.result(timeout=30)
        
        # After completion, count should return to initial
        assert synthetic_worker.pending_count == initial_count

    def test_available_slots_property(self, synthetic_worker: SyntheticDataWorker):
        """Test available_slots property."""
        assert synthetic_worker.available_slots == synthetic_worker.max_pending
        
        # Slots decrease when tasks are submitted and increase when they complete
        # This is tested implicitly in other tests

    def test_shutdown(self, sample_dataframe: pd.DataFrame):
        """Test worker shutdown."""
        worker = SyntheticDataWorker(max_workers=2, max_pending=3)
        source = DummySource(config=DummySourceConfig(data=sample_dataframe))
        
        # Submit a task
        future = worker.submit(
            source=source,
            output_size=5,
            synthesizer_cls=GaussianCopulaSynthesizer,
        )
        
        # Shutdown should complete
        worker.shutdown(wait=True)
        
        # Task should still complete
        result = future.result(timeout=30)
        assert isinstance(result, DataFrameWrapper)

    def test_generation_with_empty_source(self, synthetic_worker: SyntheticDataWorker):
        """Test that empty source raises GenerationError."""
        empty_df = pd.DataFrame()
        source = DummySource(config=DummySourceConfig(data=empty_df))
        
        with pytest.raises(GenerationError, match="No valid records loaded"):
            future = synthetic_worker.submit(
                source=source,
                output_size=10,
                synthesizer_cls=GaussianCopulaSynthesizer,
            )
            future.result(timeout=30)

    def test_generation_with_ctgan(
        self, synthetic_worker: SyntheticDataWorker, sample_dataframe: pd.DataFrame
    ):
        """Test generation with CTGAN synthesizer."""
        source = DummySource(config=DummySourceConfig(data=sample_dataframe))
        
        future = synthetic_worker.submit(
            source=source,
            output_size=10,
            synthesizer_cls=CTGANSynthesizer,
            load_limit=100,
            model_params={"epochs": 1},  # Fast training for tests
        )
        
        result = future.result(timeout=60)
        assert isinstance(result, DataFrameWrapper)
        assert len(result) == 10

    def test_model_params_passed(
        self, synthetic_worker: SyntheticDataWorker, sample_dataframe: pd.DataFrame
    ):
        """Test that model parameters are passed correctly."""
        source = DummySource(config=DummySourceConfig(data=sample_dataframe))
        
        future = synthetic_worker.submit(
            source=source,
            output_size=10,
            synthesizer_cls=GaussianCopulaSynthesizer,
            model_params={"default_distribution": "norm"},
        )
        
        result = future.result(timeout=30)
        assert isinstance(result, DataFrameWrapper)
        assert len(result) == 10
