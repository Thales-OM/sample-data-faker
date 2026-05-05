from fastapi import Request, status, FastAPI
from fastapi.responses import JSONResponse
from ..models import BaseFastAPIErrorResponse


async def unhandled_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=BaseFastAPIErrorResponse(
            detail=f"[{exc.__class__.__name__}] Internal server error"
        ).model_dump(mode="json"),
    )


def register_global_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(Exception, unhandled_handler)
