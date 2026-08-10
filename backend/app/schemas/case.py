import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models.case import CaseStatus, PartyType


class PartyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    party_type: PartyType
    name: str
    id_card_or_credit_code: str | None = None


class CaseCreate(BaseModel):
    claims: str | None = None


class CaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_no: str | None = None
    status: CaseStatus
    claims: str | None = None
    risk_level: str | None = None
    filed_date: date | None = None
    statute_deadline: date | None = None
    created_at: datetime
    updated_at: datetime
    parties: list[PartyOut] = []


class CaseTransitionRequest(BaseModel):
    target_status: CaseStatus
