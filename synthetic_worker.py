import asyncio
from typing import Any, Dict, Optional
from concurrent.futures import ThreadPoolExecutor
from queue import Queue, Empty
import torch
import pandas as pd
import s3fs
from logger import LoggerFactory
from sdv.single_table import GaussianCopulaSynthesizer, CTGANSynthesizer
from sdv.metadata import SingleTableMetadata
from flatten import DataFrameFlattener
from config import settings

logger = LoggerFactory.getLogger(__name__)

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
        self._loop: Optional[asyncio.AbstractEventLoop] = None  # <-- Store main loop

    async def start(self):
        """Start background processor and capture main event loop."""
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._process_queue())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.executor.shutdown(wait=True)

    async def enqueue_request(self, s3_path: str, output_size: int) -> asyncio.Future:
        future = self._loop.create_future()  # <-- Use stored loop
        self.queue.put({"s3_path": s3_path, "future": future, "output_size": output_size})
        return future

    async def _process_queue(self):
        loop = asyncio.get_running_loop()
        while True:
            try:
                item = await loop.run_in_executor(None, self.queue.get, True, 1.0)
                # Pass loop to thread-safe callback
                self.executor.submit(self._process_item, item, self._loop)
            except Empty:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Queue processor error: %s", e)

    def _process_item(self, item: Dict[str, Any], loop: asyncio.AbstractEventLoop):
        s3_path = item["s3_path"]
        future = item["future"]
        output_size = item["output_size"]
        try:
            result = self._generate_synthetic_data(s3_path=s3_path, output_size=output_size)
            loop.call_soon_threadsafe(future.set_result, result)
        except Exception as e:
            loop.call_soon_threadsafe(future.set_exception, e)

    @staticmethod
    def _load_from_s3(s3_path: str) -> pd.DataFrame:
        ################################# Test #############################
        
        parquet_filename = "complex_input.parquet"
        df_loaded_parquet = pd.read_parquet(parquet_filename)
        return df_loaded_parquet

        ####################################################################

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
        
        return df

    def _generate_synthetic_data(self, s3_path: str, output_size: int) -> pd.DataFrame:
        """Load Iceberg table from S3, train SDV, generate sample, and clean up."""
        df = self._load_from_s3(s3_path=s3_path)
        print(df.head())

        flattener = DataFrameFlattener()
        df = flattener.flatten(df=df)
        print(df.head())

        synth_cls = SYNTHESIZER_MAP.get(settings.sdv_model_type)
        if not synth_cls:
            raise ValueError(f"Unsupported synthesizer: {settings.sdv_model_type}")

        # Create metadata from DataFrame
        metadata = SingleTableMetadata()
        metadata.detect_from_dataframe(df)

        # Model params
        model_params = settings.sdv_model_params.copy()

        # GPU handling for CTGAN
        if settings.sdv_model_type == "CTGANSynthesizer":
            model_params["cuda"] = torch.cuda.is_available()

        # Instantiate with metadata
        synthesizer = synth_cls(
            metadata=metadata,
            **model_params
        )

        logger.info("Fitting synthesizer...")
        synthesizer.fit(df)

        logger.info("Generating %d synthetic rows...", output_size)
        synthetic_df = synthesizer.sample(num_rows=output_size)

        if settings.cleanup_on_complete:
            del synthesizer
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        return flattener.unflatten(flat_df=synthetic_df)
