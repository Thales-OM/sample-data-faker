"""
FastAPI exception handlers for synthetic worker errors.
Maps API-agnostic WorkerError subclasses to HTTP responses.
"""

from fastapi import Request, status, FastAPI
from fastapi.responses import JSONResponse
from src.core.exceptions import WorkerError, WorkerCapacityError, GenerationError
from src.logger import LoggerFactory

logger = LoggerFactory.getLogger(__name__)


class ErrorDetail:
    """Typed error detail for JSON responses"""

    def __init__(
        self,
        error_type: str,
        message: str,
        status_code: int,
        details: dict | None = None,
    ):
        self.error_type = error_type
        self.message = message
        self.status_code = status_code
        self.details = details or {}

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict"""
        result = {
            "error": self.error_type,
            "message": self.message,
        }
        if self.details:
            result["details"] = self.details
        return result

    def to_headers(self) -> dict[str, str]:
        """Convert to HTTP headers"""
        headers = {}
        return headers


async def worker_capacity_handler(
    request: Request, exc: WorkerCapacityError
) -> JSONResponse:
    """
    Handle WorkerCapacityError → HTTP 503 Service Unavailable.
    """
    error = ErrorDetail(
        error_type="worker_at_capacity",
        message="All generation slots are currently busy. Please retry shortly.",
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        details={
            "pending_tasks": exc.pending,
            "max_pending": exc.max_pending,
            "utilization": (
                f"{exc.pending / exc.max_pending * 100:.0f}%"
                if exc.max_pending > 0
                else "N/A"
            ),
        },
    )

    logger.warning(
        f"Worker capacity exceeded: {exc.pending}/{exc.max_pending} pending",
        extra={
            "path": request.url.path,
            "method": request.method,
            "client": request.client.host if request.client else "unknown",
        },
    )

    return JSONResponse(
        status_code=error.status_code,
        content=error.to_dict(),
        headers=error.to_headers(),
    )


async def generation_error_handler(
    request: Request, exc: GenerationError
) -> JSONResponse:
    """
    Handle GenerationError → HTTP 500 Internal Server Error.

    Log full details server-side; return sanitized message to client.
    """
    error = ErrorDetail(
        error_type="generation_failed",
        message="Failed to generate synthetic data. Please check your input and try again.",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        details={
            # Safe to expose: high-level error category
            "category": _categorize_generation_error(exc.cause),
        },
    )

    # Log full error server-side (with stack trace)
    logger.error(
        f"Synthetic generation failed: {exc}",
        exc_info=exc.cause,
        extra={
            "path": request.url.path,
            "method": request.method,
            "error_type": (
                type(exc.cause).__name__
                if exc.cause
                else "Unknown"
            ),
        },
    )

    return JSONResponse(
        status_code=error.status_code,
        content=error.to_dict(),
    )


async def worker_error_handler(request: Request, exc: WorkerError) -> JSONResponse:
    """
    Fallback handler for any other WorkerError subclasses.

    Maps to 500 with generic message.
    """
    error = ErrorDetail(
        error_type="worker_error",
        message="An internal error occurred while processing your request.",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )

    logger.error(
        f"Unhandled worker error: {exc}",
        exc_info=True,
        extra={"path": request.url.path, "method": request.method},
    )

    return JSONResponse(
        status_code=error.status_code,
        content=error.to_dict(),
    )


def _categorize_generation_error(original: Exception | None) -> str:
    """
    Map low-level exceptions to high-level categories for client feedback.
    Never expose raw exception types or stack traces.
    """
    if original is None:
        return "unknown"

    error_type = type(original).__name__

    # Input/data issues (client can fix)
    if error_type in ("ValueError", "KeyError", "TypeError"):
        return "invalid_input"
    if "schema" in str(original).lower():
        return "schema_error"
    if "memory" in str(original).lower() or error_type == "MemoryError":
        return "resource_exhausted"

    # SDV-specific issues
    if "sdv" in str(original).lower() or error_type in (
        "ConstraintsNotMetError",
        "InvalidDataError",
    ):
        return "model_configuration_error"

    # I/O issues
    if error_type in ("FileNotFoundError", "PermissionError", "OSError"):
        return "io_error"

    # Default: server-side issue
    return "internal_error"


def register_worker_exception_handlers(app: FastAPI) -> None:
    """
    Register all worker exception handlers with a FastAPI app.

    Usage:
        from src.app.exception_handlers import register_worker_exception_handlers
        register_worker_exception_handlers(app)
    """
    app.add_exception_handler(WorkerCapacityError, worker_capacity_handler)
    app.add_exception_handler(GenerationError, generation_error_handler)
    app.add_exception_handler(WorkerError, worker_error_handler)
