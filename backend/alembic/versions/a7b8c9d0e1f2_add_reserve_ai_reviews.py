"""add reserve_ai_reviews

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-08-17 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # AI 预约审查留痕表:每次审查的结论 JSON 与送入模型的案件摘要(供校准)。
    op.create_table(
        'reserve_ai_reviews',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('external_case_id', sa.String(length=64), nullable=False),
        sa.Column('reserve_row_id', sa.Integer(), nullable=False),
        sa.Column('applicant', sa.String(length=128), nullable=False),
        sa.Column('respondent', sa.String(length=256), nullable=False),
        sa.Column('case_reason', sa.String(length=128), nullable=True),
        sa.Column('conclusion', sa.String(length=32), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('issues', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('missing_materials', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('rule_refs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('model_name', sa.String(length=64), nullable=True),
        sa.Column('case_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('raw_result', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by', sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_reserve_ai_reviews_external_case_id'),
        'reserve_ai_reviews',
        ['external_case_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_reserve_ai_reviews_external_case_id'), table_name='reserve_ai_reviews')
    op.drop_table('reserve_ai_reviews')
