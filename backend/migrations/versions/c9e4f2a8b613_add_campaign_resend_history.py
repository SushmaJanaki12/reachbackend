"""add_campaign_resend_history

P0.5 revised (2026-08-11): resend now archives-and-clears instead of being
blocked outright -- adds the run-number columns and the two history tables
that back app/campaign_resend.py::archive_campaign_history.

Revision ID: c9e4f2a8b613
Revises: a8d3f1c67b24
Create Date: 2026-08-11 15:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9e4f2a8b613'
down_revision: Union[str, None] = 'a8d3f1c67b24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('campaigns', sa.Column(
        'current_send_run', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('messages', sa.Column(
        'sent_run_number', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('campaign_follow_up_settings', sa.Column(
        'restart_on_resend', sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        'message_history',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('campaign_id', sa.Integer(), sa.ForeignKey('campaigns.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sent_run_number', sa.Integer(), nullable=False),
        sa.Column('recipient_id', sa.Integer(), nullable=False),
        sa.Column('channel', sa.String(20), nullable=False),
        sa.Column('to_address', sa.String(200), nullable=False, server_default=''),
        sa.Column('recipient_name', sa.String(200), nullable=False, server_default=''),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('provider_id', sa.String(120), nullable=False, server_default=''),
        sa.Column('error', sa.String(300), nullable=False, server_default=''),
        sa.Column('warnings', sa.String(300), nullable=False, server_default=''),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('delivered_at', sa.DateTime(), nullable=True),
        sa.Column('read_at', sa.DateTime(), nullable=True),
        sa.Column('tracking_token', sa.String(48), nullable=False),
        sa.Column('step_id', sa.Integer(), nullable=True),
        sa.Column('opened_at', sa.DateTime(), nullable=True),
        sa.Column('clicked_at', sa.DateTime(), nullable=True),
        sa.Column('replied_at', sa.DateTime(), nullable=True),
        sa.Column('reply_text', sa.Text(), nullable=False, server_default=''),
        sa.Column('reply_sentiment', sa.String(20), nullable=True),
        sa.Column('engagement_source', sa.String(20), nullable=True),
        sa.Column('archived_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_message_history_campaign_id', 'message_history', ['campaign_id'])
    op.create_index('ix_message_history_sent_run_number', 'message_history', ['sent_run_number'])
    op.create_index('ix_message_history_recipient_id', 'message_history', ['recipient_id'])
    op.create_index('ix_message_history_tracking_token', 'message_history', ['tracking_token'])
    op.create_index('ix_message_history_campaign_run', 'message_history', ['campaign_id', 'sent_run_number'])

    op.create_table(
        'follow_up_run_history',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('campaign_id', sa.Integer(), sa.ForeignKey('campaigns.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sent_run_number', sa.Integer(), nullable=False),
        sa.Column('recipient_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('next_step_order', sa.Integer(), nullable=True),
        sa.Column('archived_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_follow_up_run_history_campaign_id', 'follow_up_run_history', ['campaign_id'])
    op.create_index('ix_follow_up_run_history_sent_run_number', 'follow_up_run_history', ['sent_run_number'])
    op.create_index('ix_follow_up_run_history_recipient_id', 'follow_up_run_history', ['recipient_id'])


def downgrade() -> None:
    op.drop_table('follow_up_run_history')
    op.drop_table('message_history')
    op.drop_column('campaign_follow_up_settings', 'restart_on_resend')
    op.drop_column('messages', 'sent_run_number')
    op.drop_column('campaigns', 'current_send_run')
