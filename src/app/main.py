from fastapi import FastAPI, status, APIRouter, Depends, HTTPException, Request
from src.metrics.middleware import MetricsMiddleware
from src.core import SyntheticDataWorker
from src.models import ReadinessResponse, LivenessResponse, VersionResponse
from src.config import APP_VERSION
from .lifespan import lifespan
from .api import router as api_router
from .deps import get_worker_queue
from .exception_handlers import (
    register_worker_exception_handlers,
    register_validation_exception_handlers,
)


root_router = APIRouter()


@root_router.get(
    "/readiness", response_model=ReadinessResponse, status_code=status.HTTP_200_OK
)
async def readiness(worker: SyntheticDataWorker = Depends(get_worker_queue)):
    if worker.is_at_capacity:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service is at max capacity",
        )
    return ReadinessResponse("OK!")


@root_router.get(
    "/liveness", response_model=LivenessResponse, status_code=status.HTTP_200_OK
)
async def liveness():
    return LivenessResponse("OK!")


@root_router.get(
    "/version", response_model=VersionResponse, status_code=status.HTTP_200_OK
)
async def version(request: Request):
    return VersionResponse(version=request.app.version)


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    All static configuration belongs here:
    - Middleware
    - Exception handlers
    - Routers
    - Dependencies
    """
    app = FastAPI(
        title="Synthetic Data Generator", lifespan=lifespan, version=APP_VERSION
    )

    app.add_middleware(MetricsMiddleware)

    register_worker_exception_handlers(app=app)
    register_validation_exception_handlers(app=app)

    app.include_router(router=root_router)
    app.include_router(router=api_router)

    return app
