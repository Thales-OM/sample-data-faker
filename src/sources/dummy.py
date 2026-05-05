from pathlib import Path
import pandas as pd
from pydantic import PrivateAttr
from typing import Literal, Union
from src.config import DUMMY_DATASET_FILEPATH
from .base import DataSource, DataSourceConfig
from . import register_source


class DummySourceConfig(DataSourceConfig):
    _input_filepath: Union[Path, str] = PrivateAttr(DUMMY_DATASET_FILEPATH)


@register_source
class DummySource(DataSource):
    type: Literal["dummy"]
    config: DummySourceConfig

    def load_dataframe(self, limit: int | None = None) -> pd.DataFrame:
        df = pd.read_parquet(self.config._input_filepath)
        if limit is not None and len(df) > limit:
            df = df.head(limit)
        return df
