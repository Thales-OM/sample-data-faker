from enum import StrEnum


class AcceptableEntityType(StrEnum):
    TABLE = "table"


class AcceptableEventType(StrEnum):
    ENTITY_CREATED = "entityCreated"
    ENTITY_UPDATED = "entityUpdated"
