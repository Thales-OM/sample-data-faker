from typing import Optional


class WorkerError(Exception):
    """Base exception for worker errors"""

    pass


class WorkerCapacityError(WorkerError):
    """Raised when worker cannot accept more tasks"""

    def __init__(self, message: str, pending: int, max_pending: int):
        super().__init__(message)
        self.pending = pending
        self.max_pending = max_pending


class GenerationError(WorkerError):
    """Raised when synthetic data generation fails"""

    def __init__(self, message: str, cause: Optional[Exception] = None):
        super().__init__(message)
        self.cause = cause
