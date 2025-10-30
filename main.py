from fastapi import FastAPI, Depends, APIRouter, status
import pandas as pd
from synthetic_worker import SyntheticDataWorker
from lifespan import lifespan
from utils import get_s3_iceberg_path, to_python_native
from deps import get_worker_queue
import json

root_router = APIRouter(prefix="/api/v1")


@root_router.post(
    "/table/generate/name/{fullyQualifiedName}", status_code=status.HTTP_201_CREATED
)
async def generate_synthetic(
    fullyQualifiedName: str, worker: SyntheticDataWorker = Depends(get_worker_queue)
):
    s3_path = get_s3_iceberg_path(table_fqn=fullyQualifiedName)
    future = await worker.enqueue_request(s3_path=s3_path, output_size=10)
    synthetic_df: pd.DataFrame = await future
    # records = [
    #     {k: to_python_native(v) for k, v in row.items()}
    #     for row in synthetic_df.to_dict(orient="records")
    # ]
    # return records
    return json.loads(synthetic_df.to_json(orient="records"))

app = FastAPI(title="Synthetic Data Generator", lifespan=lifespan)
app.include_router(router=root_router)
