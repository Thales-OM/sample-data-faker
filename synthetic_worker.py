import asyncio
from typing import Any, Dict, Optional
from concurrent.futures import ThreadPoolExecutor
from queue import Queue, Empty
import torch
import pandas as pd
from logger import LoggerFactory
from sdv.single_table import GaussianCopulaSynthesizer, CTGANSynthesizer
from sdv.metadata import SingleTableMetadata
from flatten import DataFrameFlattener
from config import settings
from sources import get_source_loader

logger = LoggerFactory.getLogger(__name__)

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
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def start(self):
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

    async def enqueue_request(
        self,
        source_config: Dict[str, Any],
        output_size: int,
        load_limit: Optional[int] = None,
    ) -> asyncio.Future:
        future = self._loop.create_future()
        self.queue.put(
            {
                "source_config": source_config,
                "output_size": output_size,
                "load_limit": load_limit,
                "future": future,
            }
        )
        return future

    async def _process_queue(self):
        loop = asyncio.get_running_loop()
        while True:
            try:
                item = await loop.run_in_executor(None, self.queue.get, True, 1.0)
                self.executor.submit(self._process_item, item, self._loop)
            except Empty:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Queue processor error: %s", e)

    def _process_item(self, item: Dict[str, Any], loop: asyncio.AbstractEventLoop):
        try:
            result = self._generate_synthetic_data(
                source_config=item["source_config"],
                output_size=item["output_size"],
                load_limit=item["load_limit"],
            )
            loop.call_soon_threadsafe(item["future"].set_result, result)
        except Exception as e:
            loop.call_soon_threadsafe(item["future"].set_exception, e)

    def _generate_synthetic_data(
        self,
        source_config: Dict[str, Any],
        output_size: int,
        load_limit: Optional[int] = None,
    ) -> pd.DataFrame:
        source_type = source_config.pop("type")
        loader = get_source_loader(source_type, **source_config)
        df = loader.load_dataframe(limit=load_limit)

        logger.info("Loaded %d rows from %s source", len(df), source_type)

        flattener = DataFrameFlattener()
        df = flattener.flatten(df=df)

        synth_cls = SYNTHESIZER_MAP.get(settings.sdv_model_type)
        if not synth_cls:
            raise ValueError(f"Unsupported synthesizer: {settings.sdv_model_type}")

        metadata = SingleTableMetadata()
        metadata.detect_from_dataframe(df)

        model_params = settings.sdv_model_params.copy()
        if settings.sdv_model_type == "CTGANSynthesizer":
            model_params["cuda"] = torch.cuda.is_available()

        synthesizer = synth_cls(metadata=metadata, **model_params)
        logger.info("Fitting synthesizer...")
        synthesizer.fit(df)

        logger.info("Generating %d synthetic rows...", output_size)
        synthetic_df = synthesizer.sample(num_rows=output_size)

        if settings.cleanup_on_complete:
            del synthesizer
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        return flattener.unflatten(flat_df=synthetic_df)
