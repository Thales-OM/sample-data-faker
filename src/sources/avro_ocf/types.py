import re
import base64
import math
from typing import Annotated
from pydantic import AfterValidator, Field


AVRO_OCF_MAGIC = b"Obj\x01"
_B64_STRICT_RE = re.compile(r"^[A-Za-z0-9+/]*={0,2}$")
AVRO_FILENAME_PATTERN = r"^[\w\-\.]+\.avro$"


def base64_decode_first_n(b64_str: str, n: int) -> bytes:
    """Decode first N bytes of a base64 encoded string"""
    # How many characters are needed to get at least N bytes
    chars_needed = math.ceil(n * 4 / 3)

    # Ensure the length is a multiple of 4 for standard b64decode
    safe_slice = ((chars_needed + 3) // 4) * 4

    return base64.b64decode(b64_str[:safe_slice])[:n]


def _check_avro_magic(data: bytes) -> bytes:
    # O(1) length guard + fast slice comparison
    if len(data) < 4 or data[:4] != AVRO_OCF_MAGIC:
        raise ValueError(
            f"Invalid Avro data: expected {AVRO_OCF_MAGIC!r} magic bytes, got {data[:4]!r}."
        )
    return data


def _validate_b64_format(value: str) -> str:
    if len(value) % 4 != 0 or not _B64_STRICT_RE.match(value):
        raise ValueError("Invalid base64 string: malformed format or padding")
    return value


def _validate_avro_magic(value: str) -> str:
    first_4_bytes = base64_decode_first_n(b64_str=value, n=4)
    _check_avro_magic(data=first_4_bytes)
    return value


Base64Str = Annotated[
    str,
    AfterValidator(_validate_b64_format),
    "Base64-encoded string validated against strict RFC 4648 format (no whitespace, correct padding). No decode.",
]

AvroBase64Str = Annotated[
    Base64Str,
    AfterValidator(_validate_avro_magic),
    "Base64-encoded Avro OCF payload, verified for correct format and 'Obj\\x01' magic bytes. No decode.",
]

AvroFilenameStr = Annotated[
    str,
    Field(
        pattern=AVRO_FILENAME_PATTERN,
        description="Valid Avro filename ending in '.avro' (case-sensitive). Allowed chars: alphanumeric, hyphen, underscore, dot.",
    ),
]
