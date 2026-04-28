from dataclasses import dataclass
import pandas as pd
import pyarrow as pa
from pydantic import Field
from typing import Any, Dict, Union, Optional, Literal
from src.openmetadata import SampleData
from src.logger import LoggerFactory
from src.openmetadata import AsyncOMDClient
from src.config import OMDConfig
from .base import BaseDestination, BaseDestinationResponse, BaseDestinationConfig


logger = LoggerFactory.getLogger(__name__)


@dataclass
class OpenMetadataDestinationResponse(BaseDestinationResponse):
    table: Dict[str, Any]


class OpenMetadataDestinationConfig(BaseDestinationConfig, OMDConfig):
    table_id: str = Field(description="ID of the table to attach SampleData to.")
    omd_async_client: Optional[AsyncOMDClient] = Field(
        None,
        description="Provides an existing client instead of creating a new one. \
            For internal use. Client is not closed upon execution.",
    )


class OpenMetadataDestination(BaseDestination):
    type: Literal["openmetadata"]
    config: OpenMetadataDestinationConfig

    async def submit(
        self, data: Union[pd.DataFrame, pa.Table], table_id: str, client: AsyncOMDClient
    ) -> OpenMetadataDestinationResponse:
        if isinstance(data, pa.Table):
            data = data.to_pandas()

        if self.config.omd_async_client:
            return await self._submit_with_client(
                df=data,
                table_id=self.config.table_id,
                client=self.config.omd_async_client,
            )

        async with AsyncOMDClient(config=self.config, logger=logger) as client:
            return await self._submit_with_client(
                df=data, table_id=self.config.table_id, client=client
            )

    async def _submit_with_client(
        self, df: pd.DataFrame, table_id: str, client: AsyncOMDClient
    ) -> OpenMetadataDestinationResponse:
        sample_data = SampleData.from_dataframe(df=df)
        table = await client.add_sample_data(id=table_id, body=sample_data)
        return OpenMetadataDestinationResponse(table=table)
