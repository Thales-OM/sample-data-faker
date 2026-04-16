from pydantic import BaseModel, Field
from typing import Optional
from src.config import DEFAULT_OUTPUT_SIZE
from src.sources import SourceConfig
from src.sources.avro_ocf import AvroBase64Str, AvroFilenameStr


class SyntheticRequest(BaseModel):
    source: SourceConfig = Field(..., description="Data source configuration.")
    output_size: int = Field(
        ..., gt=0, examples=[100], description="How many rows to generate"
    )
    load_limit: Optional[int] = Field(
        None,
        gt=0,
        description="Maximum number of rows to load from the source for training.",
        examples=[1000],
    )


class DTOAvroOCFRequest(BaseModel):
    file_content: AvroBase64Str = Field(
        ..., description="Base64 encoded Avro OCF file content"
    )
    filename: Optional[AvroFilenameStr] = Field(
        None,
        examples=["data.avro"],
        description="Original filename (e.g., 'data.avro')",
    )
    output_size: int = Field(
        DEFAULT_OUTPUT_SIZE,
        gt=0,
        le=10000,
        examples=[100],
        description="How many rows to generate",
    )
    load_limit: Optional[int] = Field(
        None,
        gt=0,
        description="Maximum number of rows to load from the source for training.",
        examples=[1000],
    )
