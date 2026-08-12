"""add_message_tracking_token

Revision ID: e2b8f4a917c5
Revises: d4a7c2f81b36
Create Date: 2026-08-11 14:00:00.000000

"""
import secrets
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2b8f4a917c5'
down_revision: Union[str, None] = 'd4a7c2f81b36'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('tracking_token', sa.String(length=48), nullable=True))

    # Backfill existing rows before the column can be made NOT NULL + unique
    # -- there's no SQL expression here that's both portable (no pgcrypto/
    # uuid-ossp dependency) and matches the app's own token format, so this
    # walks existing rows in Python instead.
    bind = op.get_bind()
    messages = sa.table('messages', sa.column('id', sa.Integer), sa.column('tracking_token', sa.String))
    ids = [row[0] for row in bind.execute(sa.text('SELECT id FROM messages')).fetchall()]
    for message_id in ids:
        bind.execute(
            messages.update().where(messages.c.id == message_id)
            .values(tracking_token=secrets.token_urlsafe(24))
        )

    op.alter_column('messages', 'tracking_token', nullable=False)
    op.create_unique_constraint('uq_messages_tracking_token', 'messages', ['tracking_token'])


def downgrade() -> None:
    op.drop_constraint('uq_messages_tracking_token', 'messages', type_='unique')
    op.drop_column('messages', 'tracking_token')
