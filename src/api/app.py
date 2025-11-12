from fastapi import FastAPI, Depends, APIRouter, status, HTTPException
import pandas as pd
from src.core.synthetic_worker import SyntheticDataWorker
from src.models import SyntheticRequest, SyntheticResponse
from src.metrics.middleware import MetricsMiddleware
from src.api.lifespan import lifespan
from src.api.deps import get_worker_queue
import json

root_router = APIRouter(prefix="/api/v1")


@root_router.post(
    "/table/generate",
    response_model=SyntheticResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_synthetic(
    request: SyntheticRequest, worker: SyntheticDataWorker = Depends(get_worker_queue)
):
    try:
        future = await worker.enqueue_request(
            source=request.source,
            output_size=request.output_size,
            load_limit=request.load_limit,
        )
        synthetic_df: pd.DataFrame = await future
        return json.loads(synthetic_df.to_json(orient="records"))
    except Exception as e:
        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
                if "validation" in str(e).lower()
                else status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=str(e),
        )


@root_router.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    return {"status": "healthy"}


app = FastAPI(title="Synthetic Data Generator", lifespan=lifespan)
app.include_router(router=root_router)
app.add_middleware(MetricsMiddleware)
