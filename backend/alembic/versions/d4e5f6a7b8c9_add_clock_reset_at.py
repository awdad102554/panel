"""add clock_reset_at to internal_case_trackings

审限重新计算:变更/增加仲裁请求、仲裁反申请、追加当事人被受理后仲裁期限重新
起算,新增 clock_reset_at 列记录最近一次重启日期(与 paused_days 同批回填)。

Revision ID: d4e5f6a7b8c9
Revises: c3e4f5a6b7d8
Create Date: 2026-07-31 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3e4f5a6b7d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('internal_case_trackings', sa.Column('clock_reset_at', sa.Date(), nullable=True))
    op.add_column('internal_case_trackings', sa.Column('paused_after_reset_days', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('internal_case_trackings', 'paused_after_reset_days')
    op.drop_column('internal_case_trackings', 'clock_reset_at')
