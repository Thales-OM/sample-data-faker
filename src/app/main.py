from fastapi import FastAPI, status, APIRouter
from src.metrics.middleware import MetricsMiddleware
from src.app.lifespan import lifespan
from .api import router as api_router
from src.models import ReadinessResponse, LivenessResponse

root_router = APIRouter()


@root_router.get(
    "/readiness", response_model=ReadinessResponse, status_code=status.HTTP_200_OK
)
async def readiness():
    return ReadinessResponse("OK!")


@root_router.get(
    "/liveness", response_model=LivenessResponse, status_code=status.HTTP_200_OK
)
async def liveness():
    return LivenessResponse("OK!")


def create_app() -> FastAPI:
    app = FastAPI(title="Synthetic Data Generator", lifespan=lifespan)
    app.add_middleware(MetricsMiddleware)
    app.include_router(router=root_router)
    app.include_router(router=api_router)
    return app
