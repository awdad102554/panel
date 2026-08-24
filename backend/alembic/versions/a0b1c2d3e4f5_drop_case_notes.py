"""drop case_notes table

案件标签(case_tags)迁到共享 MySQL(与 InfoWeb 同库),不再落 PG 的 case_notes 表。

Revision ID: a0b1c2d3e4f5
Revises: 9b0c1d2e3f4a
Create Date: 2026-08-21 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a0b1c2d3e4f5'
down_revision: Union[str, None] = '9b0c1d2e3f4a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('ix_case_notes_subject_key', table_name='case_notes')
    op.drop_table('case_notes')


def downgrade() -> None:
    # 无法还原数据,仅重建空表结构(标签已迁 MySQL,此降级仅用于回滚迁移链一致性)。
    import sqlalchemy as sa
    from sqlalchemy.dialects import postgresql

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
