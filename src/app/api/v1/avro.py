from typing import Optional
import asyncio
from fastapi import APIRouter, File, UploadFile, HTTPException, status, Depends, Form
from src.logger import LoggerFactory
from src.config import Settings, DEFAULT_OUTPUT_SIZE
from src.destinations.s3 import S3Destination, FileFormat
from src.core import SyntheticDataWorker, DataFrameWrapper
from src.sources.avro_ocf import AvroOCFSourceConfig, AvroOCFSource
from ....models import AvroOCFResponse
from ...deps import get_worker_queue, get_app_settings


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
    settings: Settings = Depends(get_app_settings),
):
    try:
        avro_ocf_source = AvroOCFSource(config=AvroOCFSourceConfig(file=file))

        future = worker.submit(
            source=avro_ocf_source,
            output_size=output_size,
            synthesizer_cls=settings.sdv_model_class,
            load_limit=load_limit,
        )  # May block up to 5s if at capacity
        asyncio_future = asyncio.wrap_future(future)
        synthetic_df_wrap: DataFrameWrapper = await asyncio_future

        s3_response = await S3Destination(config=settings.s3_destination).submit(
            df=synthetic_df_wrap.df_clean,
            filename=avro_ocf_source.title,
            prefix=avro_ocf_source.namespace,
            format=FileFormat.CSV,
        )

        return AvroOCFResponse(message="ok", s3_path=s3_response.s3_key)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
