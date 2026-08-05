"""restore_message_templates_module

Revision ID: c47b1e9a3d05
Revises: e5d8a2c6f913
Create Date: 2026-08-04 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c47b1e9a3d05'
down_revision: Union[str, None] = 'e5d8a2c6f913'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Project branding, reused by the Email template library's live preview
    # and rendered shell (see app/email_template.py). Unlike the previous
    # incarnation of this module, campaign content itself no longer has a
    # "template" mode -- these fields are now only consumed by the standalone
    # Templates library, not by campaign sending.
    op.add_column('projects', sa.Column('company_website', sa.String(length=300), nullable=False, server_default=''))
    op.add_column('projects', sa.Column('company_address', sa.String(length=300), nullable=False, server_default=''))
    op.add_column('projects', sa.Column('sender_name', sa.String(length=160), nullable=False, server_default=''))
    op.add_column('projects', sa.Column('sender_designation', sa.String(length=160), nullable=False, server_default=''))
    op.add_column('projects', sa.Column('sender_phone', sa.String(length=60), nullable=False, server_default=''))
    op.add_column('projects', sa.Column('badge1_url', sa.String(length=300), nullable=False, server_default=''))
    op.add_column('projects', sa.Column('badge2_url', sa.String(length=300), nullable=False, server_default=''))
    op.add_column('projects', sa.Column('badge3_url', sa.String(length=300), nullable=False, server_default=''))

    op.create_table(
        'template_categories',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=80), nullable=False, unique=True),
    )

    op.create_table(
        'templates',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('channel', sa.String(length=20), nullable=False),
        sa.Column('category_id', sa.Integer(), sa.ForeignKey('template_categories.id'), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        'email_template_content',
        sa.Column('template_id', sa.Integer(),
                  sa.ForeignKey('templates.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('subject', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('fields', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('branding_override', sa.JSON(), nullable=True),
    )

    op.create_table(
        'whatsapp_template_content',
        sa.Column('template_id', sa.Integer(),
                  sa.ForeignKey('templates.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('meta_template_name', sa.String(length=160), nullable=False),
        sa.Column('meta_template_id', sa.String(length=120), nullable=False),
        sa.Column('language_code', sa.String(length=20), nullable=False),
        sa.Column('header_type', sa.String(length=20), nullable=False, server_default='none'),
        sa.Column('header_content', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('body_text', sa.Text(), nullable=False),
        sa.Column('footer_text', sa.String(length=160), nullable=False, server_default=''),
        sa.Column('buttons', sa.JSON(), nullable=False, server_default='[]'),
    )

    # New (not part of the original module): lets an Email template carry
    # suggested/standard attachments, same local-disk storage as campaign
    # attachments (see app/storage.py).
    op.create_table(
        'template_attachments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('template_id', sa.Integer(),
                  sa.ForeignKey('templates.id', ondelete='CASCADE'), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('content_type', sa.String(length=120), nullable=False, server_default='application/octet-stream'),
        sa.Column('storage_path', sa.String(length=300), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_template_attachments_template_id', 'template_attachments', ['template_id'])


def downgrade() -> None:
    op.drop_index('ix_template_attachments_template_id', table_name='template_attachments')
    op.drop_table('template_attachments')
    op.drop_table('whatsapp_template_content')
    op.drop_table('email_template_content')
    op.drop_table('templates')
    op.drop_table('template_categories')

    op.drop_column('projects', 'badge3_url')
    op.drop_column('projects', 'badge2_url')
    op.drop_column('projects', 'badge1_url')
    op.drop_column('projects', 'sender_phone')
    op.drop_column('projects', 'sender_designation')
    op.drop_column('projects', 'sender_name')
    op.drop_column('projects', 'company_address')
    op.drop_column('projects', 'company_website')
