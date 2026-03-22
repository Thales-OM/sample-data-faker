"""
Tests for utility modules: exceptions, utils, metrics.
"""
import pytest
import torch

from src.core.exceptions import WorkerCapacityError, GenerationError
from src.utils import openmetadata_to_dto_table
from src.metrics.collector import SystemMetricsCollector


@pytest.mark.unit
class TestExceptions:
    """Tests for custom exceptions."""

    def test_worker_capacity_error(self):
        """Test WorkerCapacityError with pending info."""
        error = WorkerCapacityError(
            "Worker at capacity",
            pending=5,
            max_pending=5,
        )
        
        assert str(error) == "Worker at capacity"
        assert error.pending == 5
        assert error.max_pending == 5

    def test_worker_capacity_error_defaults(self):
        """Test WorkerCapacityError default values."""
        error = WorkerCapacityError("Error message")
        
        assert error.pending == 0
        assert error.max_pending == 0

    def test_generation_error(self):
        """Test GenerationError with original exception."""
        original = ValueError("Original error")
        error = GenerationError(
            "Synthetic generation failed",
            cause=original,
        )
        
        assert str(error) == "Synthetic generation failed"
        assert error.cause is original
        assert error.__cause__ is original

    def test_generation_error_without_original(self):
        """Test GenerationError without original exception."""
        error = GenerationError("Error message")
        
        assert str(error) == "Error message"
        assert error.cause is None


@pytest.mark.unit
class TestOpenMetadataUtils:
    """Tests for OpenMetadata utility functions."""

    def test_openmetadata_to_dto_table(self):
        """Test converting OpenMetadata FQN to DTO table format."""
        om_fqn = "contracts.Sources.assembly.assembled"
        dto_table = openmetadata_to_dto_table(
            table_fqn=om_fqn,
            trino_catalog="dto_iceberg",
        )
        
        assert dto_table == "dto_iceberg.assembly.assembled"

    def test_openmetadata_to_dto_table_with_underscore(self):
        """Test conversion handles underscore to hyphen in schema."""
        om_fqn = "contracts.Sources.pos_transaction_v2.pos_transaction_v2"
        dto_table = openmetadata_to_dto_table(
            table_fqn=om_fqn,
            trino_catalog="dto_iceberg",
        )
        
        # Should convert back to underscore for Trino
        assert "pos_transaction_v_2" in dto_table


@pytest.mark.unit
class TestSystemMetricsCollector:
    """Tests for SystemMetricsCollector."""

    def test_init(self):
        """Test SystemMetricsCollector initialization."""
        from prometheus_client import CollectorRegistry
        
        collector = SystemMetricsCollector()
        assert collector.process_cpu_percent is not None
        assert collector.process_memory_bytes is not None
        assert collector.system_cpu_percent is not None
        assert collector.system_memory_percent is not None
        assert collector.disk_usage_percent is not None

    def test_init_with_custom_registry(self):
        """Test initialization with custom registry."""
        from prometheus_client import CollectorRegistry
        
        registry = CollectorRegistry()
        collector = SystemMetricsCollector(registry=registry)
        
        assert collector.registry == registry

    def test_collect_cpu(self):
        """Test collecting CPU metrics."""
        collector = SystemMetricsCollector()
        collector.collect()
        
        # CPU metric should be set
        assert collector.process_cpu_percent._value.get() >= 0

    def test_collect_memory(self):
        """Test collecting memory metrics."""
        collector = SystemMetricsCollector()
        collector.collect()
        
        # Memory metrics should be set
        assert collector.process_memory_bytes._value.get() >= 0
        assert collector.system_memory_available_bytes._value.get() > 0

    def test_collect_disk(self):
        """Test collecting disk metrics."""
        collector = SystemMetricsCollector()
        collector.collect()
        
        # Disk metrics should be set
        assert collector.disk_usage_percent._value.get() >= 0
        assert collector.disk_free_bytes._value.get() > 0

    def test_collect_multiple_times(self):
        """Test that collect can be called multiple times."""
        collector = SystemMetricsCollector()
        
        collector.collect()
        first_cpu = collector.process_cpu_percent._value.get()
        
        collector.collect()
        second_cpu = collector.process_cpu_percent._value.get()
        
        # Both should be valid values
        assert first_cpu >= 0
        assert second_cpu >= 0


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA not available")
@pytest.mark.unit
class TestCudaMetrics:
    """Tests for CUDA-specific metrics (only run if CUDA available)."""

    def test_cuda_available(self):
        """Test that CUDA is available."""
        assert torch.cuda.is_available()
        assert torch.cuda.device_count() > 0
