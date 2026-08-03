"""expand_project_smtp_settings

Revision ID: 6650746aa15e
Revises: 9a1e3c5f7b21
Create Date: 2026-07-28 00:00:00.000000

"""
from email.utils import parseaddr
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6650746aa15e'
down_revision: Union[str, None] = '9a1e3c5f7b21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('smtp_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('projects', sa.Column('smtp_encryption', sa.String(length=20), nullable=False, server_default='starttls'))
    op.add_column('projects', sa.Column('smtp_from_name', sa.String(length=160), nullable=False, server_default=''))
    op.add_column('projects', sa.Column('smtp_from_email', sa.String(length=300), nullable=False, server_default=''))
    op.add_column('projects', sa.Column('smtp_reply_to', sa.String(length=300), nullable=False, server_default=''))
    op.add_column('projects', sa.Column('smtp_fallback_on_failure', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('projects', sa.Column('smtp_max_per_minute', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('projects', sa.Column('smtp_last_tested_at', sa.DateTime(), nullable=True))
    op.add_column('projects', sa.Column('smtp_last_test_status', sa.String(length=20), nullable=False, server_default='never'))

    # Data backfill, then drop the old combined column:
    #  - smtp_from_address ("Acme <noreply@acme.com>") -> smtp_from_name + smtp_from_email
    #  - smtp_password: this was never actually read on the send path (that's
    #    the bug this migration accompanies), so any value already saved here
    #    is plaintext from the project "Save changes" form. Encrypt it now so
    #    nothing plaintext lands in the newly-wired-up send path.
    from app.crypto import encrypt_secret

    conn = op.get_bind()
    projects = sa.table(
        'projects',
        sa.column('id', sa.Integer),
        sa.column('smtp_from_address', sa.String),
        sa.column('smtp_from_name', sa.String),
        sa.column('smtp_from_email', sa.String),
        sa.column('smtp_password', sa.String),
    )
    rows = conn.execute(sa.select(projects.c.id, projects.c.smtp_from_address, projects.c.smtp_password)).fetchall()
    for row in rows:
        name, email_addr = parseaddr(row.smtp_from_address or "")
        values = {}
        if email_addr:
            values['smtp_from_email'] = email_addr
            values['smtp_from_name'] = name or ''
        if row.smtp_password:
            values['smtp_password'] = encrypt_secret(row.smtp_password)
        if values:
            conn.execute(projects.update().where(projects.c.id == row.id).values(**values))

    op.drop_column('projects', 'smtp_from_address')


def downgrade() -> None:
    op.add_column('projects', sa.Column('smtp_from_address', sa.String(length=300), nullable=False, server_default=''))

    from app.crypto import decrypt_secret

    conn = op.get_bind()
    projects = sa.table(
        'projects',
        sa.column('id', sa.Integer),
        sa.column('smtp_from_address', sa.String),
        sa.column('smtp_from_name', sa.String),
        sa.column('smtp_from_email', sa.String),
        sa.column('smtp_password', sa.String),
    )
    rows = conn.execute(sa.select(projects.c.id, projects.c.smtp_from_name, projects.c.smtp_from_email, projects.c.smtp_password)).fetchall()
    for row in rows:
        if row.smtp_from_email:
            combined = f"{row.smtp_from_name} <{row.smtp_from_email}>" if row.smtp_from_name else row.smtp_from_email
            conn.execute(projects.update().where(projects.c.id == row.id).values(smtp_from_address=combined))
        if row.smtp_password:
            conn.execute(projects.update().where(projects.c.id == row.id).values(smtp_password=decrypt_secret(row.smtp_password)))

    op.drop_column('projects', 'smtp_last_test_status')
    op.drop_column('projects', 'smtp_last_tested_at')
    op.drop_column('projects', 'smtp_max_per_minute')
    op.drop_column('projects', 'smtp_fallback_on_failure')
    op.drop_column('projects', 'smtp_reply_to')
    op.drop_column('projects', 'smtp_from_email')
    op.drop_column('projects', 'smtp_from_name')
    op.drop_column('projects', 'smtp_encryption')
    op.drop_column('projects', 'smtp_enabled')
