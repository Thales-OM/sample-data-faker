from typing import List, Dict, Any
from pydantic import RootModel, BaseModel
from src.destinations import S3DestinationResponse, IcebergDestinationResponse


class SyntheticResponse(RootModel[List[Dict[str, Any]]]):
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


class DTOS3FileUpload(BaseModel, S3DestinationResponse):
    pass


class DTOIcebergUpload(BaseModel, IcebergDestinationResponse):
    pass


class DTOAvroOCFResponse(BaseModel):
    message: str = "ok"
    s3_file_upload: DTOS3FileUpload
    iceberg_upload: DTOIcebergUpload
