import pandas as pd
from abc import ABC, abstractmethod


class BaseDestinationResponse:
    pass


class BaseDestination(ABC):
    @abstractmethod
    async def submit(self, df: pd.DataFrame) -> BaseDestinationResponse:
        """Submit data to a configured destination"""
        pass
