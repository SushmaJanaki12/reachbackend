"""add_campaign_sending_since_and_message_updated_at

Revision ID: d4a7c2f81b36
Revises: b7d2e4f8a915
Create Date: 2026-08-11 13:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4a7c2f81b36'
down_revision: Union[str, None] = 'b7d2e4f8a915'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('campaigns', sa.Column('sending_since', sa.DateTime(), nullable=True))
    op.add_column('messages', sa.Column(
        'updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()))


def downgrade() -> None:
    op.drop_column('messages', 'updated_at')
    op.drop_column('campaigns', 'sending_since')
