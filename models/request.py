from pydantic import BaseModel, Field
from sources import SourceConfig
from typing import Optional


class SyntheticRequest(BaseModel):
    source: SourceConfig = Field(..., description="Data source configuration.")
    output_size: int = Field(
        ..., gt=0, example=1000, description="How many rows to generate"
    )
    load_limit: Optional[int] = Field(
        None,
        gt=0,
        description="Maximum number of rows to load from the source for training.",
        example=5000,
    )
