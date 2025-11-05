from abc import ABC, abstractmethod
from typing import Optional, Type
import pandas as pd
from pydantic import BaseModel

class DataSourceConfig(BaseModel):
    """Base config model for a data source."""
    pass

class DataSource(ABC):
    config_model: Type[DataSourceConfig]  # to be set by subclass

    @abstractmethod
    def load_dataframe(self, limit: Optional[int] = None) -> pd.DataFrame:
        pass