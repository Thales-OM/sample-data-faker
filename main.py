from fastapi import FastAPI, Depends, APIRouter, status
import pandas as pd
from synthetic_worker import SyntheticDataWorker
from lifespan import lifespan
from utils import get_s3_iceberg_path
from deps import get_worker_queue

root_router = APIRouter(prefix="/api/v1")


@root_router.post(
    "/table/generate/name/{fullyQualifiedName}", status_code=status.HTTP_201_CREATED
)
async def generate_synthetic(
    fullyQualifiedName: str, worker: SyntheticDataWorker = Depends(get_worker_queue)
):
    s3_path = get_s3_iceberg_path(table_fqn=fullyQualifiedName)
    future = await worker.enqueue_request(s3_path)
    synthetic_df: pd.DataFrame = await future
    return synthetic_df.to_dict(orient="records")

app = FastAPI(title="Synthetic Data Generator", lifespan=lifespan)
app.include_router(router=root_router)
