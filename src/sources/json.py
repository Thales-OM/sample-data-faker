from pydantic import Field, field_validator
from .base import DataSource, DataSourceConfig
from . import register_source
from typing import List, Dict, Any, Literal
import pandas as pd


# Would be better as RootModel but inheriting from single DataSourceConfig(BaseModel) is preferred
class JSONSourceConfig(DataSourceConfig):
    records: List[Dict[str, Any]] = Field(..., description="Raw JSON records")

    @field_validator("records", mode="after")
    @classmethod
    def validate_records(cls, v):
        if not v:
            raise ValueError("Empty 'records' array received")
        if not any(record for record in v):
            raise ValueError("All records are empty")
        return v


# FIXME: risks storing heavy datasets in memory, implement dump to file until worker picks up the task
@register_source
class JSONSource(DataSource):
    type: Literal["json"]
    config: JSONSourceConfig

    def load_dataframe(self, limit: int | None = None) -> pd.DataFrame:
        df = pd.DataFrame(self.config.records)
        if limit is not None and len(df) > limit:
            df = df.head(limit)
        return df
