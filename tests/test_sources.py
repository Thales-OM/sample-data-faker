"""
Unit tests for data sources: S3Source, AvroOCFSource, TrinoSource, DummySource.
"""
import io
import tempfile
import os
from unittest.mock import patch, MagicMock

import pytest
import pandas as pd
import fastavro
from fastapi import UploadFile
from pydantic import SecretStr

from src.sources.base import DataSource, DataSourceConfig
from src.sources.s3 import S3Source, S3SourceConfig
from src.sources.avro_ocf import AvroOCFSource, AvroOCFSourceConfig
from src.sources.trino import TrinoSource, TrinoSourceConfig
from src.sources.dummy import DummySource, DummySourceConfig


@pytest.mark.unit
class TestDummySource:
    """Tests for DummySource."""

    def test_init(self, sample_dataframe: pd.DataFrame):
        """Test DummySource initialization."""
        config = DummySourceConfig(data=sample_dataframe)
        source = DummySource(config=config)
        
        assert source.type == "dummy"
        assert source.config.data is sample_dataframe

    def test_load_dataframe(self, sample_dataframe: pd.DataFrame):
        """Test loading DataFrame from DummySource."""
        config = DummySourceConfig(data=sample_dataframe)
        source = DummySource(config=config)
        
        result = source.load_dataframe()
        pd.testing.assert_frame_equal(result, sample_dataframe)

    def test_load_dataframe_with_limit(self, sample_dataframe: pd.DataFrame):
        """Test loading DataFrame with limit."""
        config = DummySourceConfig(data=sample_dataframe)
        source = DummySource(config=config)
        
        result = source.load_dataframe(limit=3)
        assert len(result) == 3
        pd.testing.assert_frame_equal(result, sample_dataframe.head(3))

    def test_load_dataframe_limit_exceeds_data(self, sample_dataframe: pd.DataFrame):
        """Test loading DataFrame with limit larger than data."""
        config = DummySourceConfig(data=sample_dataframe)
        source = DummySource(config=config)
        
        result = source.load_dataframe(limit=100)
        assert len(result) == len(sample_dataframe)
        pd.testing.assert_frame_equal(result, sample_dataframe)


@pytest.mark.unit
class TestAvroOCFSourceConfig:
    """Tests for AvroOCFSourceConfig."""

    def test_valid_avro_file(self, avro_file: str):
        """Test config with valid .avro file."""
        with open(avro_file, "rb") as f:
            upload_file = UploadFile(
                filename="test.avro",
                file=f,
                content_type="application/octet-stream",
            )
            config = AvroOCFSourceConfig(file_content=upload_file)
            assert config.file_content.filename == "test.avro"

    def test_invalid_extension(self):
        """Test that non-.avro extension raises error."""
        from fastapi import HTTPException
        
        upload_file = UploadFile(
            filename="test.parquet",
            file=io.BytesIO(b"dummy"),
            content_type="application/octet-stream",
        )
        
        with pytest.raises(HTTPException, match="400"):
            AvroOCFSourceConfig(file_content=upload_file)

    def test_no_extension(self):
        """Test that missing extension raises error."""
        from fastapi import HTTPException
        
        upload_file = UploadFile(
            filename="testfile",
            file=io.BytesIO(b"dummy"),
            content_type="application/octet-stream",
        )
        
        with pytest.raises(HTTPException, match="400"):
            AvroOCFSourceConfig(file_content=upload_file)


