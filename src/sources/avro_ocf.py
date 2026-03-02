from typing import Literal, Optional, Dict, Tuple, Any
from pydantic import Field, PrivateAttr, field_validator
from fastapi import UploadFile, HTTPException, status
import fastavro
import pandas as pd
from src.logger import LoggerFactory
from src.config import DEFAULT_AVRO_NAMESPACE
from .base import DataSource, DataSourceConfig


logger = LoggerFactory.getLogger(__name__)


class AvroOCFSourceConfig(DataSourceConfig):
    file: UploadFile = Field(..., description="Avro OCF file (.avro)")

    @field_validator("file", mode="after")
    def validate_extension(file: UploadFile) -> UploadFile:
        """Validate filename extension"""
        if not file.filename or not file.filename.endswith(".avro"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File must have .avro extension",
            )
        return file


# FIXME: risks storing heavy datasets in memory, implement dump to file until worker picks up the task
# TODO: reading potentially large file in sync
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

        # Reset file pointer to start (UploadFile may be at end after validation)
        file.file.seek(0)

        magic_bytes = file.file.read(4)
        if not self.validate_avro_magic(content=magic_bytes):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Avro file: Missing or incorrect magic bytes (expected b'Obj\\x01')",
            )

        # Reset pointer again for fastavro reader
        file.file.seek(0)

        # Parse Avro OCF - fastavro auto-detects codec from header (snappy, deflate, null, etc.)
        try:
            avro_reader = fastavro.reader(file.file)
            schema = avro_reader.writer_schema

            # Log detected codec for debugging
            codec = getattr(avro_reader, "codec", "null")
            logger.info(f"Reading Avro OCF with codec: {codec}")

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

            self._namespace, self._title = self._parse_name(schema=schema)

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
        except HTTPException:
            # Propagate formed HTTPException
            raise
        except Exception as e:
            logger.error(f"Avro read error (possible codec issue): {e}")
            raise HTTPException(
                status_code=400,
                detail=f"Failed to read Avro file. Ensure compression codec is supported (snappy/deflate). Error: {str(e)}",
            )

        # Convert to DataFrame
        try:
            df = pd.DataFrame(records)
        except Exception as e:
            logger.error(f"DataFrame conversion failed: {e}")
            raise HTTPException(
                status_code=500, detail=f"DataFrame conversion failed: {str(e)}"
            )

        return df

    @staticmethod
    def _parse_name(schema: Dict[str, Any]) -> Tuple[str, str]:
        """Extract proper namespace and title from schema.name"""
        full_name = schema.get("name", None)
        if not full_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Name not found in Avro file schema",
            )
        if not isinstance(full_name, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unexpected name type in Avro schema. Expected str, got {type(full_name)}",
            )
        full_name_split = full_name.rsplit(".", maxsplit=1)
        title = full_name_split[-1]
        namespace = (
            DEFAULT_AVRO_NAMESPACE if len(full_name_split) < 2 else full_name_split[0]
        )
        return namespace, title

    @staticmethod
    def validate_avro_magic(content: bytes) -> bool:
        """Check if content starts with Avro OCF magic bytes."""
        return len(content) >= 4 and content[:4] == b"Obj\x01"
