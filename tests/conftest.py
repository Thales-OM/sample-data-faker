"""
Pytest fixtures and configuration for sample-data-faker tests.
"""

import os
import tempfile
from typing import Generator, Any
from pathlib import Path

import pandas as pd
import pytest
import fastavro
from moto import mock_aws
from fastapi.testclient import TestClient

from src.app import create_app
from src.config import (
    Settings,
    S3DestinationConfig,
    OMDConfig,
)
from src.sources.s3 import S3SourceConfig
from src.core import SyntheticDataWorker, DataFrameWrapper
from src.core.flatten import DataFrameFlattener

# ============================================================================
# Pytest Configuration
# ============================================================================


@pytest.fixture(scope="session", autouse=True)
def set_test_env():
    """Set test environment variables."""
    os.environ.setdefault("PYTHONPATH", str(Path(__file__).parent.parent))
    yield


# ============================================================================
# S3 Mock Fixtures (using moto)
# ============================================================================


@pytest.fixture
def mock_s3_client():
    """Provide a mocked S3 client using moto."""
    with mock_aws():
        import boto3

        client = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="test-access-key",
            aws_secret_access_key="test-secret-key",
        )
        yield client


@pytest.fixture
def s3_bucket(mock_s3_client) -> Generator[str, Any, Any]:
    """Create a test S3 bucket."""
    bucket_name = "test-dto-sample-data"
    mock_s3_client.create_bucket(Bucket=bucket_name)
    yield bucket_name


@pytest.fixture
def s3_source_config(s3_bucket: str) -> S3SourceConfig:
    """Create S3 source config for tests."""
    return S3SourceConfig(
        path=f"s3://{s3_bucket}/test-data.parquet",
        access_key="test-access-key",
        secret_key="test-secret-key",
        region="us-east-1",
    )


@pytest.fixture
def s3_destination_config(s3_bucket: str) -> S3DestinationConfig:
    """Create S3 destination config for tests."""
    return S3DestinationConfig(
        endpoint="http://localhost:9000",
        access_key="test-access-key",
        secret_key="test-secret-key",
        region="us-east-1",
        bucket=s3_bucket,
    )


# ============================================================================
# Test Data Fixtures
# ============================================================================


@pytest.fixture
def sample_dataframe() -> pd.DataFrame:
    """Create a sample DataFrame for testing."""
    return pd.DataFrame(
        {
            "user_id": [1, 2, 3, 4, 5],
            "username": ["alice", "bob", "charlie", "david", "eve"],
            "email": [
                "alice@example.com",
                "bob@example.com",
                "charlie@example.com",
                "david@example.com",
                "eve@example.com",
            ],
            "age": [25, 30, 35, 40, 45],
            "is_active": [True, True, False, True, False],
            "balance": [100.50, 200.75, 300.00, 400.25, 500.50],
        }
    )


@pytest.fixture
def nested_dataframe() -> pd.DataFrame:
    """Create a DataFrame with nested/complex structures."""
    return pd.DataFrame(
        {
            "order_id": [1001, 1002],
            "customer": [
                {"id": 101, "name": "John Doe", "tags": ["premium", "vip"]},
                {"id": 102, "name": "Jane Smith", "tags": ["standard"]},
            ],
            "items": [
                [
                    {"product_id": "P-123", "quantity": 2, "price": 29.99},
                    {"product_id": "P-456", "quantity": 1, "price": 99.99},
                ],
                [
                    {"product_id": "P-789", "quantity": 3, "price": 15.00},
                ],
            ],
            "shipping_address": [
                {"street": "123 Main St", "city": "Boston", "zip_code": "02108"},
                {"street": "456 Oak Ave", "city": "Seattle", "zip_code": "98101"},
            ],
        }
    )


@pytest.fixture
def avro_schema() -> dict:
    """Avro schema for test files."""
    return {
        "type": "record",
        "name": "test.User",
        "fields": [
            {"name": "user_id", "type": "int"},
            {"name": "username", "type": "string"},
            {"name": "email", "type": ["null", "string"], "default": None},
            {"name": "age", "type": ["null", "int"], "default": None},
            {"name": "is_active", "type": "boolean"},
            {"name": "balance", "type": "double"},
        ],
    }


