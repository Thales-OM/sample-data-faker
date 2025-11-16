from pydantic import SecretStr, Field, field_validator
from .base import DataSource, DataSourceConfig
from . import register_source
import pandas as pd
from sqlalchemy import create_engine
from urllib.parse import quote_plus
from typing import Optional, Dict, Any, Literal


class TrinoSourceConfig(DataSourceConfig):
    # Connection
    host: str = Field(
        ..., description="Trino coordinator host (e.g., trino.example.com)"
    )
    port: int = Field(8080, ge=1, le=65535, description="Trino HTTP port")
    user: str = Field(..., description="Trino user for authentication")
    password: Optional[SecretStr] = Field(
        None,
        description="Password (if using password-based auth)",
        exclude=True,  # Never serialize in OpenAPI/docs
    )

    # Catalog & schema (required for URL)
    catalog: str = Field(..., description="Trino catalog (e.g., hive, postgresql)")
    schema_name: str = Field(
        ..., description="Schema within the catalog", alias="schema"
    )

    # Optional: HTTP headers, session properties, etc.
    http_headers: Optional[Dict[str, str]] = Field(
        None, description="Custom HTTP headers (e.g., for proxy auth)", exclude=True
    )
    session_properties: Optional[Dict[str, Any]] = Field(
        None, description="Trino session properties (e.g., {'query_priority': 'high'})"
    )

    table: str = Field(..., description="Table name (can be qualified: schema.table)")

    @field_validator("host", mode="after")
    def host_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Host cannot be empty")
        return v.strip()

    @field_validator("catalog", "schema_name", "user", mode="after")
    def non_empty_strings(cls, v):
        if not v or not v.strip():
            raise ValueError("Field cannot be empty")
        return v.strip()


@register_source
class TrinoSource(DataSource):
    type: Literal["trino"] = "trino"
    config: TrinoSourceConfig

    def load_dataframe(self, limit: int | None = None) -> pd.DataFrame:
        IGNORE_COLUMNS = ["_dq", "_dq_failed_checks", "_stage_dt", "_cleansed_dt"]
        # Build password part
        password_part = (
            f":{quote_plus(self.config.password.get_secret_value())}"
            if self.config.password
            else ""
        )
        # Build URL
        url = f"trino://{self.config.user}{password_part}@{self.config.host}:{self.config.port}/{self.config.catalog}/{self.config.schema_name}?externalAuthentication=true"

        # Add session properties as query args (e.g., ?session_properties=query_priority%3Dhigh)
        if self.config.session_properties:
            from urllib.parse import urlencode

            engine = create_engine(
                url,
                connect_args={"http_headers": self.config.http_headers or {}},
            )
        else:
            engine = create_engine(
                url,
                connect_args=(
                    {"http_headers": self.config.http_headers}
                    if self.config.http_headers
                    else {}
                ),
            )

        query = f"SELECT * FROM {self.config.table}"
        if limit is not None:
            query += f" LIMIT {limit}"

        df = pd.read_sql(query, engine)
        df.drop(columns=IGNORE_COLUMNS, axis=1, inplace=True, errors="ignore")
        return df
