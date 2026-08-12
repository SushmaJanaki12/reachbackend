"""add_message_engagement_source

Revision ID: b7d2e4f8a915
Revises: f9c3b6e1a748
Create Date: 2026-08-11 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d2e4f8a915'
down_revision: Union[str, None] = 'f9c3b6e1a748'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('engagement_source', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('messages', 'engagement_source')
