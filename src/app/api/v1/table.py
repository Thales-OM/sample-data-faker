from fastapi import Depends, APIRouter, status, HTTPException
from src.core import SyntheticDataWorker, DataFrameWrapper
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
        synthetic_df_wrap: DataFrameWrapper = await future
        # FIXME: heavy dataframe to json conversion
        return json.loads(synthetic_df_wrap.df.to_json(orient="records", date_format="iso", index=False))
    except Exception as e:
        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
                if "validation" in str(e).lower()
                else status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=str(e),
        )
