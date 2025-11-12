from fastapi import FastAPI
from contextlib import asynccontextmanager
from prometheus_client import make_asgi_app, REGISTRY
from src.core.synthetic_worker import SyntheticDataWorker
from src.metrics.collector import SystemMetricsCollector
import asyncio
from src.logger import LoggerFactory
from src.config import settings

logger = LoggerFactory.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.worker = SyntheticDataWorker(max_workers=settings.max_concurrent_synthetic_jobs)
    await app.state.worker.start()
    logger.info("Async worker queue started")

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

    await app.state.worker.stop()
    logger.info("Async worker queue stopped")
