from typing import List, Any, Dict
from pydantic import BaseModel, model_validator
import pandas as pd
import json


class SampleData(BaseModel):
    columns: List[str]
    rows: List[List[Any]]

    @model_validator(mode="after")
    def validate_columns(self):
        num_columns = len(self.columns)
        for idx, row in enumerate(self.rows):
            row_len = len(row)
            if row_len != num_columns:
                raise ValueError(
                    f"Number of values at row {idx} = {row_len}, number of declared columns = {num_columns}"
                )
        return self
    
    # FIXME: heavy dataframe to json conversion
    def from_dataframe(df: pd.DataFrame) -> "SampleData":
        df_json = df.to_json(orient="split", date_format="iso", index=False)
        df_dict: Dict[str, Any] = json.loads(df_json)
        df_dict["rows"] = df_dict.pop("data")
        return SampleData(**df_dict)
