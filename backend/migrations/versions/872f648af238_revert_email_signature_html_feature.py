"""revert_email_signature_html_feature

Revision ID: 872f648af238
Revises: f1c2a9d7b3e4
Create Date: 2026-07-24 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '872f648af238'
down_revision: Union[str, None] = 'f1c2a9d7b3e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('campaign_content', 'is_html')
    op.drop_column('projects', 'signature')


def downgrade() -> None:
    op.add_column('projects', sa.Column('signature', sa.JSON(), nullable=False, server_default='{}'))
    op.add_column('campaign_content', sa.Column('is_html', sa.Boolean(), nullable=False, server_default=sa.false()))
