from fastapi import FastAPI
from contextlib import asynccontextmanager
from synthetic_worker import SyntheticDataWorker
from logger import LoggerFactory
from config import settings

logger = LoggerFactory.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.worker = SyntheticDataWorker(max_workers=settings.max_concurrent_synthetic_jobs)
    await app.state.worker.start()
    logger.info("Async worker queue started")

    yield

    await app.state.worker.stop()
    logger.info("Async worker queue stopped")
