from typing import List, Dict, Any
from pydantic import RootModel, BaseModel


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
    root: str = "OK!"


class LivenessResponse(RootModel[str]):
    root: str = "OK!"


class VersionResponse(BaseModel):
    version: str = "unknown"


class AvroOCFResponse(BaseModel):
    message: str = "ok"
    s3_path: str
