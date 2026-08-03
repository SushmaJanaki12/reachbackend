"""add_message_templates_module

Revision ID: a1c4e9f27b53
Revises: f4b7d2e9a6c1
Create Date: 2026-07-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c4e9f27b53'
down_revision: Union[str, None] = 'f4b7d2e9a6c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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
        'source_template_id', sa.Integer(),
        sa.ForeignKey('templates.id', ondelete='SET NULL'), nullable=True))

    op.add_column('sms_templates', sa.Column(
        'parent_template_id', sa.Integer(),
        sa.ForeignKey('templates.id', ondelete='SET NULL'), nullable=True))

    # Backfill: give every pre-existing sms_templates row a library umbrella
    # `templates` row so it shows up in the new Templates page alongside
    # Email/WhatsApp, without touching sms_templates.id or any of the
    # existing send-path columns (template_id/sender_id/body/is_active).
    conn = op.get_bind()
    sms_templates = sa.table(
        'sms_templates',
        sa.column('id', sa.Integer),
        sa.column('name', sa.String),
        sa.column('is_active', sa.Boolean),
        sa.column('parent_template_id', sa.Integer),
    )
    templates = sa.table(
        'templates',
        sa.column('id', sa.Integer),
        sa.column('name', sa.String),
        sa.column('channel', sa.String),
        sa.column('status', sa.String),
    )
    rows = conn.execute(sa.select(sms_templates.c.id, sms_templates.c.name, sms_templates.c.is_active)).fetchall()
    for row in rows:
        new_id = conn.execute(
            templates.insert().values(
                name=row.name, channel='sms',
                status='published' if row.is_active else 'archived',
            ).returning(templates.c.id)
        ).scalar_one()
        conn.execute(
            sms_templates.update()
            .where(sms_templates.c.id == row.id)
            .values(parent_template_id=new_id)
        )


def downgrade() -> None:
    op.drop_column('sms_templates', 'parent_template_id')
    op.drop_column('campaign_content', 'source_template_id')
    op.drop_table('whatsapp_template_content')
    op.drop_table('email_template_content')
    op.drop_table('templates')
    op.drop_table('template_categories')
