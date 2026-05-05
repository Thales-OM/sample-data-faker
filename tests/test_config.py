"""
Unit tests for Settings and configuration classes.
"""
import pytest
from pydantic import ValidationError

from src.config import (
    Settings,
    S3DestinationConfig,
    S3SourceConfig,
    OMDConfig,
    TrinoConnectionConfig,
)
from src.config.constants import SDVSynthesizer
from src.sources.s3 import S3SourceConfig as SourceS3SourceConfig
from src.sources.trino import TrinoSourceConfig as SourceTrinoSourceConfig


@pytest.mark.unit
class TestTrinoConnectionConfig:
    """Tests for TrinoConnectionConfig."""

    def test_minimal_config(self):
        """Test minimal required configuration."""
        config = TrinoConnectionConfig(
            host="trino.example.com",
            user="test_user",
        )
        assert config.host == "trino.example.com"
        assert config.port == 443
        assert config.user == "test_user"
        assert config.password is None
        assert config.catalog == "dto_iceberg"

    def test_full_config(self):
        """Test full configuration with all fields."""
        config = TrinoConnectionConfig(
            host="trino.example.com",
            port=8080,
            user="test_user",
            password="secret_password",
            catalog="hive",
        )
        assert config.host == "trino.example.com"
        assert config.port == 8080
        assert config.user == "test_user"
        assert config.password.get_secret_value() == "secret_password"
        assert config.catalog == "hive"

    def test_host_required(self):
        """Test that host is required."""
        with pytest.raises(ValidationError):
            TrinoConnectionConfig(user="test_user")

    def test_user_required(self):
        """Test that user is required."""
        with pytest.raises(ValidationError):
            TrinoConnectionConfig(host="trino.example.com")


@pytest.mark.unit
class TestOMDConfig:
    """Tests for OMDConfig (OpenMetadata configuration)."""

    def test_minimal_config(self):
        """Test minimal required configuration."""
        config = OMDConfig(
            api_url="https://om.example.com",
            token="test-token-12345",
        )
        assert str(config.api_url) == "https://om.example.com"
        assert config.token.get_secret_value() == "test-token-12345"
        assert config.api_version == "v1"
        assert config.timeout == 30.0
        assert config.retries == 3

    def test_full_config(self):
        """Test full configuration with all fields."""
        config = OMDConfig(
            api_url="https://om.example.com",
            token="test-token-12345",
            api_version="v1",
            timeout=60.0,
            retries=5,
        )
        assert config.timeout == 60.0
        assert config.retries == 5

    def test_api_url_strips_trailing_slash(self):
        """Test that trailing slash is removed from api_url."""
        config = OMDConfig(
            api_url="https://om.example.com/",
            token="test-token-12345",
        )
        assert str(config.api_url) == "https://om.example.com"

    def test_token_min_length(self):
        """Test that token must be at least 10 characters."""
        with pytest.raises(ValidationError):
            OMDConfig(
                api_url="https://om.example.com",
                token="short",
            )

    def test_api_version_format(self):
        """Test that api_version must match pattern v{number}."""
        # Valid
        config = OMDConfig(
            api_url="https://om.example.com",
            token="test-token-12345",
            api_version="v1",
        )
        assert config.api_version == "v1"
        
        # Invalid
        with pytest.raises(ValidationError):
            OMDConfig(
                api_url="https://om.example.com",
                token="test-token-12345",
                api_version="1",
            )

    def test_timeout_bounds(self):
        """Test timeout must be between 1 and 300 seconds."""
        # Valid
        config = OMDConfig(
            api_url="https://om.example.com",
            token="test-token-12345",
            timeout=1.0,
        )
        assert config.timeout == 1.0
        
        config = OMDConfig(
            api_url="https://om.example.com",
            token="test-token-12345",
            timeout=300.0,
        )
        assert config.timeout == 300.0
        
        # Invalid
        with pytest.raises(ValidationError):
            OMDConfig(
                api_url="https://om.example.com",
                token="test-token-12345",
                timeout=0.5,
            )

    def test_retries_bounds(self):
        """Test retries must be between 0 and 5."""
        config = OMDConfig(
            api_url="https://om.example.com",
            token="test-token-12345",
            retries=0,
        )
        assert config.retries == 0
        
        with pytest.raises(ValidationError):
            OMDConfig(
                api_url="https://om.example.com",
                token="test-token-12345",
                retries=6,
            )


