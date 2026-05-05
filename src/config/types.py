from typing import Annotated, Any, Dict
from urllib.parse import urlparse
from pydantic import AfterValidator, BeforeValidator
import json


def _parse_json_or_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value

    # String -> attempt JSON parse
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON string: {e}") from e

        if not isinstance(parsed, dict):
            raise ValueError(
                f"JSON must decode to a dict/object, got {type(parsed).__name__}"
            )
        return parsed

    # Everything else -> reject
    raise ValueError(f"Expected dict or JSON string, got {type(value).__name__}")


JsonDict = Annotated[Dict[str, Any], BeforeValidator(_parse_json_or_dict)]


def _validate_hive_metastore_uri(value: str) -> str:
    """Validate a Hive Metastore URI string."""
    value = value.strip()
    parsed = urlparse(value)

    if parsed.scheme.lower() != "thrift":
        raise ValueError(
            f"Invalid scheme '{parsed.scheme}'. Hive Metastore URIs must use the 'thrift' scheme."
        )

    if not parsed.hostname:
        raise ValueError("Missing hostname. Expected format: thrift://<host>:<port>")

    if parsed.port is None:
        raise ValueError("Missing port. Expected format: thrift://<host>:<port>")
    if not (1 <= parsed.port <= 65535):
        raise ValueError(f"Port {parsed.port} is out of valid range (1-65535).")

    if (
        parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Hive Metastore URIs must not contain user credentials, path, query, or fragment."
        )

    return value


HiveMetastoreUri = Annotated[str, AfterValidator(_validate_hive_metastore_uri)]
