import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.permissions import Action, require_permission
from app.db.session import get_db
from app.models.document import Document, DocumentType
from app.services import case_service

router = APIRouter(prefix="/cases", tags=["documents"])


class DocumentOut(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    doc_type: DocumentType
    version: int
    content: str | None
    generated_by_ai: bool

    model_config = {"from_attributes": True}


class DocumentCreate(BaseModel):
    doc_type: DocumentType
    content: str | None = None
    generated_by_ai: bool = False


@router.get("/{case_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
) -> list[DocumentOut]:
    """文书中心，对应 04 PRD 案件工作台"裁决"分区 / 06 页面原型设计 页面六。"""

    stmt = select(Document).where(Document.case_id == case_id).order_by(Document.created_at.desc())
    result = await db.execute(stmt)
    return [DocumentOut.model_validate(d) for d in result.scalars().all()]


@router.post("/{case_id}/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def create_document(
    case_id: uuid.UUID,
    payload: DocumentCreate,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_permission(Action.DOCUMENT_GENERATE)),
) -> DocumentOut:
    case = await case_service.get_case_workspace(db, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="案件不存在")
    document = Document(case_id=case_id, **payload.model_dump())
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return DocumentOut.model_validate(document)
