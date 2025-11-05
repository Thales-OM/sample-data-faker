from typing import List, Dict, Any
from pydantic import RootModel


class SyntheticResponse(RootModel[List[Dict[str, Any]]]):
    pass
