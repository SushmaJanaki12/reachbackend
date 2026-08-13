"""add_email_template_support

Revision ID: d3f9a1c2b6e7
Revises: 872f648af238
Create Date: 2026-07-24 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3f9a1c2b6e7'
down_revision: Union[str, None] = '872f648af238'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('company_website', sa.String(length=300), nullable=False, server_default=''))
    op.add_column('projects', sa.Column('company_address', sa.String(length=300), nullable=False, server_default=''))
    op.add_column('projects', sa.Column('sender_name', sa.String(length=160), nullable=False, server_default=''))
    op.add_column('projects', sa.Column('sender_designation', sa.String(length=160), nullable=False, server_default=''))
    op.add_column('projects', sa.Column('sender_phone', sa.String(length=60), nullable=False, server_default=''))
    op.add_column('projects', sa.Column('badge1_url', sa.String(length=300), nullable=False, server_default=''))
    op.add_column('projects', sa.Column('badge2_url', sa.String(length=300), nullable=False, server_default=''))
    op.add_column('projects', sa.Column('badge3_url', sa.String(length=300), nullable=False, server_default=''))

    op.add_column('campaign_content', sa.Column('content_mode', sa.String(length=20), nullable=False, server_default='plain'))
    op.add_column('campaign_content', sa.Column('template_fields', sa.JSON(), nullable=False, server_default='{}'))


def downgrade() -> None:
    op.drop_column('campaign_content', 'template_fields')
    op.drop_column('campaign_content', 'content_mode')

    op.drop_column('projects', 'badge3_url')
    op.drop_column('projects', 'badge2_url')
    op.drop_column('projects', 'badge1_url')
    op.drop_column('projects', 'sender_phone')
    op.drop_column('projects', 'sender_designation')
    op.drop_column('projects', 'sender_name')
    op.drop_column('projects', 'company_address')
    op.drop_column('projects', 'company_website')
