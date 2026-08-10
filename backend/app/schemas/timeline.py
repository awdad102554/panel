import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TimelineEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID
    event_type: str
    summary: str
    created_by: str | None = None
    created_at: datetime
