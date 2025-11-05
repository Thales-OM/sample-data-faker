from .base import DataSource, DataSourceConfig
from . import register_source
import pandas as pd
import os


class DummySourceConfig(DataSourceConfig):
    pass


@register_source("dummy", DummySourceConfig)
class DummySource(DataSource):
    def __init__(self):
        pass

    def load_dataframe(self, limit: int | None = None) -> pd.DataFrame:
        # TODO: add to settings
        INPUT_FILEPATH = os.path.join(os.getcwd(), "examples/complex_input.parquet")
        df = pd.read_parquet(INPUT_FILEPATH)
        if limit is not None and len(df) > limit:
            df = df.head(limit)
        return df