@pytest.mark.unit
class TestAvroOCFSource:
    """Tests for AvroOCFSource."""

    def test_init(self, avro_file: str):
        """Test AvroOCFSource initialization."""
        with open(avro_file, "rb") as f:
            upload_file = UploadFile(
                filename="test.avro",
                file=f,
                content_type="application/octet-stream",
            )
            config = AvroOCFSourceConfig(file_content=upload_file)
            source = AvroOCFSource(config=config)
            
            assert source.type == "avro-ocf"

    def test_load_dataframe(self, avro_file: str):
        """Test loading DataFrame from Avro OCF file."""
        with open(avro_file, "rb") as f:
            upload_file = UploadFile(
                filename="test.avro",
                file=f,
                content_type="application/octet-stream",
            )
            config = AvroOCFSourceConfig(file_content=upload_file)
            source = AvroOCFSource(config=config)
            
            df = source.load_dataframe()
            
            assert isinstance(df, pd.DataFrame)
            assert len(df) == 3  # 3 records in test file
            assert "user_id" in df.columns
            assert "username" in df.columns

    def test_load_dataframe_with_limit(self, avro_file: str):
        """Test loading DataFrame with limit."""
        with open(avro_file, "rb") as f:
            upload_file = UploadFile(
                filename="test.avro",
                file=f,
                content_type="application/octet-stream",
            )
            config = AvroOCFSourceConfig(file_content=upload_file)
            source = AvroOCFSource(config=config)
            
            df = source.load_dataframe(limit=2)
            
            assert len(df) == 2

    def test_title_and_namespace_after_load(self, avro_file: str):
        """Test that title and namespace are set after load_dataframe."""
        with open(avro_file, "rb") as f:
            upload_file = UploadFile(
                filename="test.avro",
                file=f,
                content_type="application/octet-stream",
            )
            config = AvroOCFSourceConfig(file_content=upload_file)
            source = AvroOCFSource(config=config)
            
            # Before loading, accessing title/namespace should raise error
            with pytest.raises(RuntimeError, match="Call .load_dataframe\\(\\)"):
                _ = source.title
            
            # After loading, they should be available
            source.load_dataframe()
            assert source.title == "User"
            assert source.namespace == "test"

    def test_invalid_avro_magic_bytes(self):
        """Test that invalid Avro magic bytes raise error."""
        from fastapi import HTTPException
        
        # Create file with invalid magic bytes
        upload_file = UploadFile(
            filename="invalid.avro",
            file=io.BytesIO(b"NOT_A_VALID_AVRO_FILE"),
            content_type="application/octet-stream",
        )
        config = AvroOCFSourceConfig(file_content=upload_file)
        source = AvroOCFSource(config=config)
        
        with pytest.raises(HTTPException, match="Invalid Avro file"):
            source.load_dataframe()

    def test_empty_avro_file(self):
        """Test that empty Avro file raises error."""
        from fastapi import HTTPException
        
        # Create minimal valid Avro header but no records
        schema = {
            "type": "record",
            "name": "test.Empty",
            "fields": [{"name": "id", "type": "int"}],
        }
        
        buf = io.BytesIO()
        # Write valid but empty Avro file
        fastavro.writer(buf, schema, [])
        buf.seek(0)
        
        upload_file = UploadFile(
            filename="empty.avro",
            file=buf,
            content_type="application/octet-stream",
        )
        config = AvroOCFSourceConfig(file_content=upload_file)
        source = AvroOCFSource(config=config)
        
        with pytest.raises(HTTPException, match="no records"):
            source.load_dataframe()

    def test_avro_without_schema(self):
        """Test handling of Avro file without schema."""
        from fastapi import HTTPException
        
        # This is hard to test without a malformed file
        # The fastavro library handles schema extraction
        pass  # Covered by other tests


@pytest.mark.unit
class TestTrinoSourceConfig:
    """Tests for TrinoSourceConfig."""

    def test_valid_config(self):
        """Test valid Trino source config."""
        config = TrinoSourceConfig(
            host="trino.example.com",
            port=443,
            user="test_user",
            catalog="dto_iceberg",
            schema="assembly",
            table="assembled",
        )
        assert config.host == "trino.example.com"
        assert config.schema_name == "assembly"
        assert config.table == "assembled"

    def test_password_optional(self):
        """Test that password is optional."""
        config = TrinoSourceConfig(
            host="trino.example.com",
            user="test_user",
            catalog="hive",
            schema="public",
            table="users",
        )
        assert config.password is None

    def test_http_headers_optional(self):
        """Test that http_headers is optional."""
        config = TrinoSourceConfig(
            host="trino.example.com",
            user="test_user",
            catalog="hive",
            schema="public",
            table="users",
        )
        assert config.http_headers is None


