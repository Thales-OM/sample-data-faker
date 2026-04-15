from enum import StrEnum


class FieldNameRegex(StrEnum):
    COLUMNS = r"^columns$"
    COLUMN_ATTRS = r"^columns\.(.+)\.([^\.]+)$"
    COLUMN_TAGS = r"^columns\.(.+)\.tags$"
