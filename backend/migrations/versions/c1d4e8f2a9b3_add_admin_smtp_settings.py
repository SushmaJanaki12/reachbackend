"""add_admin_smtp_settings

Revision ID: c1d4e8f2a9b3
Revises: 6650746aa15e
Create Date: 2026-07-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1d4e8f2a9b3'
down_revision: Union[str, None] = '6650746aa15e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'smtp_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('provider', sa.String(length=20), nullable=False, server_default='custom'),
        sa.Column('smtp_host', sa.String(length=200), nullable=False),
        sa.Column('smtp_port', sa.Integer(), nullable=False, server_default='587'),
        sa.Column('encryption', sa.String(length=20), nullable=False, server_default='starttls'),
        sa.Column('username', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('password', sa.String(length=500), nullable=False, server_default=''),
        sa.Column('from_email', sa.String(length=300), nullable=False),
        sa.Column('from_name', sa.String(length=160), nullable=False, server_default=''),
        sa.Column('reply_to', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('max_per_minute', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('last_tested_at', sa.DateTime(), nullable=True),
        sa.Column('last_test_status', sa.String(length=20), nullable=False, server_default='never'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    # At most one active row -- a plain unique index on is_active would only
    # allow ONE row total (both True and False values would collide across
    # rows), so index only the rows where is_active is true. Postgres allows
    # any number of rows matching the WHERE predicate to be absent from the
    # index; only rows where is_active=true are compared for uniqueness, and
    # since they'd all index the same value (true), a second one collides.
    op.create_index(
        'ix_smtp_settings_one_active', 'smtp_settings', ['is_active'],
        unique=True, postgresql_where=sa.text('is_active'),
    )


def downgrade() -> None:
    op.drop_index('ix_smtp_settings_one_active', table_name='smtp_settings')
    op.drop_table('smtp_settings')
