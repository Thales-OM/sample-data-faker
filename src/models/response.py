from enum import StrEnum
from typing import List, Dict, Any, Literal
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


class HealthStatus(StrEnum):
    OK = "ok"


class HealthResponse(BaseModel):
    status: HealthStatus = HealthStatus.OK
