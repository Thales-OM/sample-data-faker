from fastapi import FastAPI, Depends, APIRouter, status, HTTPException
import pandas as pd
from synthetic_worker import SyntheticDataWorker
from models import SyntheticRequest, SyntheticResponse
from lifespan import lifespan
from utils import get_s3_iceberg_path
from deps import get_worker_queue
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
    # Extract source type and config
    source_obj = request.source
    source_type = source_obj.type
    source_config = source_obj.model_dump(mode="python")
    # Remove the injected 'type' field before passing to worker
    source_config.pop("type")

    try:
        future = await worker.enqueue_request(
            source_config={"type": source_type, **source_config},
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


app = FastAPI(title="Synthetic Data Generator", lifespan=lifespan)
app.include_router(router=root_router)
