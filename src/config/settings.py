from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr, HttpUrl, field_validator
from typing import Optional, Type, Literal
from .secrets import DumpableSecretsBaseModel
from .types import HiveMetastoreUri, JsonDict
from .constants import (
    SDVSynthesizer,
    DEFAULT_LOG_LEVEL,
    BaseSynthesizer,
    SYNTHESIZER_MAP,
    APP_VERSION,
    DEFAULT_MAX_THREADS,
    DEFAULT_MAX_PENDING,
)


class TrinoConnectionConfig(BaseSettings):
    host: str
    port: int = 443
    user: str
    password: Optional[SecretStr] = None
    catalog: str = "dto_iceberg"


class OMDConfig(BaseSettings):
    api_url: HttpUrl = Field(
        ..., description="Base URL of OpenMetadata server, e.g. https://om.example.com"
    )
    token: SecretStr = Field(
        ..., min_length=10, description="Bearer token for authentication"
    )
    api_version: str = Field(
        "v1", pattern=r"^v\d+$", description="API version (e.g., 'v1')"
    )
    timeout: float = Field(30.0, ge=1, le=300, description="HTTP timeout in seconds")
    retries: int = Field(
        3, ge=0, le=5, description="Number of retries on transient errors"
    )

    @field_validator("api_url", mode="after")
    @classmethod
    def ensure_no_trailing_slash(cls, v):
        return HttpUrl(str(v).rstrip("/"))


class S3DestinationConfig(BaseSettings, DumpableSecretsBaseModel):
    endpoint: Optional[HttpUrl] = Field(
        None, description="Custom S3 endpoint (for minio, etc.)"
    )
    access_key: str
    secret_key: SecretStr = Field(exclude=True)
    region: str = Field("us-east-1", description="AWS region (e.g., us-east-1)")
    bucket: str


class HMSS3DestinationConfig(BaseSettings, DumpableSecretsBaseModel):
    catalog_name: str = Field(serialization_alias="name")
    type: Literal["hive"] = "hive"
    uri: HiveMetastoreUri = Field(examples=["thrift://hms:9083"])
    warehouse: str = Field(examples=["s3://my-bucket/warehouse/"])
    s3_access_key_id: str = Field(serialization_alias="s3.access-key-id")
    s3_secret_access_key: SecretStr = Field(
        serialization_alias="s3.secret-access-key",
    )
    write_format_default: str = Field(
        "parquet",
        serialization_alias="write.format.default",
    )
    s3_region: str = Field("us-east-1", serialization_alias="s3.region")
    s3_endpoint: str = Field(
        serialization_alias="s3.endpoint",
        description="S3 endpoint URL (optional, for MinIO etc.)",
    )
    py_io_impl: str = Field(
        "pyiceberg.io.pyarrow.PyArrowFileIO", serialization_alias="py-io-impl"
    )

    model_config = SettingsConfigDict(populate_by_name=True)


class FatAPISettings(BaseSettings):
    root_path: str = ""
    version: str = APP_VERSION


class Settings(BaseSettings):
    # Default source configs
    trino_source: Optional[TrinoConnectionConfig] = None

    # Default publish destinations
    openmetadata_destination: Optional[OMDConfig] = None
    s3_destination: Optional[S3DestinationConfig] = None
    hms_s3_destination: Optional[HMSS3DestinationConfig] = None

    # FastAPI app settings
    fastapi: FatAPISettings = FatAPISettings()

    # SDV & queue
    max_threads: int = Field(
        DEFAULT_MAX_THREADS,
        ge=1,
        description="How much concurrent workloads to run at max",
    )
    max_pending: int = Field(DEFAULT_MAX_PENDING, ge=1, description="Max backpressure")
    sdv_model_type: SDVSynthesizer = SDVSynthesizer.GAUSSIAN_COPULA
    sdv_model_params: JsonDict = Field(default_factory=dict)

    # Logging
    log_level: str = DEFAULT_LOG_LEVEL

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    @field_validator("sdv_model_type", mode="after")
    @classmethod
    def check_class_mapping(cls, v):
        if not (synthesizer_class := SYNTHESIZER_MAP.get(v, None)):
            raise KeyError("Synthesizer is declared but is missing a class mapping")
        if not issubclass(synthesizer_class, BaseSynthesizer):
            raise ValueError(
                "Synthesizer is misdeclared, not an subclass from BaseSynthesizer"
            )
        return v

    @property
    def sdv_model_class(self) -> Type[BaseSynthesizer]:
        return SYNTHESIZER_MAP[self.sdv_model_type]
