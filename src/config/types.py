from typing import Annotated
from urllib.parse import urlparse
from pydantic import AfterValidator


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
