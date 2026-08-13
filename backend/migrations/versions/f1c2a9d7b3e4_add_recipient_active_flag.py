"""add_recipient_active_flag

Revision ID: f1c2a9d7b3e4
Revises: a4a11e2724d3
Create Date: 2026-07-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1c2a9d7b3e4'
down_revision: Union[str, None] = 'a4a11e2724d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('recipients', sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column('recipients', 'active')
