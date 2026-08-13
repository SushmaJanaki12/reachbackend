"""add_smtp_provider_to_projects

Revision ID: f4b7d2e9a6c1
Revises: d8e3b4f0c1a2
Create Date: 2026-07-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4b7d2e9a6c1'
down_revision: Union[str, None] = 'd8e3b4f0c1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'projects',
        sa.Column('smtp_provider', sa.String(length=20), nullable=False, server_default='custom'),
    )


def downgrade() -> None:
    op.drop_column('projects', 'smtp_provider')
