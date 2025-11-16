from fastapi import FastAPI, status
from src.metrics.middleware import MetricsMiddleware
from src.app.lifespan import lifespan
from .api import router as api_router
from src.models import HealthResponse, HealthStatus

app = FastAPI(title="Synthetic Data Generator", lifespan=lifespan)
app.add_middleware(MetricsMiddleware)

app.include_router(router=api_router)


@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    return HealthResponse(status=HealthStatus.OK)
