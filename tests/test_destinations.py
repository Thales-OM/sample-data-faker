"""
Tests for destinations: OpenMetadata client and S3 writer.
"""
import pytest
import responses
import pandas as pd

from src.destinations.openmetadata import AsyncOMDClient
from src.destinations.s3 import S3Destination
from src.config import OMDConfig, S3DestinationConfig
from src.openmetadata import SampleData


@pytest.mark.unit
class TestAsyncOMDClient:
    """Tests for AsyncOMDClient."""

    def test_init_with_dict_config(self):
        """Test initialization with dict config."""
        config = {
            "api_url": "https://om.example.com",
            "token": "test-token-12345",
            "api_version": "v1",
        }
        client = AsyncOMDClient(config=config)
        
        assert client.config.api_url is not None
        assert client._base_url == "https://om.example.com/api/v1"

    def test_init_with_omd_config(self):
        """Test initialization with OMDConfig object."""
        config = OMDConfig(
            api_url="https://om.example.com",
            token="test-token-12345",
        )
        client = AsyncOMDClient(config=config)
        
        assert client.config == config

    @pytest.mark.asyncio
    async def test_get_success(self):
        """Test successful GET request."""
        config = OMDConfig(
            api_url="https://om.example.com",
            token="test-token-12345",
        )
        
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://om.example.com/api/v1/tables",
                json={"tables": []},
                status=200,
            )
            
            async with AsyncOMDClient(config=config) as client:
                result = await client.get("/tables")
                assert result == {"tables": []}

    @pytest.mark.asyncio
    async def test_get_nullable_404(self):
        """Test GET with nullable=True returns None on 404."""
        config = OMDConfig(
            api_url="https://om.example.com",
            token="test-token-12345",
        )
        
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://om.example.com/api/v1/tables/nonexistent",
                status=404,
            )
            
            async with AsyncOMDClient(config=config) as client:
                result = await client.get("/tables/nonexistent", nullable=True)
                assert result is None

    @pytest.mark.asyncio
    async def test_get_table_by_name(self):
        """Test get_table_by_name method."""
        config = OMDConfig(
            api_url="https://om.example.com",
            token="test-token-12345",
        )
        
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://om.example.com/api/v1/tables/name/test.table",
                json={"id": "test-id", "fullyQualifiedName": "test.table"},
                status=200,
            )
            
            async with AsyncOMDClient(config=config) as client:
                result = await client.get_table_by_name("test.table")
                assert result["id"] == "test-id"

    @pytest.mark.asyncio
    async def test_get_table_by_id(self):
        """Test get_table_by_id method."""
        config = OMDConfig(
            api_url="https://om.example.com",
            token="test-token-12345",
        )
        
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://om.example.com/api/v1/tables/test-id",
                json={"id": "test-id", "name": "test"},
                status=200,
            )
            
            async with AsyncOMDClient(config=config) as client:
                result = await client.get_table_by_id("test-id")
                assert result["id"] == "test-id"

    @pytest.mark.asyncio
    async def test_post_success(self):
        """Test successful POST request."""
        config = OMDConfig(
            api_url="https://om.example.com",
            token="test-token-12345",
        )
        
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST,
                "https://om.example.com/api/v1/tables",
                json={"id": "new-id"},
                status=201,
            )
            
            async with AsyncOMDClient(config=config) as client:
                result = await client.post("/tables", json={"name": "test"})
                assert result["id"] == "new-id"

    @pytest.mark.asyncio
    async def test_put_success(self):
        """Test successful PUT request."""
        config = OMDConfig(
            api_url="https://om.example.com",
            token="test-token-12345",
        )
        
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.PUT,
                "https://om.example.com/api/v1/tables/test-id",
                json={"id": "test-id", "updated": True},
                status=200,
            )
            
            async with AsyncOMDClient(config=config) as client:
                result = await client.put("/tables/test-id", json={"name": "updated"})
                assert result["updated"] is True

    @pytest.mark.asyncio
    async def test_add_sample_data(self, sample_dataframe: pd.DataFrame):
        """Test add_sample_data method."""
        config = OMDConfig(
            api_url="https://om.example.com",
            token="test-token-12345",
        )
        
        sample_data = SampleData.from_dataframe(df=sample_dataframe)
        
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.PUT,
                "https://om.example.com/api/v1/tables/test-id/sampleData",
                json={"message": "Sample data added"},
                status=200,
            )
            
            async with AsyncOMDClient(config=config) as client:
                result = await client.add_sample_data(id="test-id", body=sample_data)
                assert "message" in result

    @pytest.mark.asyncio
    async def test_delete_success(self):
        """Test successful DELETE request."""
        config = OMDConfig(
            api_url="https://om.example.com",
            token="test-token-12345",
        )
        
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.DELETE,
                "https://om.example.com/api/v1/tables/test-id",
                status=204,
            )
            
            async with AsyncOMDClient(config=config) as client:
                result = await client.delete("/tables/test-id")
                assert result is True

    @pytest.mark.asyncio
    async def test_is_healthy_success(self):
        """Test is_healthy returns True when connection works."""
        config = OMDConfig(
            api_url="https://om.example.com",
            token="test-token-12345",
        )
        
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://om.example.com/api/v1/tables",
                json={"tables": []},
                status=200,
            )
            
            async with AsyncOMDClient(config=config) as client:
                healthy, error = await client.is_healthy()
                assert healthy is True
                assert error is None

    @pytest.mark.asyncio
    async def test_is_healthy_failure(self):
        """Test is_healthy returns False when connection fails."""
        config = OMDConfig(
            api_url="https://om.example.com",
            token="test-token-12345",
        )
        
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://om.example.com/api/v1/tables",
                status=500,
            )
            
            async with AsyncOMDClient(config=config) as client:
                healthy, error = await client.is_healthy()
                assert healthy is False
                assert error is not None

    def test_build_url(self):
        """Test _build_url method handles various endpoint formats."""
        config = OMDConfig(
            api_url="https://om.example.com",
            token="test-token-12345",
        )
        client = AsyncOMDClient(config=config)
        
        assert client._build_url("/tables") == "https://om.example.com/api/v1/tables"
        assert client._build_url("tables") == "https://om.example.com/api/v1/tables"
        assert client._build_url("/tables/") == "https://om.example.com/api/v1/tables/"


