from pydantic import SecretStr, Field, field_validator
from .base import DataSource, DataSourceConfig
from . import register_source
import pandas as pd
import s3fs
from src.config import Settings
from src.logger import LoggerFactory
from typing import Optional, Literal


logger = LoggerFactory.getLogger(__name__)
global_settings = Settings()


class S3SourceConfig(DataSourceConfig):
    path: str = Field(..., description="S3 URI, e.g., s3://bucket/prefix/")
    access_key: Optional[str] = Field(None, description="Override global access key")
    secret_key: Optional[SecretStr] = Field(
        None, description="Override global secret key"
    )
    region: Optional[str] = Field(None, description="AWS region (e.g., us-east-1)")
    endpoint_url: Optional[str] = Field(
        None, description="Custom S3 endpoint (for minio, etc.)"
    )

    @field_validator("path", mode="after")
    @classmethod
    def validate_path(cls, v: str):
        if not v.startswith("s3://"):
            raise ValueError("S3 path must start with 's3://'")
        return v


@register_source
class S3Source(DataSource):
    type: Literal["s3"] = "s3"
    config: S3SourceConfig

    def load_dataframe(self, limit: int | None = None) -> pd.DataFrame:
        logger.info("Loading from S3: %s", self.config.path)

        # Build S3 args: source config > global settings
        s3_kwargs = {}
        if self.config.access_key or self.config.secret_key:
            s3_kwargs.update(
                key=self.config.access_key or global_settings.s3_source.access_key,
                secret=(
                    self.config.secret_key.get_secret_value()
                    if self.config.secret_key
                    else global_settings.s3_source.secret_key.get_secret_value()
                ),
            )
        elif (
            global_settings.s3_source.access_key
            and global_settings.s3_source.secret_key
        ):
            s3_kwargs.update(
                key=global_settings.s3_source.access_key,
                secret=global_settings.s3_source.secret_key,
            )

        if self.config.region or global_settings.s3_source.region:
            s3_kwargs["client_kwargs"] = {
                "region_name": self.config.region or global_settings.s3_source.region
            }

        if self.config.endpoint_url:
            s3_kwargs["client_kwargs"] = s3_kwargs.get("client_kwargs", {})
            s3_kwargs["client_kwargs"]["endpoint_url"] = self.config.endpoint_url

        fs = s3fs.S3FileSystem(**s3_kwargs)
        df = pd.read_parquet(self.config.path, filesystem=fs)

        if limit is not None and len(df) > limit:
            df = df.head(limit)

        logger.info("Loaded %d rows from S3", len(df))
        return df
