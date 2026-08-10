import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.ai_output import AICapabilityType


class AIInvokeRequest(BaseModel):
    capability: AICapabilityType


class AIOutputOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID
    capability: AICapabilityType
    result: dict[str, Any]
    created_at: datetime
    confirmed_at: datetime | None = None
    confirmed_by: str | None = None


class AIConfirmRequest(BaseModel):
    ai_output_id: uuid.UUID
