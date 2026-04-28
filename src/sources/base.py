from abc import abstractmethod, ABC
from typing import Optional, Literal, Union
import pandas as pd
import pyarrow as pa
from pydantic import BaseModel


class DataSourceConfig(BaseModel):
    """Base config model for a data source."""

    pass


class DataSource(BaseModel, ABC):
    type: Literal["base"]
    config: DataSourceConfig

    @abstractmethod
    def load_dataframe(
        self, limit: Optional[int] = None
    ) -> Union[pd.DataFrame, pa.Table]:
        pass
