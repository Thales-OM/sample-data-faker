from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from src.logger import LoggerFactory


logger = LoggerFactory.getLogger(__name__)


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Custom exception handler for RequestValidationError
    (FastAPI's internal error for request body validation)
    """
    logger.error(f"Validation error occurred for request: {request.url}")
    try:
        # Attempt to get the request body to log the offending input data
        body = await request.json()
        logger.error(f"Request body causing error: {body}")
    except Exception:
        logger.error("Could not parse request body for logging")

    error_details = exc.errors()
    logger.error(f"Full error details: {error_details}")

    # Return a custom JSON response to the client
    return JSONResponse(
        status_code=422,
        content={
            "detail": "A detailed validation error occurred.",
            "errors": error_details,
        },
    )


async def pydantic_validation_handler(request: Request, exc: ValidationError):
    """
    Handle direct Pydantic ValidationErrors if model.model_validate() is called manually
    """
    logger.error(f"Manual Pydantic validation error: {exc.json()}")
    return JSONResponse(
        status_code=422,
        content={
            "detail": "A manual pydantic validation error occurred",
            "errors": exc.errors(),
        },
    )


def register_validation_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(ValidationError, pydantic_validation_handler)
