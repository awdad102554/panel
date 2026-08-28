"""Create company_agent_bindings table

Revision ID: add_company_agent_bindings
Revises:
Create Date: 2026-08-28

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_company_agent_bindings'
down_revision = 'e1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'company_agent_bindings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_name', sa.String(length=255), nullable=False),
        sa.Column('company_credit_code', sa.String(length=64), nullable=True),
        sa.Column('agent_name', sa.String(length=64), nullable=False),
        sa.Column('agent_type', sa.Integer(), nullable=False),
        sa.Column('agent_phone', sa.String(length=32), nullable=True),
        sa.Column('agent_law_firm', sa.String(length=255), nullable=True),
        sa.Column('agent_id_number', sa.String(length=64), nullable=True),
        sa.Column('party_role', sa.String(length=16), nullable=False),
        sa.Column('external_case_id', sa.String(length=64), nullable=False),
        sa.Column('case_no', sa.String(length=64), nullable=True),
        sa.Column('filed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_name', 'agent_name', 'external_case_id', name='uk_company_agent_case')
    )
    op.create_index('idx_company_agent_bindings_company_name', 'company_agent_bindings', ['company_name'])
    op.create_index('idx_company_agent_bindings_agent_name', 'company_agent_bindings', ['agent_name'])
    op.create_index('idx_company_agent_bindings_external_case_id', 'company_agent_bindings', ['external_case_id'])
    op.create_index('idx_company_agent_bindings_filed_at', 'company_agent_bindings', ['filed_at'])
    op.create_index('idx_filed_at_desc', 'company_agent_bindings', [sa.text('filed_at DESC')])


def downgrade() -> None:
    op.drop_index('idx_filed_at_desc', table_name='company_agent_bindings')
    op.drop_index('idx_company_agent_bindings_filed_at', table_name='company_agent_bindings')
    op.drop_index('idx_company_agent_bindings_external_case_id', table_name='company_agent_bindings')
    op.drop_index('idx_company_agent_bindings_agent_name', table_name='company_agent_bindings')
    op.drop_index('idx_company_agent_bindings_company_name', table_name='company_agent_bindings')
    op.drop_table('company_agent_bindings')
