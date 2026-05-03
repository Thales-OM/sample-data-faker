from typing import Any, Dict, List, Union, Literal
from pydantic import BaseModel
from pydantic.types import _SecretField
from pydantic_core import to_jsonable_python


class DumpableSecretsBaseModel(BaseModel):
    def model_dump_with_secrets(
        self,
        *,
        mode: Literal["python", "json"] = "python",
        include=None,
        exclude=None,
        context=None,
        by_alias=None,
        exclude_unset=False,
        exclude_defaults=False,
        exclude_none=False,
        exclude_computed_fields=False,
        round_trip=False,
        warnings=True,
        fallback=None,
        serialize_as_any=False,
    ) -> Dict[str, Any]:
        """
        Dump model with SecretStr/SecretBytes values revealed.
        """
        ALLOWED_MODES = ("python", "json")

        if mode not in ALLOWED_MODES:
            raise ValueError(f"Invalid mode: {mode}. Allowed: {ALLOWED_MODES}")

        data = self.model_dump(
            mode="python",
            include=include,
            exclude=exclude,
            context=context,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
            exclude_computed_fields=exclude_computed_fields,
            round_trip=round_trip,
            warnings=warnings,
            fallback=fallback,
            serialize_as_any=serialize_as_any,
        )

        data = self._extract_secrets_recursive(data)

        if mode == "json":
            data = to_jsonable_python(data, fallback=fallback)

        return data

    @staticmethod
    def _is_secret_field(value: Any) -> bool:
        """Check if value is a secret field by checking _SecretField inheritance."""
        return isinstance(value, _SecretField)

    @staticmethod
    def _get_secret_value(value: _SecretField) -> Union[str, bytes]:
        """Extract the actual value from a secret field."""
        return value.get_secret_value()

    @classmethod
    def _extract_secrets_recursive(cls, data: Any) -> Any:
        """
        Recursively extract secret values from dumped data.
        """
        if isinstance(data, dict):
            return cls._extract_secrets_from_dict(data)
        if isinstance(data, list):
            return cls._extract_secrets_from_list(data)
        if cls._is_secret_field(data):
            return cls._get_secret_value(data)
        return data

    @classmethod
    def _extract_secrets_from_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract secrets from dictionary"""
        result = {}
        for key, value in data.items():
            result[key] = cls._extract_secrets_recursive(value)
        return result

    @classmethod
    def _extract_secrets_from_list(cls, data: List[Any]) -> List[Any]:
        """Extract secrets from list items"""
        return [cls._extract_secrets_recursive(value) for value in data]
