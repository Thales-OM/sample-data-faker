from pydantic import BaseModel, ConfigDict
from typing import List
from .field.field import (
    FieldAddedTypes,
    FieldUpdatedTypes,
    FieldDeletedTypes,
)


class ChangeDescription(BaseModel):
    model_config = ConfigDict(extra="ignore")

    fieldsAdded: List[FieldAddedTypes] = []
    fieldsUpdated: List[FieldUpdatedTypes] = []
    fieldsDeleted: List[FieldDeletedTypes] = []
