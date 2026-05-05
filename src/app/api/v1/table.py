import asyncio
from fastapi import Depends, APIRouter, status
import pyarrow as pa
from src.core import SyntheticDataWorker
from src.config import Settings
from ...models import SyntheticRequest, SyntheticJSONResponse
from ...deps import get_worker_queue, get_app_settings


router = APIRouter(prefix="/table")


@router.post(
    "/generate",
    response_model=SyntheticJSONResponse,
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
    synthetic_data = await asyncio_future

    if isinstance(synthetic_data, pa.Table):
        return synthetic_data.to_pylist()
    return synthetic_data.to_dict()
