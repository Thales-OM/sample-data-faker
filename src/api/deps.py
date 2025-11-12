from fastapi import Request
from src.core.synthetic_worker import SyntheticDataWorker

def get_worker_queue(request: Request) -> SyntheticDataWorker:
    return request.app.state.worker
