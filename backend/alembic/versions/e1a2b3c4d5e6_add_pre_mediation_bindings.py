"""add pre_mediation_bindings table

案前调解→立案 一对一绑定表(详见 app/models/pre_mediation_binding.py)。

Revision ID: e1a2b3c4d5e6
Revises: a0b1c2d3e4f5
Create Date: 2026-08-24 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'e1a2b3c4d5e6'
down_revision: Union[str, None] = 'a0b1c2d3e4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'pre_mediation_bindings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('receive_external_case_id', sa.String(length=64), nullable=False),
        sa.Column('handle_external_case_id', sa.String(length=64), nullable=False),
        sa.Column('handle_case_no', sa.String(length=64), nullable=True),
        sa.Column('bound_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        'ix_pre_mediation_bindings_receive_external_case_id',
        'pre_mediation_bindings',
        ['receive_external_case_id'],
        unique=True,
    )
    op.create_index(
        'ix_pre_mediation_bindings_handle_external_case_id',
        'pre_mediation_bindings',
        ['handle_external_case_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_pre_mediation_bindings_handle_external_case_id', table_name='pre_mediation_bindings')
    op.drop_index('ix_pre_mediation_bindings_receive_external_case_id', table_name='pre_mediation_bindings')
    op.drop_table('pre_mediation_bindings')
