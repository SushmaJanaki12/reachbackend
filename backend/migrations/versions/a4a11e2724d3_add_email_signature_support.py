"""add_email_signature_support

Revision ID: a4a11e2724d3
Revises: eb2d61d60657
Create Date: 2026-07-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4a11e2724d3'
down_revision: Union[str, None] = 'eb2d61d60657'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('signature', sa.JSON(), nullable=False, server_default='{}'))
    op.add_column('campaign_content', sa.Column('is_html', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('messages', sa.Column('warnings', sa.String(length=300), nullable=False, server_default=''))


def downgrade() -> None:
    op.drop_column('messages', 'warnings')
    op.drop_column('campaign_content', 'is_html')
    op.drop_column('projects', 'signature')
