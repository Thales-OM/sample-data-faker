from typing import Union, Annotated
from fastapi import Depends, APIRouter, status, HTTPException
from fastapi.responses import JSONResponse
from pydantic import Field
import pandas as pd
from src.core.synthetic_worker import SyntheticDataWorker
from src.models import (
    SyntheticRequest,
    OpenMetadataPopulateResponse,
    SampleData,
    WebhookTableCreated,
    WebhookTableUpdated,
    WebhookResponse,
)
from src.openmetadata import AsyncOMDClient
from src.app.deps import get_worker_queue, get_omd_async_client
from src.sources.trino import TrinoSource, TrinoSourceConfig
from src.utils import openmetadata_to_dto_table
from src.constants import DEFAULT_SAMPLE_SIZE, DEFAULT_OUTPUT_SIZE
from src.config import settings


router = APIRouter(prefix="/openmetadata")


@router.post(
    "/generate/{table_fqn}",
    response_model=OpenMetadataPopulateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_synthetic(
    request: SyntheticRequest,
    table_fqn: str,
    omd_async_client: AsyncOMDClient = Depends(get_omd_async_client),
    worker: SyntheticDataWorker = Depends(get_worker_queue),
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
        future = await worker.enqueue_request(
            source=request.source,
            output_size=request.output_size,
            load_limit=request.load_limit,
        )
        synthetic_df: pd.DataFrame = await future
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )

    sample_data = SampleData.from_dataframe(df=synthetic_df)
    await omd_async_client.add_sample_data(id=table_id, body=sample_data)
    return OpenMetadataPopulateResponse(
        table_fqn=table_fqn, table_id=table_id, output_size=len(synthetic_df)
    )


WebhookTableUnionType = Annotated[
    Union[WebhookTableCreated, WebhookTableUpdated], Field(discriminator="eventType")
]


@router.post("/webhook", status_code=status.HTTP_201_CREATED)
async def webhook(
    body: WebhookTableUnionType,
    omd_async_client: AsyncOMDClient = Depends(get_omd_async_client),
    worker: SyntheticDataWorker = Depends(get_worker_queue),
):
    if isinstance(body, WebhookTableUpdated) and not body.is_schema_change():
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=WebhookResponse(message="received, no action needed")
        )
    
    if not settings.trino:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Trino connection is unavailable")
    
    table_id = body.entityId
    table = await omd_async_client.get_table_by_id(id=table_id, fields="fullyQualifiedName", nullable=True)
    if not table:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Table not found in OpenMetadata",
        )
    table_fqn = table["fullyQualifiedName"]

    dto_table_full_name = openmetadata_to_dto_table(table_fqn=table_fqn, trino_catalog=settings.trino.catalog)
    catalog, schema, table_name = dto_table_full_name.split(".")
    trino_config = TrinoSourceConfig(
        host=settings.trino.host,
        port=settings.trino.port,
        user=settings.trino.user,
        password=settings.trino.password.get_secret_value() if settings.trino.password else None,
        catalog=catalog,
        schema=schema,
        table=table_name,
    )
    trino_source = TrinoSource(
        type="trino",
        config=trino_config,
    )

    try:
        future = await worker.enqueue_request(
            source=trino_source,
            output_size=DEFAULT_OUTPUT_SIZE,
            load_limit=DEFAULT_SAMPLE_SIZE,
        )
        synthetic_df: pd.DataFrame = await future
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    
    sample_data = SampleData.from_dataframe(df=synthetic_df)
    await omd_async_client.add_sample_data(id=table_id, body=sample_data)
    return WebhookResponse(message="ok")
