from pydantic import BaseModel, ConfigDict, BeforeValidator
from typing import Any, Annotated, Union, List
import json


class ColumnValue(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    fullyQualifiedName: str


def parse_column_value(v: Any) -> Union[List[ColumnValue], str]:
    if isinstance(v, str):
        try:
            # Parse the string as JSON to get a list of dicts
            parsed_list = json.loads(v)
            # Convert each dict in the list to a ColumnValue instance
            return [ColumnValue.model_validate(item) for item in parsed_list]
        except Exception:
            pass
    return v


ColumnValueRaw = Annotated[List[ColumnValue], BeforeValidator(parse_column_value)]
