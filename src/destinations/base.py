from typing import Union, Literal
import pandas as pd
import pyarrow as pa
from pydantic import BaseModel
from abc import ABC, abstractmethod


class BaseDestinationResponse:
    pass


class BaseDestinationConfig(BaseModel):
    pass


class BaseDestination(ABC, BaseModel):
    type: Literal["base"]
    config: BaseDestinationConfig

    @abstractmethod
    async def submit(
        self, data: Union[pd.DataFrame, pa.Table]
    ) -> BaseDestinationResponse:
        """Submit data to a configured destination"""
        pass
