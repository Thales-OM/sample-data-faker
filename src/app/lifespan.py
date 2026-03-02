from fastapi import FastAPI
from contextlib import asynccontextmanager
from prometheus_client import make_asgi_app, REGISTRY
from src.core.synthetic_worker import SyntheticDataWorker
from src.metrics.collector import SystemMetricsCollector
from src.destinations.openmetadata import AsyncOMDClient
import asyncio
from src.logger import LoggerFactory
from src.config import Settings

logger = LoggerFactory.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()

    app.state.settings = settings

    app.state.worker = SyntheticDataWorker(
        max_workers=settings.max_workers, max_pending=settings.max_pending,
    )
    logger.info("Worker queue started")

    if settings.openmetadata_destination:
        app.state.omd_async_client = AsyncOMDClient(
            config=settings.openmetadata_destination,
            logger=LoggerFactory.getLogger("root_omd_client"),
        )
        logger.info("Root Async OpenMetadata client created")
        # client_healthy, ex = await app.state.omd_async_client.is_healthy()
        # if not client_healthy:
        #     top_ex = RuntimeError("OpenMetadata connection not healthy")
        #     if isinstance(ex, BaseException):
        #         raise top_ex from ex
        #     raise top_ex
    else:
        app.state.omd_async_client = None
        logger.warning(
            "No configuration for OpenMetadata client was provided. Skipping."
        )

    metrics_app = make_asgi_app(registry=REGISTRY)
    app.mount("/metrics", metrics_app)
    system_collector = SystemMetricsCollector(registry=REGISTRY)

    async def refresh_system_metrics():
        while True:
            system_collector.collect()
            await asyncio.sleep(15)

    asyncio.create_task(refresh_system_metrics())
    logger.info("Prometheus metrics collector started")

    yield

    app.state.worker.shutdown(wait=True, timeout=60.0)
    logger.info("Async worker queue stopped")
