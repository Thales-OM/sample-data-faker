from fastapi import Request
from src.core.synthetic_worker import SyntheticDataWorker
from src.destinations.openmetadata import AsyncOMDClient


def get_worker_queue(request: Request) -> SyntheticDataWorker:
    return request.app.state.worker


def get_omd_async_client(request: Request) -> AsyncOMDClient:
    client = request.app.state.omd_async_client
    if not client:
        raise RuntimeError(
            "OpenMetadata client not found. Perhaps it was not declared in configuration."
        )
    return client
