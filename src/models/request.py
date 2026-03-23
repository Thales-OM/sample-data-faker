from pydantic import BaseModel, Field
from src.sources import SourceConfig
from typing import Optional
from src.config import DEFAULT_OUTPUT_SIZE


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


class DTOAvroOCFRequest(BaseModel):
    file_content: bytes = Field(..., description="Avro OCF file content as raw bytes")
    filename: Optional[str] = Field(None, description="Original filename")
    output_size: int = Field(
        DEFAULT_OUTPUT_SIZE,
        gt=0,
        le=10000,
        example=100,
        description="How many rows to generate",
    )
    load_limit: Optional[int] = Field(
        None,
        gt=0,
        description="Maximum number of rows to load from the source for training.",
        example=1000,
    )
