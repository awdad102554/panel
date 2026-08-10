"""add system settings table

时限设置功能:system_settings key-value 表,存用户可调的提醒阈值
(时效临近/中止过久/调解超时/同步间隔)。

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-31 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'system_settings',
        sa.Column('key', sa.String(64), primary_key=True),
        sa.Column('value', sa.String(128), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('system_settings')
