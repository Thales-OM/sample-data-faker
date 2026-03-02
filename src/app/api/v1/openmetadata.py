from typing import Union, Annotated
import asyncio
from fastapi import Depends, APIRouter, status, HTTPException
from fastapi.responses import JSONResponse
from pydantic import Field
from src.core import SyntheticDataWorker, DataFrameWrapper
from src.models import (
    SyntheticRequest,
    OpenMetadataPopulateResponse,
    SampleData,
    WebhookTableCreated,
    WebhookTableUpdated,
    WebhookResponse,
)
from src.destinations.openmetadata import AsyncOMDClient
from src.sources.trino import TrinoSource, TrinoSourceConfig
from src.utils import openmetadata_to_dto_table
from src.config import DEFAULT_SAMPLE_SIZE, DEFAULT_OUTPUT_SIZE, Settings
from ...deps import get_worker_queue, get_omd_async_client, get_app_settings


router = APIRouter(prefix="/openmetadata")


@router.post(
    "/generate/{table_fqn}",
    response_model=OpenMetadataPopulateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_synthetic(
    body: SyntheticRequest,
    table_fqn: str,
    omd_async_client: AsyncOMDClient = Depends(get_omd_async_client),
    worker: SyntheticDataWorker = Depends(get_worker_queue),
    settings: Settings = Depends(get_app_settings),
):
    table = await omd_async_client.get_table_by_name(
        fqn=table_fqn, fields="id", nullable=True
    )
    if not table:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Table not found in OpenMetadata",
        )
    table_id = table["id"]
    try:
        future = await worker.submit(
            source=body.source,
            output_size=body.output_size,
            synthesizer_cls=settings.sdv_model_class,
            load_limit=body.load_limit,
        )
        synthetic_df_wrap: DataFrameWrapper = await future
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )

    sample_data = SampleData.from_dataframe(df=synthetic_df_wrap.df_clean)
    await omd_async_client.add_sample_data(id=table_id, body=sample_data)
    return OpenMetadataPopulateResponse(
        table_fqn=table_fqn, table_id=table_id, output_size=len(synthetic_df_wrap)
    )


WebhookTableUnionType = Annotated[
    Union[WebhookTableCreated, WebhookTableUpdated], Field(discriminator="eventType")
]


@router.post(
    "/webhook", response_model=WebhookResponse, status_code=status.HTTP_201_CREATED
)
async def webhook(
    body: WebhookTableUnionType,
    omd_async_client: AsyncOMDClient = Depends(get_omd_async_client),
    worker: SyntheticDataWorker = Depends(get_worker_queue),
    settings: Settings = Depends(get_app_settings),
):
    if isinstance(body, WebhookTableUpdated) and not body.is_schema_change():
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=WebhookResponse(message="received, no action needed"),
        )

    if not settings.trino_source:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Trino connection is unavailable",
        )

    table_id = body.entityId
    table = await omd_async_client.get_table_by_id(
        id=table_id, fields="fullyQualifiedName", nullable=True
    )
    if not table:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Table not found in OpenMetadata",
        )
    table_fqn = table["fullyQualifiedName"]

    dto_table_full_name = openmetadata_to_dto_table(
        table_fqn=table_fqn, trino_catalog=settings.trino_source.catalog
    )
    catalog, schema, table_name = dto_table_full_name.split(".")
    trino_config = TrinoSourceConfig(
        host=settings.trino_source.host,
        port=settings.trino_source.port,
        user=settings.trino_source.user,
        password=(
            settings.trino_source.password.get_secret_value()
            if settings.trino_source.password
            else None
        ),
        catalog=catalog,
        schema=schema,
        table=table_name,
    )
    trino_source = TrinoSource(
        type="trino",
        config=trino_config,
    )

    try:
        future = worker.submit(
            source=trino_source,
            output_size=DEFAULT_OUTPUT_SIZE,
            synthesizer_cls=settings.sdv_model_class,
            load_limit=DEFAULT_SAMPLE_SIZE,
        )  # May block up to 5s if at capacity
        asyncio_future = asyncio.wrap_future(future)
        synthetic_df_wrap: DataFrameWrapper = await asyncio_future
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )

    sample_data = SampleData.from_dataframe(df=synthetic_df_wrap.df_clean)
    await omd_async_client.add_sample_data(id=table_id, body=sample_data)
    return WebhookResponse(message="ok")
