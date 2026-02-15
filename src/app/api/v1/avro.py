from typing import Optional
from fastapi import APIRouter, File, UploadFile, HTTPException, status, Depends, Form
from src.logger import LoggerFactory
from src.config import settings, DEFAULT_OUTPUT_SIZE
from src.destinations.s3 import S3Writer
from src.core import SyntheticDataWorker, DataFrameWrapper
from src.sources.avro_ocf import AvroOCFSourceConfig, AvroOCFSource
from ....models import AvroOCFResponse
from ...deps import get_worker_queue


logger = LoggerFactory.getLogger(__name__)


router = APIRouter(prefix="/avro")


@router.post(
    "/ocf",
    response_model=AvroOCFResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_from_avro(
    file: UploadFile = File(..., description="Avro OCF file (.avro)"),
    output_size: int = Form(
        DEFAULT_OUTPUT_SIZE,
        ge=1,
        le=10000,
        description="Max records to produce in output",
    ),
    load_limit: Optional[int] = Form(
        None, ge=1, description="Max records to sample from file"
    ),
    worker: SyntheticDataWorker = Depends(get_worker_queue),
):
    try:
        avro_ocf_source = AvroOCFSource(config=AvroOCFSourceConfig(file=file))
        future = await worker.enqueue_request(
            source=avro_ocf_source,
            output_size=output_size,
            load_limit=load_limit,
        )
        synthetic_df_wrap: DataFrameWrapper = await future

        s3_object_key = await S3Writer(config=settings.s3_destination).upload(
            df=synthetic_df_wrap.df_clean,
            filename=avro_ocf_source.title,
            prefix=avro_ocf_source.namespace,
        )

        return AvroOCFResponse(message="ok", s3_path=s3_object_key)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
