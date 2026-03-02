import sys
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Optional, Type
import torch
from sdv.metadata import SingleTableMetadata
from sdv.single_table.base import BaseSynthesizer
from sdv.single_table import CTGANSynthesizer
from src.logger import LoggerFactory
from src.sources import DataSource
from .flatten import DataFrameFlattener
from .dataframe_wrapper import DataFrameWrapper
from .exceptions import WorkerCapacityError, GenerationError
from .singleton import Singleton


logger = LoggerFactory.getLogger(__name__)


class SyntheticDataWorker(Singleton):
    """
    A single entrypoint class to schedule, limit and submit synthetic data generation workloads.
    """

    def __init__(self, max_workers: int, max_pending: int = 10):
        self.max_workers = max_workers
        self.max_pending = max_pending

        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="synthetic-worker"
        )

        self._pending_count = 0
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)

        logger.info(
            f"Worker initialized: {max_workers} threads, {max_pending} max pending"
        )

    def submit(
        self,
        source: DataSource,
        output_size: int,
        synthesizer_cls: Type[BaseSynthesizer],
        load_limit: Optional[int] = None,
        model_params: Optional[dict] = None,
    ) -> Future:
        """
        Submit a generation task. Returns a Future that resolves to DataFrameWrapper.

        Blocks (with timeout) if pending tasks exceed max_pending.
        """
        with self._condition:
            # Wait for a slot to become available (with timeout)
            acquired = self._condition.wait_for(
                lambda: self._pending_count < self.max_pending, timeout=5.0
            )

            if not acquired:
                raise WorkerCapacityError(
                    f"Worker at capacity: {self._pending_count}/{self.max_pending} pending",
                    pending=self._pending_count,
                    max_pending=self.max_pending,
                )

            # Reserve a slot
            self._pending_count += 1

        # Submit to thread pool (outside lock to avoid holding it during submission)
        future = self._executor.submit(
            self._generate_with_cleanup,
            source=source,
            output_size=output_size,
            load_limit=load_limit,
            model_params=model_params or {},
            synthesizer_cls=synthesizer_cls,
        )

        # Callback to release slot when done
        def _on_complete(f: Future):
            with self._condition:
                self._pending_count -= 1
                self._condition.notify_all()  # Wake up any waiting submit() calls
            # Log unhandled errors
            if f.exception() and not f.cancelled():
                logger.warning(f"Task completed with error: {f.exception()}")

        future.add_done_callback(_on_complete)
        return future

    def _generate_with_cleanup(self, **kwargs) -> DataFrameWrapper:
        """Wrapper with error handling and cleanup"""
        try:
            return self._generate_synthetic_data(**kwargs)
        except Exception as e:
            logger.exception("Generation failed")
            raise GenerationError(
                f"Synthetic generation failed: {str(e)}", original_exception=e
            ) from e

    def _generate_synthetic_data(
        self,
        source: DataSource,
        output_size: int,
        synthesizer_cls: Type[BaseSynthesizer],
        load_limit: Optional[int],
        model_params: dict,
    ) -> DataFrameWrapper:
        df = source.load_dataframe(limit=load_limit)
        logger.info(f"Loaded {len(df)} rows from {source.type}")

        if df.empty:
            raise GenerationError("No valid records loaded from source")

        flattener = DataFrameFlattener()
        df_flat = flattener.flatten(df)

        metadata = SingleTableMetadata()
        metadata.detect_from_dataframe(df_flat)

        params = model_params.copy()

        if synthesizer_cls is CTGANSynthesizer:
            params["cuda"] = torch.cuda.is_available()

        synthesizer = synthesizer_cls(metadata=metadata, **params)
        synthesizer.fit(df_flat)
        synthetic_flat = synthesizer.sample(num_rows=output_size)
        synthetic_df = flattener.unflatten(synthetic_flat)

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        del synthesizer

        return DataFrameWrapper(df=synthetic_df)

    @property
    def pending_count(self) -> int:
        """Number of tasks currently pending or in progress"""
        with self._lock:
            return self._pending_count

    @property
    def available_slots(self) -> int:
        """Number of additional tasks that can be submitted"""
        with self._lock:
            return self.max_pending - self._pending_count

    @property
    def is_at_capacity(self) -> bool:
        """Check if worker cannot accept more tasks"""
        with self._lock:
            return self._pending_count >= self.max_pending

    def shutdown(self, wait: bool = True, timeout: Optional[float] = None):
        """Shutdown worker and release resources"""
        logger.info(f"Shutting down worker (pending={self.pending_count})")

        cancel_futures = not wait and sys.version_info >= (3, 9)
        self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)
        logger.info("Worker shutdown complete")
