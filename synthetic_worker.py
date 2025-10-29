import asyncio
import logging
from typing import Any, Dict, Optional
from concurrent.futures import ThreadPoolExecutor
from queue import Queue, Empty
import torch
import pandas as pd
import s3fs
from sdv.single_table import GaussianCopulaSynthesizer, CTGANSynthesizer
from config import Settings

logger = logging.getLogger(__name__)
settings = Settings()

# Supported synthesizers
SYNTHESIZER_MAP = {
    "GaussianCopulaSynthesizer": GaussianCopulaSynthesizer,
    "CTGANSynthesizer": CTGANSynthesizer,
}


class SyntheticDataWorker:
    def __init__(self, max_workers: int):
        self.max_workers = max_workers
        self.queue: Queue[Dict[str, Any]] = Queue()
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the background worker loop."""
        if self._task is None:
            self._task = asyncio.create_task(self._process_queue())

    async def stop(self):
        """Gracefully stop the worker."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.executor.shutdown(wait=True)

    async def enqueue_request(self, s3_path: str) -> asyncio.Future:
        """Enqueue a synthetic data request and return a future."""
        future = asyncio.Future()
        self.queue.put({"s3_path": s3_path, "future": future})
        return future

    async def _process_queue(self):
        """Background coroutine that processes the FIFO queue."""
        loop = asyncio.get_running_loop()
        while True:
            try:
                # Use a timeout to allow periodic checks for cancellation
                item = await loop.run_in_executor(None, self.queue.get, True, 1.0)
                # Submit to thread pool
                loop.run_in_executor(self.executor, self._process_item, item)
            except Empty:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Error in queue processor: %s", e)

    def _process_item(self, item: Dict[str, Any]):
        """Process a single item in a thread."""
        s3_path = item["s3_path"]
        future = item["future"]
        try:
            result = self._generate_synthetic_data(s3_path)
            asyncio.run_coroutine_threadsafe(future.set_result(result), asyncio.get_event_loop())
        except Exception as e:
            asyncio.run_coroutine_threadsafe(future.set_exception(e), asyncio.get_event_loop())

    def _generate_synthetic_data(self, s3_path: str) -> pd.DataFrame:
        """Load Iceberg table from S3, train SDV, generate sample, and clean up."""
        logger.info("Loading data from S3: %s", s3_path)

        # Setup S3 filesystem
        s3_kwargs = {}
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            s3_kwargs.update(
                key=settings.aws_access_key_id,
                secret=settings.aws_secret_access_key,
            )
        if settings.aws_region:
            s3_kwargs["client_kwargs"] = {"region_name": settings.aws_region}

        fs = s3fs.S3FileSystem(**s3_kwargs)

        # Load Iceberg table as pandas DataFrame
        # Note: Iceberg metadata isn't directly readable by pandas.
        # You may need to use PyIceberg or convert to Parquet first.
        # For simplicity, assume the path points to Parquet files.
        df = pd.read_parquet(s3_path, filesystem=fs)

        logger.info("Loaded %d rows from %s", len(df), s3_path)

        # Determine output size
        output_size = int(len(df) * settings.synthetic_output_size_multiplier)

        # Select synthesizer
        synth_cls = SYNTHESIZER_MAP.get(settings.sdv_model_type)
        if not synth_cls:
            raise ValueError(f"Unsupported synthesizer: {settings.sdv_model_type}")

        # Configure device
        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("Using device: %s", device)

        # Special handling for CTGAN (uses torch)
        model_params = settings.sdv_model_params.copy()
        if settings.sdv_model_type == "CTGANSynthesizer":
            model_params["cuda"] = torch.cuda.is_available()

        synthesizer = synth_cls(**model_params)
        synthesizer.fit(df)

        logger.info("Model trained. Generating %d synthetic rows...", output_size)
        synthetic_df = synthesizer.sample(num_rows=output_size)

        if settings.cleanup_on_complete:
            del synthesizer
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        return synthetic_df
