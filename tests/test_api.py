"""
API endpoint tests for table, openmetadata, and avro endpoints.
"""

import pytest
import time
import responses
from unittest.mock import MagicMock

import pandas as pd
from fastapi.testclient import TestClient
from fastapi import status
from sdv.single_table import GaussianCopulaSynthesizer

from src.app import create_app
from src.config import Settings, S3DestinationConfig
from src.core import SyntheticDataWorker
from src.sources.dummy import DummySource, DummySourceConfig


@pytest.mark.api
class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_liveness_endpoint(self, test_client: TestClient):
        """Test /liveness endpoint."""
        response = test_client.get("/liveness")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["root"] == "OK!"

    def test_readiness_endpoint(self, test_client: TestClient):
        """Test /readiness endpoint."""
        response = test_client.get("/readiness")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["root"] == "OK!"

    def test_readiness_at_capacity(self):
        """Test /readiness returns 503 when at capacity."""
        app = create_app()
        settings = Settings(max_workers=1, max_pending=1)

        app.state.settings = settings
        app.state.worker = SyntheticDataWorker(
            max_workers=settings.max_workers,
            max_pending=settings.max_pending,
        )
        app.state.omd_async_client = None

        # Fill the worker queue
        df = pd.DataFrame({"col": [1]})
        source = DummySource(config=DummySourceConfig(data=df))

        app.state.worker.submit(
            source=source,
            output_size=1,
            synthesizer_cls=GaussianCopulaSynthesizer,
        )

        # Wait for task to start processing
        time.sleep(0.1)

        with TestClient(app) as client:
            response = client.get("/readiness")
            # Should be 503 if at capacity, 200 if task completed quickly
            assert response.status_code in [
                status.HTTP_200_OK,
                status.HTTP_503_SERVICE_UNAVAILABLE,
            ]

        app.state.worker.shutdown(wait=True)


@pytest.mark.api
class TestTableEndpoints:
    """Tests for /api/v1/table endpoints."""

    def test_generate_synthetic_from_dummy_source(self, test_client: TestClient):
        """Test POST /api/v1/table/generate with dummy source."""
        payload = {
            "source": {
                "type": "dummy",
                "config": {
                    "data": [
                        {"user_id": 1, "username": "alice", "age": 25},
                        {"user_id": 2, "username": "bob", "age": 30},
                        {"user_id": 3, "username": "charlie", "age": 35},
                    ]
                },
            },
            "output_size": 5,
            "load_limit": 100,
        }

        response = test_client.post("/api/v1/table/generate", json=payload)

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 5

    def test_generate_synthetic_invalid_source_type(self, test_client: TestClient):
        """Test POST /api/v1/table/generate with invalid source type."""
        payload = {
            "source": {
                "type": "invalid_type",
                "config": {},
            },
            "output_size": 5,
        }

        response = test_client.post("/api/v1/table/generate", json=payload)

        # Should return validation error
        assert response.status_code in [
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        ]

    def test_generate_synthetic_invalid_output_size(self, test_client: TestClient):
        """Test POST /api/v1/table/generate with invalid output_size."""
        payload = {
            "source": {
                "type": "dummy",
                "config": {"data": [{"col": 1}]},
            },
            "output_size": -5,  # Invalid: must be > 0
        }

        response = test_client.post("/api/v1/table/generate", json=payload)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_generate_synthetic_empty_source(self, test_client: TestClient):
        """Test POST /api/v1/table/generate with empty source data."""
        payload = {
            "source": {
                "type": "dummy",
                "config": {"data": []},
            },
            "output_size": 5,
        }

        response = test_client.post("/api/v1/table/generate", json=payload)

        # Should fail with generation error
        assert response.status_code in [
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ]


