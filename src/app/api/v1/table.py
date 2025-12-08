from fastapi import Depends, APIRouter, status, HTTPException
import pandas as pd
from src.core.synthetic_worker import SyntheticDataWorker
from src.models import SyntheticRequest, SyntheticResponse
from src.app.deps import get_worker_queue
import json


router = APIRouter(prefix="/table")


@router.post(
    "/generate",
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
