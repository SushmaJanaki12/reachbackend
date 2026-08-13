"""index_campaign_fk_columns

Postgres does not auto-index foreign key columns (only primary keys), and
none of the prior migrations added one for these. Every recipient/content
lookup filters by campaign_id, so as row counts grow in production this
turns into a sequential scan across the whole table -- invisible in local
dev where these tables only hold a handful of seed rows.

Revision ID: 9a1e3c5f7b21
Revises: d3f9a1c2b6e7
Create Date: 2026-07-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '9a1e3c5f7b21'
down_revision: Union[str, None] = 'd3f9a1c2b6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(op.f('ix_recipients_campaign_id'), 'recipients', ['campaign_id'])
    op.create_index(op.f('ix_campaign_content_campaign_id'), 'campaign_content', ['campaign_id'])
    op.create_index(op.f('ix_messages_campaign_id'), 'messages', ['campaign_id'])
    op.create_index(op.f('ix_messages_recipient_id'), 'messages', ['recipient_id'])
    op.create_index(op.f('ix_campaigns_project_id'), 'campaigns', ['project_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_campaigns_project_id'), table_name='campaigns')
    op.drop_index(op.f('ix_messages_recipient_id'), table_name='messages')
    op.drop_index(op.f('ix_messages_campaign_id'), table_name='messages')
    op.drop_index(op.f('ix_campaign_content_campaign_id'), table_name='campaign_content')
    op.drop_index(op.f('ix_recipients_campaign_id'), table_name='recipients')
