from pydantic import BaseModel, Field
from src.sources import SourceConfig
from typing import Optional


class SyntheticRequest(BaseModel):
    source: SourceConfig = Field(..., description="Data source configuration.")
    output_size: int = Field(
        ..., gt=0, example=5, description="How many rows to generate"
    )
    load_limit: Optional[int] = Field(
        None,
        gt=0,
        description="Maximum number of rows to load from the source for training.",
        example=1000,
    )
