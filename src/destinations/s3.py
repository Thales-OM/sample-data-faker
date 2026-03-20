from typing import Optional
from dataclasses import dataclass
import pandas as pd
from io import BytesIO
from pathlib import Path
from enum import StrEnum
from aiobotocore.session import get_session
from botocore.config import Config
from src.config import S3DestinationConfig
from src.logger import LoggerFactory
from .base import BaseDestination, BaseDestinationResponse


logger = LoggerFactory.getLogger(__name__)


class FileFormat(StrEnum):
    """
    Enum defining supported file formats and their corresponding extensions.
    """

    CSV = "csv"
    JSON = "json"
    EXCEL = "excel"
    PARQUET = "parquet"

    @property
    def extension(self) -> str:
        """Returns the file extension with a leading dot (e.g., '.csv')."""
        mapping = {"csv": "csv", "json": "json", "excel": "xlsx", "parquet": "parquet"}
        return f".{mapping[self.value]}"

    @property
    def save_method_name(self) -> str:
        """Returns the corresponding pandas DataFrame method name."""
        mapping = {
            "csv": "to_csv",
            "json": "to_json",
            "excel": "to_excel",
            "parquet": "to_parquet",
        }
        return mapping[self.value]

    @property
    def mime_type(self) -> str:
        """Returns the MIME type for HTTP request/responses."""
        mapping = {
            "csv": "text/csv",
            "json": "application/json",
            "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "parquet": "application/vnd.apache.parquet",
        }
        return mapping[self.value]


@dataclass
class S3DestinationResponse(BaseDestinationResponse):
    s3_key: str


class S3Destination(BaseDestination):
    def __init__(self, config: S3DestinationConfig):
        self._config = config

    async def submit(
        self,
        df: pd.DataFrame,
        filename: str,
        prefix: Optional[str] = None,
        format: FileFormat = FileFormat.CSV,
    ) -> S3DestinationResponse:
        """
        Asynchronously upload file to S3/MinIO bucket under domain-named prefix.

        Args:
            df (pd.DataFrame): tabular data to upload
            filename (str): file name (without extension)
            prefix (Optional[str], optional): S3 path prefix. Defaults to None.
            format (FileFormat, optional): file format to save in. Defaults to "csv".

        Returns:
            str: Path to the saved file in the given bucket
        """
        s3_key = self._get_s3_key(filename=filename, prefix=prefix, format=format)
        content_type = format.mime_type

        # Configure client
        session = get_session()
        bucket_name = self._config.bucket
        client_kwargs = {
            "endpoint_url": str(self._config.endpoint),
            "aws_access_key_id": self._config.access_key,
            "aws_secret_access_key": self._config.secret_key.get_secret_value(),
            "region_name": self._config.region,
            "config": Config(s3={"addressing_style": "path"}),
        }

        async with session.create_client("s3", **client_kwargs) as s3_client:
            # Ensure bucket exists
            try:
                await s3_client.head_bucket(Bucket=bucket_name)
            except Exception as e:
                error_code = (
                    e.response["Error"]["Code"] if hasattr(e, "response") else str(e)
                )
                if "404" in str(error_code):
                    raise FileNotFoundError(
                        f"S3 bucket not found: {bucket_name}"
                    ) from e
                else:
                    raise

            # Create file when bucket in ensured
            data = self._produce_file_bytes(df=df, format=format)

            await s3_client.put_object(
                Bucket=bucket_name,
                Key=s3_key,
                Body=data,
                ContentType=content_type,
                Metadata={"original-filename": filename},
            )

            logger.info(f"Uploaded to s3://{bucket_name}/{s3_key}")
            return S3DestinationResponse(s3_key=s3_key)

    def _get_s3_key(
        self, filename: str, prefix: Optional[str], format: FileFormat
    ) -> str:
        filename_with_ext = self._get_full_filename(filename=filename, format=format)
        s3_key = filename_with_ext
        if prefix:
            s3_key = f"{prefix}/{s3_key}"
        # Specifically configured key overrides prefix/filename
        if self._config.key:
            s3_key = self._config.key
        return s3_key

    @staticmethod
    def _get_full_filename(filename: str, format: FileFormat) -> str:
        file_path = Path(filename)

        # If a full path is provided, respect the directory, but enforce the extension
        if file_path.suffix:
            final_path = file_path.with_suffix(format.extension)
        else:
            final_path = f"{file_path.name}{format.extension}"

        return str(final_path)

    @staticmethod
    def _produce_file_bytes(df: pd.DataFrame, format: FileFormat, **kwargs) -> bytes:
        method_name = format.save_method_name
        save_method = getattr(df, method_name)
        try:
            if format == FileFormat.EXCEL:
                # to_excel requires the buffer as 'excel_writer'
                with BytesIO() as buffer:
                    save_method(buffer, **kwargs)
                    return buffer.getvalue()

            return save_method(**kwargs)
        except Exception as e:
            raise IOError(f"Failed to save file to (format={format}): {e}")
