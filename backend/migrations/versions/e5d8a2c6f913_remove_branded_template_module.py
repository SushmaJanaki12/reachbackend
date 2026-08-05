"""remove_branded_template_module

Revision ID: e5d8a2c6f913
Revises: b2e6f1a9d4c7
Create Date: 2026-08-03 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5d8a2c6f913'
down_revision: Union[str, None] = 'b2e6f1a9d4c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Content is now authored as plain text or via Generative AI only --
    # the fixed branded HTML shell (content_mode == 'template') and the
    # reusable Email/WhatsApp template library are being removed.
    op.drop_column('sms_templates', 'parent_template_id')
    op.drop_column('campaign_content', 'source_template_id')
    op.drop_column('campaign_content', 'template_fields')
    op.drop_column('campaign_content', 'content_mode')

    op.drop_table('whatsapp_template_content')
    op.drop_table('email_template_content')
    op.drop_table('templates')
    op.drop_table('template_categories')

    # These project fields only ever fed the branded template shell's
    # CompanyWebsite/SenderName/etc. placeholders (see app/email_template.py,
    # now removed) -- unused now that path is gone.
    op.drop_column('projects', 'badge3_url')
    op.drop_column('projects', 'badge2_url')
    op.drop_column('projects', 'badge1_url')
    op.drop_column('projects', 'sender_phone')
    op.drop_column('projects', 'sender_designation')
    op.drop_column('projects', 'sender_name')
    op.drop_column('projects', 'company_address')
    op.drop_column('projects', 'company_website')


def downgrade() -> None:
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

    op.add_column('campaign_content', sa.Column(
        'content_mode', sa.String(length=20), nullable=False, server_default='plain'))
    op.add_column('campaign_content', sa.Column(
        'template_fields', sa.JSON(), nullable=False, server_default='{}'))
    op.add_column('campaign_content', sa.Column(
        'source_template_id', sa.Integer(),
        sa.ForeignKey('templates.id', ondelete='SET NULL'), nullable=True))

    op.add_column('sms_templates', sa.Column(
        'parent_template_id', sa.Integer(),
        sa.ForeignKey('templates.id', ondelete='SET NULL'), nullable=True))
