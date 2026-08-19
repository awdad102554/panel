"""add reserve_review_decisions

Revision ID: 9a8b7c6d5e4f
Revises: c8d9e0f1a2b3
Create Date: 2026-08-18 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9a8b7c6d5e4f'
down_revision: Union[str, None] = 'c8d9e0f1a2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 人工「审核结果」留痕表:同意/不同意 + 理由(8 选 1)+ 补充说明,最新一条生效。
    op.create_table(
        'reserve_review_decisions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('external_case_id', sa.String(length=64), nullable=False),
        sa.Column('reserve_row_id', sa.Integer(), nullable=False),
        sa.Column('applicant', sa.String(length=128), nullable=False),
        sa.Column('respondent', sa.String(length=256), nullable=False),
        sa.Column('case_reason', sa.String(length=128), nullable=True),
        sa.Column('decision', sa.String(length=16), nullable=False),
        sa.Column('reject_reason', sa.String(length=256), nullable=True),
        sa.Column('reject_detail', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by', sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_reserve_review_decisions_external_case_id'),
        'reserve_review_decisions',
        ['external_case_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_reserve_review_decisions_external_case_id'), table_name='reserve_review_decisions')
    op.drop_table('reserve_review_decisions')
