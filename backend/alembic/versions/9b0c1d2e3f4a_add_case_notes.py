"""add case_notes table

Revision ID: 9b0c1d2e3f4a
Revises: 3c4d5e6f7a8b
Create Date: 2026-08-21 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '9b0c1d2e3f4a'
down_revision: Union[str, None] = '3c4d5e6f7a8b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 案件记事本:subject_key(ext:内网 case_id / virt:预登记 id)为线程键,追加式留痕。
    op.create_table(
        'case_notes',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('subject_key', sa.String(length=80), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('stage', sa.String(length=16), nullable=False),
        sa.Column('operator', sa.String(length=64), nullable=False),
        sa.Column('client_ip', sa.String(length=45), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_case_notes_subject_key', 'case_notes', ['subject_key'])


def downgrade() -> None:
    op.drop_index('ix_case_notes_subject_key', table_name='case_notes')
    op.drop_table('case_notes')
