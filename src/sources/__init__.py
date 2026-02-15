from .base import DataSource
from typing import Dict, Type, Union
import importlib
import pkgutil
import pathlib
from typing import Literal, get_type_hints, get_origin, get_args, Annotated
import sys
from pydantic import BaseModel, Field


SOURCE_REGISTRY: Dict[str, Type[DataSource]] = {}


def register_source(cls: Type[DataSource]):
    """Decorator to register a data source with its config schema."""

    TYPE_FIELD = "type"

    if not issubclass(cls, DataSource):
        raise TypeError(
            f"@check_type_literal can only be applied to DataSource subclasses, got {cls.__name__}"
        )

    # Get type annotations for the class
    annotations = get_type_hints(cls)

    if TYPE_FIELD not in annotations:
        raise TypeError(f"Class {cls.__name__} must have a '{TYPE_FIELD}' field")

    type_annotation = annotations[TYPE_FIELD]

    # Check if it's a Literal type
    origin = get_origin(type_annotation)
    if origin is not Literal:
        raise TypeError(
            f"Field '{TYPE_FIELD}' in {cls.__name__} must be of type Literal, got {type_annotation}"
        )

    # Get the literal arguments
    args = get_args(type_annotation)

    # Check if there's exactly one argument and it's a string
    if len(args) != 1:
        raise TypeError(
            f"Field '{TYPE_FIELD}' in {cls.__name__} must be Literal with exactly one value, got {len(args)} values: {args}"
        )

    literal_value = args[0]
    if not isinstance(literal_value, str):
        raise TypeError(
            f"Field '{TYPE_FIELD}' in {cls.__name__} must be Literal[str], got Literal[{type(literal_value).__name__}]: {literal_value}"
        )

    if literal_value in SOURCE_REGISTRY:
        raise KeyError(
            f"Duplicate DataSource type discovered ({TYPE_FIELD}: {literal_value}, class: {cls.__name__})"
        )

    SOURCE_REGISTRY[literal_value] = cls
    return cls


def build_source_union_type() -> Type[BaseModel]:
    """Build a discriminated union of all source config models."""
    if not SOURCE_REGISTRY:
        raise RuntimeError("No sources registered. Did you import plugins?")
    return Annotated[
        Union[tuple(SOURCE_REGISTRY.values())], Field(discriminator="type")
    ]


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
