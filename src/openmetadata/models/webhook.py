from typing import Literal
from pydantic import BaseModel, ConfigDict
from .change_description import ChangeDescription
from ._types import AcceptableEntityType, AcceptableEventType
from src.logger import LoggerFactory


logger = LoggerFactory.getLogger(__name__)


class BaseWebhookTable(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    entityType: Literal[AcceptableEntityType.TABLE.value]
    eventType: AcceptableEventType
    entityId: str
    timestamp: int


class WebhookTableCreated(BaseWebhookTable):
    eventType: Literal[AcceptableEventType.ENTITY_CREATED.value]


class WebhookTableUpdated(BaseWebhookTable):
    eventType: Literal[AcceptableEventType.ENTITY_UPDATED.value]
    changeDescription: ChangeDescription

    def is_schema_change(self) -> bool:
        failed_fields = []
        for field in (
            self.changeDescription.fieldsAdded
            + self.changeDescription.fieldsUpdated
            + self.changeDescription.fieldsDeleted
        ):
            try:
                schema_changing_column = field.get_target_column_name()
                # At least one column was added/altered/deleted
                if schema_changing_column:
                    return True
            except Exception:
                failed_fields.append(field)

        if failed_fields:
            logger.error(
                f"Failed to parse some fields and determine whether schema change has occured: {failed_fields}."
                f"Falling back to assuming schema change (TableId={self.entityId})."
            )
            return True
        return False
