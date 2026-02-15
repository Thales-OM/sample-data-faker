from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr, HttpUrl, field_validator
from typing import Optional
from .constants import (
    SDVSynthesizer,
    DEFAULT_LOG_LEVEL,
    BaseSynthesizer,
    SYNTHESIZER_MAP,
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


class S3DestinationConfig(BaseSettings):
    S3_ENDPOINT: HttpUrl = HttpUrl("http://localhost:9000")
    S3_ACCESS_KEY: str
    S3_SECRET_KEY: SecretStr = Field(exclude=True)
    S3_REGION: str
    S3_BUCKET: str
    S3_USE_SSL: bool

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


class Settings(BaseSettings):
    # Global AWS (fallback)
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[SecretStr] = None
    aws_region: Optional[str] = None

    # Trino
    trino: Optional[TrinoConnectionConfig] = None

    # SDV & queue
    max_concurrent_synthetic_jobs: int = 2
    sdv_model_type: SDVSynthesizer = SDVSynthesizer.GAUSSIAN_COPULA
    sdv_model_params: dict = {}
    cleanup_on_complete: bool = True

    # Logging
    log_level: str = DEFAULT_LOG_LEVEL

    # OpenMetadata
    openmetadata: Optional[OMDConfig] = None

    # Sample data S3 destination
    s3_destination: S3DestinationConfig = S3DestinationConfig()

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
    def sdv_model_class(self) -> BaseSynthesizer:
        return SYNTHESIZER_MAP[self.sdv_model_type]


settings = Settings()
