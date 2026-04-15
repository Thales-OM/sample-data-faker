from dataclasses import dataclass
import pandas as pd
from typing import Any, Dict
from src.openmetadata import SampleData
from src.logger import LoggerFactory
from src.openmetadata import AsyncOMDClient
from .base import BaseDestination, BaseDestinationResponse


logger = LoggerFactory.getLogger(__name__)


@dataclass
class OpenMetadataDestinationResponse(BaseDestinationResponse):
    table: Dict[str, Any]


class OpenMetadataDestination(BaseDestination):
    async def submit(
        self, df: pd.DataFrame, table_id: str, client: AsyncOMDClient
    ) -> OpenMetadataDestinationResponse:
        sample_data = SampleData.from_dataframe(df=df)
        table = await client.add_sample_data(id=table_id, body=sample_data)
        return OpenMetadataDestinationResponse(table=table)
