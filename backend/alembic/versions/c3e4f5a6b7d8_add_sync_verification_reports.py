"""add sync verification reports

一致性校验结果留档:sync_verification_reports 表保存每次全量只读对账的
统计与完整差异明细,供排查轻量同步问题。

Revision ID: c3e4f5a6b7d8
Revises: b2d3e4f5a6c7
Create Date: 2026-07-31 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c3e4f5a6b7d8'
down_revision: Union[str, None] = 'b2d3e4f5a6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'sync_verification_reports',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('checked', sa.Integer(), nullable=False),
        sa.Column('missing_total', sa.Integer(), nullable=False),
        sa.Column('mismatch_total', sa.Integer(), nullable=False),
        sa.Column('only_in_snapshot', sa.Integer(), nullable=False),
        sa.Column('details', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('sync_verification_reports')
