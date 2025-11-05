from pydantic import Field, field_validator
from .base import DataSource, DataSourceConfig
from . import register_source
from typing import List, Dict, Any
import pandas as pd


# Would be better as RootModel but inheriting from single DataSourceConfig(BaseModel) is preferred
class JSONSourceConfig(DataSourceConfig):
    records: List[Dict[str, Any]] = Field(..., description="Raw JSON records")

    @field_validator("records", mode="after")
    def validate_records(cls, v):
        if not v:
            raise ValueError("Empty 'records' array received")
        if not any(record for record in v):
            raise ValueError("All records are empty")


@register_source("json", JSONSourceConfig)
class JSONSource(DataSource):
    def __init__(self, records: List[Dict[str, Any]]):
        # FIXME: risks storing heavy datasets in memory, implement dump to file until worker picks up the task 
        self.records = records

    def load_dataframe(self, limit: int | None = None) -> pd.DataFrame:
        df = pd.DataFrame(self.records)
        if limit is not None and len(df) > limit:
            df = df.head(limit)
        return df
