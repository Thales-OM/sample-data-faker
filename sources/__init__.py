from .base import DataSource, DataSourceConfig
from typing import Dict, Type, List
import importlib
import pkgutil
import pathlib
import sys
from pydantic import BaseModel, create_model
from typing import Union


SOURCE_REGISTRY: Dict[str, Type[DataSource]] = {}


def register_source(name: str, config_model: Type[DataSourceConfig]):
    """Decorator to register a data source with its config schema."""

    def decorator(cls: Type[DataSource]):
        if name in SOURCE_REGISTRY:
            raise ValueError(f"Source type '{name}' already registered")
        cls.config_model = config_model
        cls._source_name = name  # store name on class
        SOURCE_REGISTRY[name] = cls
        return cls

    return decorator


def get_source_loader(source_type: str, **config) -> DataSource:
    if source_type not in SOURCE_REGISTRY:
        available = list(SOURCE_REGISTRY.keys())
        raise ValueError(f"Unknown source type: {source_type}. Available: {available}")
    cls = SOURCE_REGISTRY[source_type]
    config_obj = cls.config_model(**config)  # validate early
    return cls(**config_obj.model_dump(mode="python"))


def build_source_union_type() -> Type[BaseModel]:
    """Build a discriminated union of all source config models."""
    if not SOURCE_REGISTRY:
        raise RuntimeError("No sources registered. Did you import plugins?")

    # Collect all (name, config_model) pairs
    choices = {}
    for name, cls in SOURCE_REGISTRY.items():
        model_with_type = create_model(
            f"{name.capitalize()}Source",
            type=(str, name),  # required for discrimination
            __base__=cls.config_model,
        )
        choices[name] = model_with_type

    return Union[tuple(choices.values())]


def _discover_plugins():
    """Auto-discover plugins inside current module"""
    package_name = __name__
    package_path = pathlib.Path(__file__).parent
    for _, module_name, _ in pkgutil.iter_modules([str(package_path)]):
        if module_name == "base":
            continue
        full_name = f"{package_name}.{module_name}"
        if full_name not in sys.modules:
            importlib.import_module(full_name)


# Run discovery when this package is first imported
_discover_plugins()

# Export the dynamic model
SourceConfig = build_source_union_type()
