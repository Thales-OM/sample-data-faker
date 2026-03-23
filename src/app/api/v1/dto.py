import asyncio
from fastapi import APIRouter, HTTPException, status, Depends
from src.logger import LoggerFactory
from src.config import Settings
from src.destinations.s3 import S3Destination, FileFormat
from src.core import SyntheticDataWorker, DataFrameWrapper
from src.sources.avro_ocf import AvroOCFSourceConfig, AvroOCFSource
from ....models import DTOAvroOCFRequest, AvroOCFResponse
from ...deps import get_worker_queue, get_app_settings


logger = LoggerFactory.getLogger(__name__)


router = APIRouter(prefix="/dto")


@router.post(
    "/avro-ocf",
    response_model=AvroOCFResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_from_avro(
    body: DTOAvroOCFRequest,
    worker: SyntheticDataWorker = Depends(get_worker_queue),
    settings: Settings = Depends(get_app_settings),
):
    logger.info(
        f"Received raw bytes: size={len(body.file_content)}, filename={body.filename}"
    )
    try:
        avro_ocf_source = AvroOCFSource(
            config=AvroOCFSourceConfig(
                file_content=body.file_content, filename=body.filename
            )
        )

        future = worker.submit(
            source=avro_ocf_source,
            output_size=body.output_size,
            synthesizer_cls=settings.sdv_model_class,
            load_limit=body.load_limit,
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
