"""add_is_test_campaign_flag

Revision ID: f9c3b6e1a748
Revises: a3f6d1c8e207
Create Date: 2026-08-11 12:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f9c3b6e1a748'
down_revision: Union[str, None] = 'a3f6d1c8e207'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('campaigns', sa.Column(
        'is_test_campaign', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('campaigns', 'is_test_campaign')
