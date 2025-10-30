from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
from pathlib import Path


class Settings(BaseSettings):
    # Queue & concurrency
    max_concurrent_synthetic_jobs: int = 2  # Max concurrent SDV jobs

    # SDV
    sdv_model_type: str = "GaussianCopulaSynthesizer"  # or "CTGANSynthesizer", etc.
    sdv_model_params: dict = {}

    # Cleanup
    cleanup_on_complete: bool = True

    # AWS (for Iceberg/S3)
    aws_region: Optional[str] = None
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None

    log_level: str = Field("INFO")

    # class Config:
    #     env_file = ".env"
    #     env_file_encoding = "utf-8"


settings = Settings()
