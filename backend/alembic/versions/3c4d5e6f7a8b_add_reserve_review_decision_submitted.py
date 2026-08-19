"""add reserve_review_decisions submitted fields

Revision ID: 3c4d5e6f7a8b
Revises: 2b3c4d5e6f7a
Create Date: 2026-08-19 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3c4d5e6f7a8b'
down_revision: Union[str, None] = '2b3c4d5e6f7a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 预约「审核结果」提交内网(preAudit)成功后的留痕;可空、无默认值(未提交即 NULL)。
    op.add_column('reserve_review_decisions', sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('reserve_review_decisions', sa.Column('submitted_by', sa.String(length=64), nullable=True))
    op.add_column('reserve_review_decisions', sa.Column('internal_status', sa.Integer(), nullable=True))
    op.add_column('reserve_review_decisions', sa.Column('internal_reason', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('reserve_review_decisions', 'internal_reason')
    op.drop_column('reserve_review_decisions', 'internal_status')
    op.drop_column('reserve_review_decisions', 'submitted_by')
    op.drop_column('reserve_review_decisions', 'submitted_at')
