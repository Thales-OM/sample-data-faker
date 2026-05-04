from typing import List, Dict, Any, Optional
from enum import StrEnum
from pydantic import RootModel, BaseModel, field_validator
from src.destinations import S3DestinationResponse, IcebergDestinationResponse


class SyntheticJSONResponse(RootModel[List[Dict[str, Any]]]):
    pass


class OpenMetadataPopulateResponse(BaseModel):
    table_fqn: str
    table_id: str
    output_size: int
    message: str = "Sample data added successfully"


class WebhookResponse(BaseModel):
    message: str = "ok"


class ReadinessResponse(RootModel[str]):
    root: str = "ok"


class LivenessResponse(RootModel[str]):
    root: str = "ok"


class VersionResponse(BaseModel):
    version: str = "unknown"


class UploadStatus(StrEnum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


class BaseUploadResult(BaseModel):
    status: UploadStatus
    details: Any = None
    reason: Optional[str] = None
    error: Optional[str] = None

    @field_validator("error", mode="before")
    @classmethod
    def _parse_error(cls, v):
        return str(v) if isinstance(v, Exception) else v


class S3UploadResult(BaseUploadResult):
    details: Optional[S3DestinationResponse] = None


class IcebergUploadResult(BaseUploadResult):
    details: Optional[IcebergDestinationResponse] = None


class DTOAvroOCFResponse(BaseModel):
    message: str = "ok"
    s3_file_upload: Optional[S3UploadResult] = None
    iceberg_upload: Optional[IcebergUploadResult] = None


class BaseFastAPIErrorResponse(BaseModel):
    detail: Optional[str] = None
