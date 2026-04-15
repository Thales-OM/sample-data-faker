import json
import asyncio
from fastapi import Depends, APIRouter, status
from src.core import SyntheticDataWorker, DataFrameWrapper
from src.config import Settings
from ...models import SyntheticRequest, SyntheticResponse
from ...deps import get_worker_queue, get_app_settings


router = APIRouter(prefix="/table")


@router.post(
    "/generate",
    response_model=SyntheticResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate synthetic dataset from custom source",
)
async def generate_synthetic(
    request: SyntheticRequest,
    worker: SyntheticDataWorker = Depends(get_worker_queue),
    settings: Settings = Depends(get_app_settings),
):
    future = worker.submit(
        source=request.source,
        output_size=request.output_size,
        synthesizer_cls=settings.sdv_model_class,
        load_limit=request.load_limit,
    )
    asyncio_future = asyncio.wrap_future(future)
    synthetic_df_wrap: DataFrameWrapper = await asyncio_future

    # FIXME: heavy dataframe to json conversion
    return json.loads(
        synthetic_df_wrap.df_clean.to_json(
            orient="records", date_format="iso", index=False
        )
    )
