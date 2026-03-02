from typing import Optional, Literal, Tuple
import pandas as pd
from aiobotocore.session import get_session
from botocore.config import Config
from src.config import S3DestinationConfig
from src.logger import LoggerFactory


logger = LoggerFactory.getLogger(__name__)


class S3Writer:
    def __init__(self, config: S3DestinationConfig):
        self._config = config

    async def upload(
        self,
        df: pd.DataFrame,
        filename: str,
        prefix: Optional[str] = None,
        format: Literal["csv"] = "csv",
    ) -> str:
        """
        Asynchronously upload CSV file to S3/MinIO bucket under domain-named prefix.

        Args:
            df (pd.DataFrame): tabular data to upload
            filename (str): file name (without extension)
            prefix (Optional[str], optional): S3 path prefix. Defaults to None.
            format (Literal["csv"], optional): file format to save in. Defaults to "csv".

        Returns:
            str: Path to the saved file in the given bucket
        """

        filename_with_ext = None
        data = None
        match format:
            case "csv":
                filename_with_ext, data = self._prepare_csv(filename=filename, df=df)
            case _:
                raise ValueError(f"Unexpected format parameter: {format}")

        s3_key = filename_with_ext
        if prefix:
            s3_key = f"{prefix}/{s3_key}"
        if self._config.key:
            s3_key = self._config.key

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

            await s3_client.put_object(
                Bucket=bucket_name,
                Key=s3_key,
                Body=data,
                ContentType="text/csv",
                Metadata={"original-filename": filename},
            )

            logger.info(f"Uploaded to s3://{bucket_name}/{s3_key}")
            return s3_key

    @staticmethod
    def _prepare_csv(filename: str, df: pd.DataFrame) -> Tuple[str, bytes]:
        filename_with_ext = f"{filename}.csv"
        data = df.to_csv(date_format="iso", index=False).encode("utf-8")
        return filename_with_ext, data
