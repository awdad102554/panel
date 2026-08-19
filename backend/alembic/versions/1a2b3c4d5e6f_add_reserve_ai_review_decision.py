"""add reserve_ai_reviews.decision/reject_reason/reject_detail

Revision ID: 1a2b3c4d5e6f
Revises: 9a8b7c6d5e4f
Create Date: 2026-08-18 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '1a2b3c4d5e6f'
down_revision: Union[str, None] = '9a8b7c6d5e4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # AI 初筛同时预测人工审核口径的 decision(同意/不同意)与不同意理由(8 选 1),
    # 供前端自动预填、人工编辑确认;落库用于与最终人工决定对比校准。
    op.add_column('reserve_ai_reviews', sa.Column('decision', sa.String(length=16), nullable=True))
    op.add_column('reserve_ai_reviews', sa.Column('reject_reason', sa.String(length=256), nullable=True))
    op.add_column('reserve_ai_reviews', sa.Column('reject_detail', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('reserve_ai_reviews', 'reject_detail')
    op.drop_column('reserve_ai_reviews', 'reject_reason')
    op.drop_column('reserve_ai_reviews', 'decision')
