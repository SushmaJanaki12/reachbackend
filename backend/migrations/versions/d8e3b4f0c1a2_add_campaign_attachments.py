"""add_campaign_attachments

Revision ID: d8e3b4f0c1a2
Revises: c1d4e8f2a9b3
Create Date: 2026-07-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8e3b4f0c1a2'
down_revision: Union[str, None] = 'c1d4e8f2a9b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'campaign_attachments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('campaign_id', sa.Integer(),
                  sa.ForeignKey('campaigns.id', ondelete='CASCADE'), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('content_type', sa.String(length=120), nullable=False, server_default='application/octet-stream'),
        sa.Column('storage_path', sa.String(length=300), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_campaign_attachments_campaign_id', 'campaign_attachments', ['campaign_id'])


def downgrade() -> None:
    op.drop_index('ix_campaign_attachments_campaign_id', table_name='campaign_attachments')
    op.drop_table('campaign_attachments')