@pytest.mark.unit
class TestS3SourceConfig:
    """Tests for S3SourceConfig."""

    def test_minimal_config(self):
        """Test minimal required configuration."""
        config = S3SourceConfig(
            access_key="test-access-key",
            secret_key="test-secret-key",
            bucket="test-bucket",
        )
        assert config.access_key == "test-access-key"
        assert config.secret_key.get_secret_value() == "test-secret-key"
        assert config.bucket == "test-bucket"
        assert config.region == "us-east-1"
        assert config.endpoint is None
        assert config.key is None

    def test_full_config(self):
        """Test full configuration with all fields."""
        config = S3SourceConfig(
            endpoint="http://localhost:9000",
            access_key="test-access-key",
            secret_key="test-secret-key",
            region="eu-west-1",
            bucket="test-bucket",
            key="path/to/file.parquet",
        )
        assert str(config.endpoint) == "http://localhost:9000/"
        assert config.region == "eu-west-1"
        assert config.key == "path/to/file.parquet"

    def test_secret_key_hidden(self):
        """Test that secret_key is excluded from representation."""
        config = S3SourceConfig(
            access_key="test-access-key",
            secret_key="super-secret",
            bucket="test-bucket",
        )
        repr_str = repr(config)
        assert "super-secret" not in repr_str


@pytest.mark.unit
class TestS3DestinationConfig:
    """Tests for S3DestinationConfig."""

    def test_minimal_config(self):
        """Test minimal required configuration."""
        config = S3DestinationConfig(
            access_key="test-access-key",
            secret_key="test-secret-key",
            bucket="test-bucket",
        )
        assert config.access_key == "test-access-key"
        assert config.secret_key.get_secret_value() == "test-secret-key"
        assert config.bucket == "test-bucket"
        assert config.region == "us-east-1"
        assert config.key is None

    def test_with_custom_key(self):
        """Test configuration with custom key path."""
        config = S3DestinationConfig(
            access_key="test-access-key",
            secret_key="test-secret-key",
            bucket="test-bucket",
            key="custom/path/output.csv",
        )
        assert config.key == "custom/path/output.csv"


@pytest.mark.unit
class TestSourceS3SourceConfig:
    """Tests for sources.s3.S3SourceConfig."""

    def test_valid_s3_path(self):
        """Test valid S3 path."""
        config = SourceS3SourceConfig(
            path="s3://bucket/prefix/data.parquet",
        )
        assert config.path == "s3://bucket/prefix/data.parquet"

    def test_invalid_s3_path(self):
        """Test that non-S3 path raises error."""
        with pytest.raises(ValueError, match="S3 path must start with 's3://'"):
            SourceS3SourceConfig(
                path="gs://bucket/data.parquet",
            )

    def test_optional_fields(self):
        """Test optional override fields."""
        config = SourceS3SourceConfig(
            path="s3://bucket/data.parquet",
            access_key="override-key",
            secret_key="override-secret",
            region="eu-central-1",
            endpoint_url="http://minio:9000",
        )
        assert config.access_key == "override-key"
        assert config.secret_key.get_secret_value() == "override-secret"
        assert config.region == "eu-central-1"
        assert config.endpoint_url == "http://minio:9000"


@pytest.mark.unit
class TestSourceTrinoSourceConfig:
    """Tests for sources.trino.TrinoSourceConfig."""

    def test_minimal_config(self):
        """Test minimal required configuration."""
        config = SourceTrinoSourceConfig(
            host="trino.example.com",
            port=443,
            user="test_user",
            catalog="dto_iceberg",
            schema="assembly",
            table="assembled",
        )
        assert config.host == "trino.example.com"
        assert config.port == 443
        assert config.user == "test_user"
        assert config.catalog == "dto_iceberg"
        assert config.schema_name == "assembly"
        assert config.table == "assembled"
        assert config.password is None

    def test_with_password(self):
        """Test configuration with password."""
        config = SourceTrinoSourceConfig(
            host="trino.example.com",
            user="test_user",
            password="secret123",
            catalog="hive",
            schema="public",
            table="users",
        )
        assert config.password.get_secret_value() == "secret123"

    def test_host_cannot_be_empty(self):
        """Test that host cannot be empty."""
        with pytest.raises(ValueError, match="Host cannot be empty"):
            SourceTrinoSourceConfig(
                host="  ",
                user="test_user",
                catalog="hive",
                schema="public",
                table="users",
            )

    def test_optional_headers_and_session(self):
        """Test optional http_headers and session_properties."""
        config = SourceTrinoSourceConfig(
            host="trino.example.com",
            user="test_user",
            catalog="hive",
            schema="public",
            table="users",
            http_headers={"X-Custom-Header": "value"},
            session_properties={"query_priority": "high"},
        )
        assert config.http_headers == {"X-Custom-Header": "value"}
        assert config.session_properties == {"query_priority": "high"}