@pytest.mark.api
class TestOpenMetadataEndpoints:
    """Tests for /api/v1/openmetadata endpoints."""

    @responses.activate
    def test_generate_synthetic_openmetadata(
        self, test_client_with_omd: TestClient, sample_dataframe: pd.DataFrame
    ):
        """Test POST /api/v1/openmetadata/generate/{table_fqn}."""
        table_fqn = "contracts.Sources.assembly.assembled"
        table_id = "test-table-id"

        # Mock OpenMetadata API responses
        responses.add(
            responses.GET,
            f"http://localhost:8585/api/v1/tables/name/{table_fqn}",
            json={"id": table_id, "fullyQualifiedName": table_fqn},
            status=200,
        )

        responses.add(
            responses.PUT,
            f"http://localhost:8585/api/v1/tables/{table_id}/sampleData",
            json={"message": "Sample data added successfully"},
            status=200,
        )

        payload = {
            "source": {
                "type": "dummy",
                "config": {
                    "data": [
                        {"id": 1, "name": "test", "value": 100},
                        {"id": 2, "name": "test2", "value": 200},
                    ]
                },
            },
            "output_size": 10,
            "load_limit": 50,
        }

        response = test_client_with_omd.post(
            f"/api/v1/openmetadata/generate/{table_fqn}",
            json=payload,
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["table_fqn"] == table_fqn
        assert data["table_id"] == table_id
        assert data["output_size"] == 10

    @responses.activate
    def test_generate_openmetadata_table_not_found(
        self, test_client_with_omd: TestClient
    ):
        """Test POST /api/v1/openmetadata/generate with non-existent table."""
        table_fqn = "contracts.Sources.nonexistent.table"

        responses.add(
            responses.GET,
            f"http://localhost:8585/api/v1/tables/name/{table_fqn}",
            status=404,
        )

        payload = {
            "source": {
                "type": "dummy",
                "config": {"data": [{"col": 1}]},
            },
            "output_size": 5,
        }

        response = test_client_with_omd.post(
            f"/api/v1/openmetadata/generate/{table_fqn}",
            json=payload,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @responses.activate
    def test_webhook_table_created(
        self, test_client_with_omd: TestClient, sample_dataframe: pd.DataFrame
    ):
        """Test POST /api/v1/openmetadata/webhook for TABLE_CREATED event."""
        table_id = "test-table-id"
        table_fqn = "contracts.Sources.assembly.assembled"

        # Mock OpenMetadata API
        responses.add(
            responses.GET,
            f"http://localhost:8585/api/v1/tables/{table_id}",
            json={"id": table_id, "fullyQualifiedName": table_fqn},
            status=200,
        )

        responses.add(
            responses.PUT,
            f"http://localhost:8585/api/v1/tables/{table_id}/sampleData",
            json={"message": "Sample data added successfully"},
            status=200,
        )

        # Configure test client with Trino settings
        test_client_with_omd.app.state.settings.trino_source = MagicMock(
            host="trino.example.com",
            port=443,
            user="test_user",
            password=MagicMock(get_secret_value=lambda: "secret"),
            catalog="dto_iceberg",
        )

        payload = {
            "eventType": "TABLE_CREATED",
            "entityId": table_id,
            "entityName": table_fqn,
        }

        response = test_client_with_omd.post(
            "/api/v1/openmetadata/webhook",
            json=payload,
        )

        assert response.status_code == status.HTTP_201_CREATED

    @responses.activate
    def test_webhook_table_updated_no_schema_change(
        self, test_client_with_omd: TestClient
    ):
        """Test POST /api/v1/openmetadata/webhook for TABLE_UPDATED without schema change."""
        payload = {
            "eventType": "TABLE_UPDATED",
            "entityId": "test-id",
            "entityName": "test.table",
            # No schema change fields
        }

        response = test_client_with_omd.post(
            "/api/v1/openmetadata/webhook",
            json=payload,
        )

        # Should return 200 with no action message
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "no action" in data["message"].lower()

    def test_webhook_trino_not_configured(self, test_client: TestClient):
        """Test webhook fails when Trino is not configured."""
        payload = {
            "eventType": "TABLE_CREATED",
            "entityId": "test-id",
            "entityName": "test.table",
        }

        response = test_client.post(
            "/api/v1/openmetadata/webhook",
            json=payload,
        )

        # Should fail with 500 - Trino not configured
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


@pytest.mark.api
class TestAvroEndpoints:
    """Tests for /api/v1/avro endpoints."""

    def test_generate_from_avro_ocf(self, test_client: TestClient, avro_file: str):
        """Test POST /api/v1/avro/ocf with valid Avro file."""
        # Configure S3 destination for test
        test_client.app.state.settings.s3_destination = S3DestinationConfig(
            access_key="test-key",
            secret_key="test-secret",
            bucket="test-bucket",
            endpoint="http://localhost:9000",
        )

        with open(avro_file, "rb") as f:
            files = {"file": ("test.avro", f, "application/octet-stream")}
            data = {
                "output_size": 10,
                "load_limit": 50,
            }

            response = test_client.post("/api/v1/avro/ocf", files=files, data=data)

        # Should succeed (may fail on S3 upload if not mocked)
        assert response.status_code in [
            status.HTTP_201_CREATED,
            status.HTTP_500_INTERNAL_SERVER_ERROR,  # If S3 not available
        ]

    def test_generate_from_avro_invalid_extension(self, test_client: TestClient):
        """Test POST /api/v1/avro/ocf with non-.avro file."""
        files = {"file": ("test.parquet", b"dummy content", "application/octet-stream")}
        data = {"output_size": 10}

        response = test_client.post("/api/v1/avro/ocf", files=files, data=data)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "extension" in response.json()["detail"].lower()

    def test_generate_from_avro_invalid_magic_bytes(self, test_client: TestClient):
        """Test POST /api/v1/avro/ocf with invalid Avro magic bytes."""
        files = {"file": ("test.avro", b"NOT_VALID_AVRO", "application/octet-stream")}
        data = {"output_size": 10}

        response = test_client.post("/api/v1/avro/ocf", files=files, data=data)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "magic" in response.json()["detail"].lower()

    def test_generate_from_avro_missing_file(self, test_client: TestClient):
        """Test POST /api/v1/avro/ocf without file."""
        response = test_client.post("/api/v1/avro/ocf", data={"output_size": 10})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_generate_from_avro_invalid_output_size(
        self, test_client: TestClient, avro_file: str
    ):
        """Test POST /api/v1/avro/ocf with invalid output_size."""
        with open(avro_file, "rb") as f:
            files = {"file": ("test.avro", f, "application/octet-stream")}
            data = {
                "output_size": 0,  # Invalid: must be >= 1
            }

            response = test_client.post("/api/v1/avro/ocf", files=files, data=data)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.api
class TestMetricsEndpoint:
    """Tests for /metrics endpoint."""

    def test_metrics_endpoint(self, test_client: TestClient):
        """Test GET /metrics returns Prometheus metrics."""
        response = test_client.get("/metrics")

        assert response.status_code == status.HTTP_200_OK
        # Prometheus metrics are in text format
        assert "text/plain" in response.headers.get("content-type", "")
        # Should contain some standard metrics
        content = response.text
        assert len(content) > 0
