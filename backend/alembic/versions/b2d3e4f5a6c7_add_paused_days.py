"""add paused_days to internal_case_trackings

审理时长扣除中止期间:internal_case_trackings 新增 paused_days 列,
由后台任务按内网 caseData.review_matter 的中止/恢复审理记录回填。

Revision ID: b2d3e4f5a6c7
Revises: a1c2e3f4b5d6
Create Date: 2026-07-30 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2d3e4f5a6c7'
down_revision: Union[str, None] = 'a1c2e3f4b5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('internal_case_trackings', sa.Column('paused_days', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('internal_case_trackings', 'paused_days')
