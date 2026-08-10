"""drop case service confirmations

送达跟踪取消(2026-07-30 工作人员确认口径):结案即终态,不再录入/跟踪结案后的
送达签收,删除 case_service_confirmations 表。

Revision ID: a1c2e3f4b5d6
Revises: 169f05d5cffe
Create Date: 2026-07-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a1c2e3f4b5d6'
down_revision: Union[str, None] = '169f05d5cffe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table('case_service_confirmations')


def downgrade() -> None:
    op.create_table(
        'case_service_confirmations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('external_case_id', sa.String(64), nullable=False),
        sa.Column('applicant_served_at', sa.Date(), nullable=True),
        sa.Column('respondent_served_at', sa.Date(), nullable=True),
        sa.Column('confirmed_by', sa.String(64), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('note', sa.String(256), nullable=True),
    )
    op.create_index(
        'ix_case_service_confirmations_external_case_id',
        'case_service_confirmations',
        ['external_case_id'],
        unique=True,
    )
