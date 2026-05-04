import asyncio
from fastapi import APIRouter, status, Depends, HTTPException
from src.logger import LoggerFactory
from src.config import Settings
from src.destinations import (
    S3Destination,
    S3DestinationConfig,
    FileFormat,
    IcebergDestination,
    IcebergDestinationConfig,
)
from src.core import SyntheticDataWorker
from src.sources.avro_ocf import AvroOCFSourceConfig, AvroOCFSource
from ...models import (
    DTOAvroOCFRequest,
    DTOAvroOCFResponse,
    UploadStatus,
    S3UploadResult,
    IcebergUploadResult,
    BaseFastAPIErrorResponse,
)
from ...deps import get_worker_queue, get_app_settings


logger = LoggerFactory.getLogger(__name__)


router = APIRouter(prefix="/dto")


@router.post(
    "/avro-ocf",
    response_model=DTOAvroOCFResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": BaseFastAPIErrorResponse,
            "description": "Error occurred during pipeline or both destination uploads",
        }
    },
    summary="Generate and load synthetic dataset to S3 + Iceberg",
    description="Accept Apache Avro payload and upload generated "
    "dataset to preconfigured S3 bucket and Iceberg (HMS+S3) destinations.\n"
    "Single destination failure still responds with 200 OK. See individual statuses for info.",
)
async def generate_from_avro(
    body: DTOAvroOCFRequest,
    worker: SyntheticDataWorker = Depends(get_worker_queue),
    settings: Settings = Depends(get_app_settings),
):
    if not (settings.s3_destination or settings.hms_s3_destination):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No destinations configured for this endpoint.",
        )

    avro_ocf_source = AvroOCFSource(
        type="avro-ocf",
        config=AvroOCFSourceConfig(
            file_content=body.file_content, filename=body.filename
        ),
    )

    future = worker.submit(
        source=avro_ocf_source,
        output_size=body.output_size,
        synthesizer_cls=settings.sdv_model_class,
        load_limit=body.load_limit,
    )
    asyncio_future = asyncio.wrap_future(future)
    synthetic_data = await asyncio_future

    # Base case - no destination configured
    s3_file_upload = S3UploadResult(
        status=UploadStatus.SKIPPED, details=None, reason="not_configured", error=None
    )
    try:
        if settings.s3_destination:
            s3_config = S3DestinationConfig(
                filename=avro_ocf_source.title,
                prefix=avro_ocf_source.namespace,
                format=FileFormat.CSV,
                **settings.s3_destination.model_dump_with_secrets(mode="python")
            )
            s3_response = await S3Destination(type="s3", config=s3_config).submit(
                data=synthetic_data,
            )
            s3_file_upload = S3UploadResult(
                status=UploadStatus.SUCCESS,
                details=s3_response,
                reason=None,
                error=None,
            )
    except Exception as ex:
        logger.error(f"S3 upload failed: {ex}")
        s3_file_upload = S3UploadResult(
            status=UploadStatus.FAILED, details=None, reason="upload_failed", error=ex
        )

    iceberg_upload = IcebergUploadResult(
        status=UploadStatus.SKIPPED, details=None, reason="not_configured", error=None
    )
    try:
        if settings.hms_s3_destination:
            iceberg_config = IcebergDestinationConfig(
                namespace=avro_ocf_source.namespace,
                table_name=avro_ocf_source.title,
                **settings.hms_s3_destination.model_dump_with_secrets(mode="python"),
            )
            iceberg_response = await IcebergDestination(
                type="iceberg", config=iceberg_config
            ).submit(data=synthetic_data)
            iceberg_upload = IcebergUploadResult(
                status=UploadStatus.SUCCESS,
                details=iceberg_response,
                reason=None,
                error=None,
            )
    except Exception as ex:
        logger.error(f"Iceberg upload failed: {ex}")
        iceberg_upload = IcebergUploadResult(
            status=UploadStatus.FAILED, details=None, reason="upload_failed", error=ex
        )

    if (
        s3_file_upload.status == UploadStatus.FAILED
        and iceberg_upload.status == UploadStatus.FAILED
    ):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Both upload destinations failed.",
        )

    message = (
        "partial_success"
        if s3_file_upload.status == UploadStatus.FAILED
        or iceberg_upload.status == UploadStatus.FAILED
        else "ok"
    )
    return DTOAvroOCFResponse(
        message=message,
        s3_file_upload=s3_file_upload,
        iceberg_upload=iceberg_upload,
    )
