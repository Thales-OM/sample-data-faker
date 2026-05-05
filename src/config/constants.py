from typing import Type
from pathlib import Path
from frozendict import frozendict
from enum import StrEnum
from sdv.single_table.base import BaseSynthesizer
from sdv.single_table import GaussianCopulaSynthesizer, CTGANSynthesizer


APP_VERSION = "1.0.0"

# Logging
DEFAULT_LOG_LEVEL = "INFO"

# SDV options
DEFAULT_SAMPLE_SIZE = 5000
DEFAULT_OUTPUT_SIZE = 1000


class SDVSynthesizer(StrEnum):
    GAUSSIAN_COPULA = "GaussianCopulaSynthesizer"
    CTGAN = "CTGANSynthesizer"


SYNTHESIZER_MAP: frozendict[SDVSynthesizer, Type[BaseSynthesizer]] = frozendict(
    {
        SDVSynthesizer.GAUSSIAN_COPULA: GaussianCopulaSynthesizer,
        SDVSynthesizer.CTGAN: CTGANSynthesizer,
    }
)


# Assets
DUMMY_DATASET_FILEPATH = (
    Path(__file__).parent.parent.parent / "examples" / "complex_input.parquet"
)

# Avro parsing
DEFAULT_AVRO_NAMESPACE = "wb"

# Core worker
DEFAULT_MAX_THREADS = 2
DEFAULT_MAX_PENDING = 3
