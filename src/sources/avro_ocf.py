from typing import Literal, overload, Optional
from pydantic import Field, PrivateAttr
from fastapi import UploadFile, HTTPException, status
from io import BytesIO
import fastavro
import struct
import pandas as pd
import numpy as np
from src.logger import LoggerFactory
from .base import DataSource, DataSourceConfig
from . import register_source

logger = LoggerFactory.getLogger(__name__)

DEFAULT_NAMESPACE = "wb"


class AvroOCFSourceConfig(DataSourceConfig):
    file: UploadFile = Field(..., description="Avro OCF file (.avro)")


# FIXME: risks storing heavy datasets in memory, implement dump to file until worker picks up the task
@register_source
class AvroOCFSource(DataSource):
    type: Literal["avro-ocf"] = "avro-ocf"
    config: AvroOCFSourceConfig

    _title: Optional[str] = PrivateAttr(None)
    _namespace: Optional[str] = PrivateAttr(None)

    @property
    def title(self) -> str:
        if self._title is None:
            raise RuntimeError(
                f"Call .load_dataframe() before addressing .title property of {self.__class__.__name__} object"
            )
        return self._title

    @property
    def namespace(self) -> str:
        if self._namespace is None:
            raise RuntimeError(
                f"Call .load_dataframe() before addressing .namespace property of {self.__class__.__name__} object"
            )
        return self._namespace

    def load_dataframe(self, limit: int | None = None) -> pd.DataFrame:
        file = self.config.file

        # Validate filename extension (first line of defense)
        if not file.filename or not file.filename.endswith(".avro"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File must have .avro extension",
            )

        # Read content
        content = file.file.read()

        # Validate file size
        if len(content) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file uploaded"
            )

        # Validate magic bytes (critical - prevents non-Avro files)
        if not self.validate_avro_magic(content=content):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Avro file: Missing or incorrect magic bytes (expected b'Obj\\x01')",
            )

        # Parse Avro OCF
        bytes_io = BytesIO(content)
        try:
            avro_reader = fastavro.reader(bytes_io)
            schema = avro_reader.writer_schema

            if not schema:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No schema found in Avro file",
                )
            if not isinstance(schema, dict):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unexpected schema format in Avro file. Expected dict, got {type(schema)}",
                )

            full_name = schema.get("name", None)
            if not full_name:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Name not found in Avro file schema",
                )
            if not isinstance(full_name, str):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unexpected name type in Avro schema. Expected str, got {type(schema)}",
                )
            full_name_split = full_name.rsplit(".", maxsplit=1)
            self._title = full_name_split[-1]
            if len(full_name_split) < 2:
                self._namespace = DEFAULT_NAMESPACE
            else:
                self._namespace = full_name_split[0]

            # Stream records with limit
            records = []
            for i, record in enumerate(avro_reader):
                records.append(record)
                if limit and i + 1 >= limit:
                    break

            if not records:
                raise HTTPException(
                    status_code=400, detail="Avro file contains no records"
                )

        except (fastavro.SchemaParseException, ValueError, struct.error) as e:
            logger.error(f"Avro parse error: {e}")
            raise HTTPException(
                status_code=400, detail=f"Failed to parse Avro file: {str(e)}"
            )

        # Convert to DataFrame
        try:
            df = pd.DataFrame(records)
        except Exception as e:
            logger.error(f"DataFrame conversion failed: {e}")
            raise HTTPException(
                status_code=500, detail=f"DataFrame conversion failed: {str(e)}"
            )

        # Sanitize for JSON response
        self.sanitize_dataframe_for_json(df=df, inplace=True)

        return df

    @staticmethod
    def validate_avro_magic(content: bytes) -> bool:
        """Check if content starts with Avro OCF magic bytes."""
        return len(content) >= 4 and content[:4] == b"Obj\x01"

    @overload
    @staticmethod
    def sanitize_dataframe_for_json(
        df: pd.DataFrame, inplace: Literal[True]
    ) -> None: ...

    @overload
    @staticmethod
    def sanitize_dataframe_for_json(
        df: pd.DataFrame, inplace: Literal[False]
    ) -> pd.DataFrame: ...

    @staticmethod
    def sanitize_dataframe_for_json(
        df: pd.DataFrame, inplace: bool = False
    ) -> pd.DataFrame | None:
        """Convert problematic types to JSON-serializable formats."""
        if not inplace:
            df = df.copy()

        # Convert datetime types to ISO strings
        for col in df.select_dtypes(include=["datetime64", "timedelta64"]).columns:
            df[col] = df[col].astype(str)

        # Convert bytes/bytearray to hex strings
        for col in df.columns:
            if df[col].apply(lambda x: isinstance(x, (bytes, bytearray))).any():
                df[col] = df[col].apply(
                    lambda x: x.hex() if isinstance(x, (bytes, bytearray)) else x
                )

        # Replace infinities
        df = df.replace([np.inf, -np.inf], np.nan)

        if not inplace:
            return df
        return None