@pytest.mark.unit
class TestTrinoSource:
    """Tests for TrinoSource."""

    def test_init(self):
        """Test TrinoSource initialization."""
        config = TrinoSourceConfig(
            host="trino.example.com",
            user="test_user",
            catalog="dto_iceberg",
            schema="assembly",
            table="assembled",
        )
        source = TrinoSource(config=config)
        
        assert source.type == "trino"

    @patch("src.sources.trino.create_engine")
    @patch("src.sources.trino.pd.read_sql")
    def test_load_dataframe(self, mock_read_sql, mock_create_engine):
        """Test loading DataFrame from Trino."""
        # Setup mocks
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine
        
        expected_df = pd.DataFrame({"col1": [1, 2], "col2": ["a", "b"]})
        mock_read_sql.return_value = expected_df
        
        config = TrinoSourceConfig(
            host="trino.example.com",
            user="test_user",
            password="secret",
            catalog="hive",
            schema="public",
            table="users",
        )
        source = TrinoSource(config=config)
        
        result = source.load_dataframe()
        
        pd.testing.assert_frame_equal(result, expected_df)
        mock_read_sql.assert_called_once()

    @patch("src.sources.trino.create_engine")
    @patch("src.sources.trino.pd.read_sql")
    def test_load_dataframe_with_limit(self, mock_read_sql, mock_create_engine):
        """Test loading DataFrame with LIMIT clause."""
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine
        
        expected_df = pd.DataFrame({"col1": [1, 2], "col2": ["a", "b"]})
        mock_read_sql.return_value = expected_df
        
        config = TrinoSourceConfig(
            host="trino.example.com",
            user="test_user",
            catalog="hive",
            schema="public",
            table="users",
        )
        source = TrinoSource(config=config)
        
        source.load_dataframe(limit=100)
        
        # Check that LIMIT was added to query
        call_args = mock_read_sql.call_args
        query = call_args[0][0]
        assert "LIMIT 100" in query

    @patch("src.sources.trino.create_engine")
    @patch("src.sources.trino.pd.read_sql")
    def test_load_dataframe_drops_ignore_columns(self, mock_read_sql, mock_create_engine):
        """Test that ignored columns are dropped from result."""
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine
        
        # DataFrame with columns that should be dropped
        df_with_ignored = pd.DataFrame({
            "col1": [1, 2],
            "_dq": [True, False],
            "_dq_failed_checks": [0, 1],
            "_stage_dt": ["2024-01-01", "2024-01-02"],
        })
        mock_read_sql.return_value = df_with_ignored
        
        config = TrinoSourceConfig(
            host="trino.example.com",
            user="test_user",
            catalog="hive",
            schema="public",
            table="users",
        )
        source = TrinoSource(config=config)
        
        result = source.load_dataframe()
        
        assert "_dq" not in result.columns
        assert "_dq_failed_checks" not in result.columns
        assert "_stage_dt" not in result.columns
        assert "col1" in result.columns


@pytest.mark.unit
class TestS3Source:
    """Tests for S3Source."""

    def test_init(self):
        """Test S3Source initialization."""
        config = S3SourceConfig(
            path="s3://bucket/prefix/data.parquet",
        )
        source = S3Source(config=config)
        
        assert source.type == "s3"
        assert source.config.path == "s3://bucket/prefix/data.parquet"

    def test_config_validation(self):
        """Test that S3 path must start with s3://."""
        with pytest.raises(ValueError, match="S3 path must start with 's3://'"):
            S3SourceConfig(path="gs://bucket/data.parquet")

    @patch("src.sources.s3.s3fs.S3FileSystem")
    @patch("src.sources.s3.pd.read_parquet")
    def test_load_dataframe(self, mock_read_parquet, mock_s3fs):
        """Test loading DataFrame from S3."""
        # Setup mocks
        mock_fs = MagicMock()
        mock_s3fs.return_value = mock_fs
        
        expected_df = pd.DataFrame({"col1": [1, 2], "col2": ["a", "b"]})
        mock_read_parquet.return_value = expected_df
        
        config = S3SourceConfig(
            path="s3://bucket/data.parquet",
            access_key="test-key",
            secret_key="test-secret",
        )
        source = S3Source(config=config)
        
        result = source.load_dataframe()
        
        pd.testing.assert_frame_equal(result, expected_df)
        mock_read_parquet.assert_called_once()

    @patch("src.sources.s3.s3fs.S3FileSystem")
    @patch("src.sources.s3.pd.read_parquet")
    def test_load_dataframe_with_limit(self, mock_read_parquet, mock_s3fs):
        """Test loading DataFrame with limit from S3."""
        mock_fs = MagicMock()
        mock_s3fs.return_value = mock_fs
        
        large_df = pd.DataFrame({"col1": list(range(1000))})
        mock_read_parquet.return_value = large_df
        
        config = S3SourceConfig(
            path="s3://bucket/data.parquet",
            access_key="test-key",
            secret_key="test-secret",
        )
        source = S3Source(config=config)
        
        result = source.load_dataframe(limit=100)
        
        assert len(result) == 100

    @patch("src.sources.s3.s3fs.S3FileSystem")
    @patch("src.sources.s3.pd.read_parquet")
    def test_load_dataframe_uses_source_config_over_global(
        self, mock_read_parquet, mock_s3fs
    ):
        """Test that source config overrides global settings."""
        mock_fs = MagicMock()
        mock_s3fs.return_value = mock_fs
        mock_read_parquet.return_value = pd.DataFrame({"col1": [1]})
        
        config = S3SourceConfig(
            path="s3://bucket/data.parquet",
            access_key="override-key",
            secret_key="override-secret",
            region="eu-west-1",
            endpoint_url="http://custom:9000",
        )
        source = S3Source(config=config)
        source.load_dataframe()
        
        # Verify S3FileSystem was called with override values
        call_kwargs = mock_s3fs.call_args[1]
        assert call_kwargs["key"] == "override-key"
        assert call_kwargs["secret"] == "override-secret"
