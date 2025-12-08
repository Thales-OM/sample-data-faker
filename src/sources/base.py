from abc import abstractmethod
from typing import Optional, Literal
import pandas as pd
from pydantic import BaseModel

class DataSourceConfig(BaseModel):
    """Base config model for a data source."""
    pass

class DataSource(BaseModel):
    type: Literal["base"] = "base"
    config: DataSourceConfig

    @abstractmethod
    def load_dataframe(self, limit: Optional[int] = None) -> pd.DataFrame:
        pass