@pytest.mark.unit
class TestSettings:
    """Tests for main Settings class."""

    def test_default_settings(self):
        """Test default settings values."""
        settings = Settings()
        assert settings.max_threads == 2
        assert settings.max_pending == 3
        assert settings.sdv_model_type == SDVSynthesizer.GAUSSIAN_COPULA
        assert settings.sdv_model_params == {}
        assert settings.log_level == "INFO"

    def test_custom_settings(self):
        """Test custom settings values."""
        settings = Settings(
            max_threads=4,
            max_pending=5,
            sdv_model_type=SDVSynthesizer.CTGAN,
            sdv_model_params={"epochs": 100},
            log_level="DEBUG",
        )
        assert settings.max_threads == 4
        assert settings.max_pending == 5
        assert settings.sdv_model_type == SDVSynthesizer.CTGAN
        assert settings.sdv_model_params == {"epochs": 100}
        assert settings.log_level == "DEBUG"

    def test_sdv_model_class_property(self):
        """Test sdv_model_class property returns correct class."""
        from sdv.single_table import GaussianCopulaSynthesizer, CTGANSynthesizer
        
        settings_gc = Settings(sdv_model_type=SDVSynthesizer.GAUSSIAN_COPULA)
        assert settings_gc.sdv_model_class == GaussianCopulaSynthesizer
        
        settings_ctgan = Settings(sdv_model_type=SDVSynthesizer.CTGAN)
        assert settings_ctgan.sdv_model_class == CTGANSynthesizer

    def test_invalid_sdv_model_type(self):
        """Test that invalid sdv_model_type raises error."""
        with pytest.raises(KeyError):
            Settings(sdv_model_type="InvalidSynthesizer")

    def test_nested_s3_source_config(self):
        """Test Settings with nested S3 source config."""
        settings = Settings(
            s3_source=S3SourceConfig(
                access_key="test-key",
                secret_key="test-secret",
                bucket="test-bucket",
            )
        )
        assert settings.s3_source.access_key == "test-key"
        assert settings.s3_source.bucket == "test-bucket"

    def test_nested_omd_config(self):
        """Test Settings with nested OpenMetadata config."""
        settings = Settings(
            openmetadata_destination=OMDConfig(
                api_url="https://om.example.com",
                token="test-token-12345",
            )
        )
        assert settings.openmetadata_destination.api_url is not None
        assert settings.openmetadata_destination.token.get_secret_value() == "test-token-12345"

    def test_nested_trino_config(self):
        """Test Settings with nested Trino config."""
        settings = Settings(
            trino_source=TrinoConnectionConfig(
                host="trino.example.com",
                user="test_user",
                catalog="hive",
            )
        )
        assert settings.trino_source.host == "trino.example.com"
        assert settings.trino_source.user == "test_user"

    def test_nested_s3_destination_config(self):
        """Test Settings with nested S3 destination config."""
        settings = Settings(
            s3_destination=S3DestinationConfig(
                access_key="test-key",
                secret_key="test-secret",
                bucket="test-bucket",
                key="output/file.csv",
            )
        )
        assert settings.s3_destination.access_key == "test-key"
        assert settings.s3_destination.key == "output/file.csv"

    def test_env_file_loading(self, tmp_path):
        """Test loading settings from .env file."""
        env_file = tmp_path / ".test.env"
        env_file.write_text("""
MAX_WORKERS=5
MAX_PENDING=10
SDV_MODEL_TYPE=CTGANSynthesizer
LOG_LEVEL=WARNING
""")
        
        settings = Settings(_env_file=env_file)
        assert settings.max_threads == 5
        assert settings.max_pending == 10
        assert settings.sdv_model_type == SDVSynthesizer.CTGAN
        assert settings.log_level == "WARNING"

    def test_extra_fields_ignored(self):
        """Test that extra fields are ignored (not raised as errors)."""
        # This should not raise an error due to extra="ignore"
        settings = Settings(
            unknown_field="should be ignored",
            another_unknown=123,
        )
        assert settings.max_threads == 2  # Default value
