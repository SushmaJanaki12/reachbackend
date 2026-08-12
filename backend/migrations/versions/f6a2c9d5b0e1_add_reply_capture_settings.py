"""add_reply_capture_settings

Revision ID: f6a2c9d5b0e1
Revises: e2b8f4a917c5
Create Date: 2026-08-11 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6a2c9d5b0e1'
down_revision: Union[str, None] = 'e2b8f4a917c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'reply_capture_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('mailbox_address', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('imap_host', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('imap_port', sa.Integer(), nullable=False, server_default='993'),
        sa.Column('imap_use_ssl', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('imap_username', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('imap_password', sa.String(length=500), nullable=False, server_default=''),
        sa.Column('poll_folder', sa.String(length=120), nullable=False, server_default='INBOX'),
        sa.Column('poll_interval_seconds', sa.Integer(), nullable=False, server_default='120'),
        sa.Column('last_polled_at', sa.DateTime(), nullable=True),
        sa.Column('last_poll_status', sa.String(length=20), nullable=False, server_default='never'),
        sa.Column('last_poll_error', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('reply_capture_settings')
