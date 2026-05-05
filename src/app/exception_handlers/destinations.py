from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from src.destinations import IcebergDestinationError
from src.logger import LoggerFactory
from .base import ErrorDetail

logger = LoggerFactory.getLogger(__name__)


def _categorize_iceberg_error(original: Exception) -> str:
    """
    Map Iceberg/storage exceptions to high-level categories.
    Never expose raw exception types or internal paths.
    """
    error_type = type(original).__name__
    error_msg = str(original).lower()

    # Table existence issues
    if "no such table" in error_msg or "table not found" in error_msg:
        return "table_not_found"

    # Schema compatibility issues
    if (
        "schema" in error_msg
        or "incompatible" in error_msg
        or "type mismatch" in error_msg
        or error_type in ("SchemaMismatchError", "ValueError")
    ):
        return "schema_conflict"

    # Resource/availability issues
    if (
        "timeout" in error_msg
        or "connection" in error_msg
        or "unavailable" in error_msg
        or error_type in ("ConnectionError", "TimeoutError")
    ):
        return "resource_exhausted"

    # I/O and storage issues
    if (
        "permission" in error_msg
        or "access" in error_msg
        or "s3" in error_msg
        or "bucket" in error_msg
        or error_type in ("PermissionError", "OSError", "ClientError")
    ):
        return "io_error"

    # Commit conflicts (concurrent writes)
    if "commit" in error_msg or "conflict" in error_msg:
        return "commit_conflict"

    # Default: internal error
    return "internal_error"


async def iceberg_destination_error_handler(
    request: Request, exc: IcebergDestinationError
) -> JSONResponse:
    """
    Handle IcebergDestinationError → HTTP 500 or 503 based on error type.

    Provides detailed information about the failed operation
    while keeping internal paths and credentials hidden.
    """
    # Determine status code based on error category
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_type = "iceberg_destination_error"
    message = "Failed to write data to Iceberg table."

    details = {
        "table": exc.table_identifier or "unknown",
        "operation": exc.operation or "unknown",
    }

    # Categorize error for client feedback
    if exc.cause:
        error_category = _categorize_iceberg_error(exc.cause)
        details["category"] = error_category

        if error_category == "table_not_found":
            message = f"Table '{exc.table_identifier}' does not exist and could not be created."
        elif error_category == "schema_conflict":
            message = "Schema incompatibility detected. Please check table schema."
        elif error_category == "io_error":
            message = "Failed to access storage. Please check your configuration."
        elif error_category == "resource_exhausted":
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            message = "Iceberg service is currently unavailable. Please retry shortly."

    error = ErrorDetail(
        error_type=error_type,
        message=message,
        status_code=status_code,
        details=details,
    )

    logger.error(
        f"Iceberg destination error: {exc}",
        exc_info=exc.cause,
        extra={
            "path": request.url.path,
            "method": request.method,
            "table": exc.table_identifier,
            "operation": exc.operation,
        },
    )

    return JSONResponse(
        status_code=error.status_code,
        content=error.to_dict(),
    )


def register_destination_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(
        IcebergDestinationError, iceberg_destination_error_handler
    )
