from pydantic import BaseModel, ConfigDict, Field
from typing import Union, Optional, Annotated
import re
from src.models.openmetadata.field.value import ColumnValueRaw
from ._types import FieldNameRegex


Columns = Annotated[str, Field(..., pattern=FieldNameRegex.COLUMNS.value)]
ColumnAttrs = Annotated[str, Field(..., pattern=FieldNameRegex.COLUMN_ATTRS.value)]
ColumnTags = Annotated[str, Field(..., pattern=FieldNameRegex.COLUMN_TAGS.value)]


class BaseField(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str

    def get_target_column_name(self) -> Optional[str]:
        """
        If the field represents a change in column definition
        (not a tag change) then returns the column name, otherwise None
        """
        return None


class BaseFieldAdded(BaseField):
    newValue: str


class BaseFieldDeleted(BaseField):
    oldValue: str


class BaseFieldUpdated(BaseFieldAdded, BaseFieldDeleted):
    pass


class Column(BaseField):
    name: Columns


class ColumnAdded(Column, BaseFieldAdded):
    newValue: ColumnValueRaw

    def get_target_column_name(self) -> Optional[str]:
        return self.newValue[0].name


class ColumnDeleted(Column, BaseFieldDeleted):
    oldValue: ColumnValueRaw


class ColumnUpdated(ColumnAdded, ColumnDeleted):
    pass


class ColumnAttr(BaseField):
    name: ColumnAttrs


class ColumnAttrAdded(ColumnAttr, BaseFieldAdded):
    def get_target_column_name(self) -> Optional[str]:
        if match := re.match(FieldNameRegex.COLUMN_ATTRS.value, self.name):
            if not re.match(FieldNameRegex.COLUMN_TAGS.value, self.name):
                return match.group(1)
        return None


class ColumnAttrDeleted(ColumnAttr, BaseFieldDeleted):
    pass


class ColumnAttrUpdated(ColumnAttrAdded, ColumnAttrDeleted):
    pass


FieldAddedTypes = Union[ColumnAdded, ColumnAttrAdded, BaseFieldAdded]
FieldUpdatedTypes = Union[ColumnUpdated, ColumnAttrUpdated, BaseFieldUpdated]
FieldDeletedTypes = Union[ColumnDeleted, ColumnAttrDeleted, BaseFieldDeleted]
