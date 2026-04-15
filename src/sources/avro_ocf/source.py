from typing import Literal, Optional, Dict, Tuple, Any
from io import BytesIO
import base64
from pydantic import Field, PrivateAttr
from fastapi import HTTPException, status
import fastavro
import pandas as pd
from src.logger import LoggerFactory
from src.config import DEFAULT_AVRO_NAMESPACE
from .types import AvroBase64Str, AvroFilenameStr
from ..base import DataSource, DataSourceConfig
from .. import register_source


logger = LoggerFactory.getLogger(__name__)


class AvroOCFSourceConfig(DataSourceConfig):
    file_content: AvroBase64Str = Field(
        ..., description="Avro OCF file content as base64-encoded string"
    )
    filename: Optional[AvroFilenameStr] = Field(
        None, description="Original filename for extension validation"
    )


# FIXME: storing heavy datasets in memory, implement dump to file until worker picks up the task
# Okay for <=100MB uploads, x2 payload size at peak. Otherwise need custom stream wrapper (high cpu, low mem)
@register_source
class AvroOCFSource(DataSource):
    type: Literal["avro-ocf"]
    config: AvroOCFSourceConfig

    _title: Optional[str] = PrivateAttr(None)
    _namespace: Optional[str] = PrivateAttr(None)
    _avro_schema: Optional[Dict[str, Any]] = PrivateAttr(None)

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

    @property
    def avro_schema(self) -> Dict[str, Any]:
        if self._avro_schema is None:
            raise RuntimeError(
                f"Call .load_dataframe() before addressing .avro_schema property of {self.__class__.__name__} object"
            )
        return self._avro_schema

    def load_dataframe(self, limit: int | None = None) -> pd.DataFrame:
        file_stream = BytesIO(base64.b64decode(self.config.file_content))

        # Parse Avro OCF - fastavro auto-detects codec from header (snappy, deflate, null, etc.)
        try:
            avro_reader = fastavro.reader(file_stream)
            schema = avro_reader.writer_schema

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
                    detail=f"Unexpected schema format. Expected dict, got {type(schema)}",
                )
            self._avro_schema = schema

            self._namespace, self._title = self._parse_name(schema=schema)

            # Stream records with optional limit
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
            raise
        except Exception as e:
            logger.error(f"Avro read error: {e}", exc_info=True)
            raise HTTPException(
                status_code=400,
                detail=f"Failed to read Avro file. Ensure codec is supported (snappy/deflate). Error: {str(e)}",
            )

        try:
            return pd.DataFrame(records)
        except Exception as e:
            logger.error(f"DataFrame conversion failed: {e}", exc_info=True)
            raise HTTPException(
                status_code=500, detail=f"DataFrame conversion failed: {str(e)}"
            )

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