@pytest.fixture
def avro_file(avro_schema: dict) -> Generator[str, None, None]:
    """Create a temporary Avro OCF file for testing."""
    records = [
        {
            "user_id": 1,
            "username": "alice",
            "email": "alice@example.com",
            "age": 28,
            "is_active": True,
            "balance": 1234.56,
        },
        {
            "user_id": 2,
            "username": "bob",
            "email": "bob@example.com",
            "age": 34,
            "is_active": True,
            "balance": 7890.12,
        },
        {
            "user_id": 3,
            "username": "charlie",
            "email": None,
            "age": None,
            "is_active": False,
            "balance": 0.0,
        },
    ]

    with tempfile.NamedTemporaryFile(suffix=".avro", delete=False) as f:
        fastavro.writer(f, avro_schema, records)
        temp_path = f.name

    yield temp_path
    os.unlink(temp_path)


@pytest.fixture
def parquet_file(sample_dataframe: pd.DataFrame) -> Generator[str, None, None]:
    """Create a temporary Parquet file for testing."""
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        sample_dataframe.to_parquet(f.name)
        temp_path = f.name

    yield temp_path
    os.unlink(temp_path)


# ============================================================================
# Application Fixtures
# ============================================================================


@pytest.fixture
def test_settings() -> Settings:
    """Create test settings."""
    return Settings(
        max_workers=2,
        max_pending=3,
        cleanup_on_complete=True,
    )


@pytest.fixture
def test_client(test_settings: Settings) -> Generator[TestClient, None, None]:
    """Create a test client with test settings."""
    app = create_app()

    # Override state with test settings
    app.state.settings = test_settings
    app.state.worker = SyntheticDataWorker(
        max_workers=test_settings.max_workers,
        max_pending=test_settings.max_pending,
    )
    app.state.omd_async_client = None

    with TestClient(app) as client:
        yield client


@pytest.fixture
def test_client_with_omd(test_settings: Settings) -> Generator[TestClient, None, None]:
    """Create a test client with OpenMetadata settings."""
    app = create_app()

    # Configure with mock OpenMetadata settings
    test_settings.openmetadata_destination = OMDConfig(
        api_url="http://localhost:8585/api",
        token="test-token-for-openmetadata",
        api_version="v1",
    )

    app.state.settings = test_settings
    app.state.worker = SyntheticDataWorker(
        max_workers=test_settings.max_workers,
        max_pending=test_settings.max_pending,
    )

    with TestClient(app) as client:
        yield client


# ============================================================================
# Core Component Fixtures
# ============================================================================


@pytest.fixture
def synthetic_worker() -> Generator[SyntheticDataWorker, None, None]:
    """Create a SyntheticDataWorker instance."""
    worker = SyntheticDataWorker(max_workers=2, max_pending=3)
    yield worker
    worker.shutdown(wait=True)


@pytest.fixture
def dataframe_flattener() -> DataFrameFlattener:
    """Create a DataFrameFlattener instance."""
    return DataFrameFlattener()


@pytest.fixture
def dataframe_wrapper(sample_dataframe: pd.DataFrame) -> DataFrameWrapper:
    """Create a DataFrameWrapper instance."""
    return DataFrameWrapper(df=sample_dataframe)


# ============================================================================
# OpenMetadata Mock Fixtures
# ============================================================================


@pytest.fixture
def mock_omd_responses():
    """Mock OpenMetadata API responses."""
    import responses

    with responses.RequestsMock() as rsps:
        # Mock table lookup
        rsps.add(
            responses.GET,
            "http://localhost:8585/api/v1/tables/name/contracts.Sources.assembly.assembled",
            json={
                "id": "test-table-id",
                "fullyQualifiedName": "contracts.Sources.assembly.assembled",
            },
            status=200,
        )

        # Mock add sample data
        rsps.add(
            responses.PUT,
            "http://localhost:8585/api/v1/tables/test-table-id/sampleData",
            json={"message": "Sample data added successfully"},
            status=200,
        )

        yield rsps
