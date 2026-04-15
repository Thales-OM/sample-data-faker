from pydantic import BaseModel


class TestMessage(BaseModel):
    """Message sent by OpenMetadata to test Alert destination"""

    message: str
