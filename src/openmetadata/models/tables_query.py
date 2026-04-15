from typing import Optional
from enum import StrEnum
from pydantic import BaseModel, Field


class IncludeValues(StrEnum):
    ALL = "all"
    DELETED = "deleted"
    NON_DELETED = "non-deleted"


class TablesQuery(BaseModel):
    fields: Optional[str] = "*"
    database: Optional[str] = None
    databaseSchema: Optional[str] = None
    includeEmptyTestSuite: Optional[bool] = True
    limit: Optional[int] = Field(10, ge=0, le=1000000)
    before: Optional[str] = None
    after: Optional[str] = None
    include: IncludeValues = IncludeValues.NON_DELETED
