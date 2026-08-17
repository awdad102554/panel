import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AIModelCreate(BaseModel):
    name: str
    provider: str
    base_url: str
    api_key: str
    model_name: str
    temperature: float | None = 0.2
    max_tokens: int | None = 8192
    remark: str | None = None


class AIModelUpdate(BaseModel):
    """全部可选；api_key 为 None 表示不修改密钥。"""

    name: str | None = None
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model_name: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    remark: str | None = None


class AIModelOut(BaseModel):
    """对外输出，不回显 api_key 明文，仅返回脱敏后的 api_key_masked。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    provider: str
    base_url: str
    api_key_masked: str
    model_name: str
    temperature: float | None = None
    max_tokens: int | None = None
    is_enabled: bool
    remark: str | None = None
    created_at: datetime
    updated_at: datetime
