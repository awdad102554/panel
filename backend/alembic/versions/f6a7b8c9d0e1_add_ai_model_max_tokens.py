"""add max_tokens to ai_model_configs

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-17 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 单次请求最大输出 token 数(供真实 LLM Provider 使用);默认 8192 为通用安全值。
    op.add_column(
        'ai_model_configs',
        sa.Column('max_tokens', sa.Integer(), server_default='8192', nullable=True),
    )
    # 已存在的 DeepSeek V4 配置按官方上限(384K 输出)回填。
    op.execute(
        "UPDATE ai_model_configs SET max_tokens = 393216 "
        "WHERE model_name IN ('deepseek-v4-pro', 'deepseek-v4-flash')"
    )


def downgrade() -> None:
    op.drop_column('ai_model_configs', 'max_tokens')