@pytest.mark.unit
class TestSampleData:
    """Tests for SampleData model."""

    def test_from_dataframe(self, sample_dataframe: pd.DataFrame):
        """Test creating SampleData from DataFrame."""
        sample_data = SampleData.from_dataframe(df=sample_dataframe)
        
        assert sample_data.tableData is not None
        assert len(sample_data.tableData) == len(sample_dataframe)

    def test_from_dataframe_with_nulls(self):
        """Test creating SampleData from DataFrame with null values."""
        df = pd.DataFrame({
            "id": [1, 2, None],
            "name": ["alice", None, "charlie"],
            "value": [10.0, 20.0, None],
        })
        
        sample_data = SampleData.from_dataframe(df=df)
        
        assert sample_data.tableData is not None
        assert len(sample_data.tableData) == 3

    def test_from_dataframe_empty(self):
        """Test creating SampleData from empty DataFrame."""
        df = pd.DataFrame()
        
        sample_data = SampleData.from_dataframe(df=df)
        
        assert sample_data.tableData == []


@pytest.mark.unit
class TestS3Writer:
    """Tests for S3Writer."""

    def test_init(self, s3_destination_config: S3DestinationConfig):
        """Test S3Writer initialization."""
        writer = S3Destination(config=s3_destination_config)
        assert writer._config == s3_destination_config

    @pytest.mark.asyncio
    async def test_prepare_csv(self, sample_dataframe: pd.DataFrame):
        """Test _prepare_csv static method."""
        filename, data = S3Destination._prepare_csv(
            filename="test-output",
            df=sample_dataframe,
        )
        
        assert filename == "test-output.csv"
        assert isinstance(data, bytes)
        assert b"user_id" in data
        assert b"alice" in data

    @pytest.mark.asyncio
    async def test_prepare_csv_with_datetime(self):
        """Test _prepare_csv handles datetime columns."""
        df = pd.DataFrame({
            "id": [1, 2],
            "timestamp": pd.date_range("2024-01-01", periods=2),
        })
        
        filename, data = S3Destination._prepare_csv(
            filename="datetime-test",
            df=df,
        )
        
        assert isinstance(data, bytes)
        assert b"timestamp" in data

    def test_upload_format_selection(self):
        """Test upload method format parameter validation."""
        config = S3DestinationConfig(
            access_key="test-key",
            secret_key="test-secret",
            bucket="test-bucket",
        )
        writer = S3Destination(config=config)
        
        # CSV should work
        assert hasattr(writer, "upload")
        
        # Invalid format should raise error in upload
        # This requires mocking the S3 client, tested in integration tests
