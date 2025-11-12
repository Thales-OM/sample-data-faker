from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr
from typing import Optional, Dict


class TrinoConnectionConfig(BaseSettings):
    host: str
    port: int = 8080
    catalog: str
    schema_name: str = Field(..., alias="schema")
    user: str
    password: Optional[SecretStr] = None


class Settings(BaseSettings):
    # Global AWS (fallback)
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[SecretStr] = None
    aws_region: Optional[str] = None

    # Named secure connections
    trino_connections: Dict[str, TrinoConnectionConfig] = {}

    # SDV & queue
    max_concurrent_synthetic_jobs: int = 2
    sdv_model_type: str = "GaussianCopulaSynthesizer"
    sdv_model_params: dict = {}
    cleanup_on_complete: bool = True

    # Logging
    log_level: str = Field("INFO")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )


settings = Settings()
