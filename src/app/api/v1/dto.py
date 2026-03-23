import asyncio
from typing import Optional
from fastapi import APIRouter, HTTPException, status, Depends, File, Form
from src.logger import LoggerFactory
from src.config import Settings, DEFAULT_OUTPUT_SIZE
from src.destinations.s3 import S3Destination, FileFormat
from src.core import SyntheticDataWorker, DataFrameWrapper
from src.sources.avro_ocf import AvroOCFSourceConfig, AvroOCFSource
from ....models import AvroOCFResponse
from ...deps import get_worker_queue, get_app_settings


logger = LoggerFactory.getLogger(__name__)


router = APIRouter(prefix="/dto")


@router.post(
    "/avro-ocf",
    response_model=AvroOCFResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_from_avro(
    file: bytes = File(..., description="Avro OCF file (.avro)"),
    filename: Optional[str] = Form(None, description="Original filename"),
    output_size: int = Form(
        DEFAULT_OUTPUT_SIZE,
        ge=1,
        le=10000,
        description="How many rows to generate",
    ),
    load_limit: Optional[int] = Form(
        None, gt=0, description="Max records to sample from file"
    ),
    worker: SyntheticDataWorker = Depends(get_worker_queue),
    settings: Settings = Depends(get_app_settings),
):
    logger.info(f"Received raw bytes: size={len(file)}, filename={filename}")
    try:
        avro_ocf_source = AvroOCFSource(
            config=AvroOCFSourceConfig(file_content=file, filename=filename)
        )

        future = worker.submit(
            source=avro_ocf_source,
            output_size=output_size,
            synthesizer_cls=settings.sdv_model_class,
            load_limit=load_limit,
        )  # May block up to 1m if at capacity
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
