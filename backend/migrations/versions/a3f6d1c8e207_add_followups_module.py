"""add_followups_module

Revision ID: a3f6d1c8e207
Revises: c47b1e9a3d05
Create Date: 2026-08-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f6d1c8e207'
down_revision: Union[str, None] = 'c47b1e9a3d05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('timezone', sa.String(length=60), nullable=False, server_default='UTC'))

    op.create_table(
        'follow_up_steps',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('campaign_id', sa.Integer(),
                  sa.ForeignKey('campaigns.id', ondelete='CASCADE'), nullable=False),
        sa.Column('step_order', sa.Integer(), nullable=False),
        sa.Column('trigger_type', sa.String(length=20), nullable=False),
        sa.Column('delay_value', sa.Integer(), nullable=False),
        sa.Column('delay_unit', sa.String(length=10), nullable=False, server_default='days'),
        sa.Column('send_time', sa.String(length=5), nullable=True),
        sa.Column('primary_channel', sa.String(length=20), nullable=False, server_default='email'),
        sa.Column('fallback_channel', sa.String(length=20), nullable=True),
        sa.Column('subject', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('body_template', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_follow_up_steps_campaign_id', 'follow_up_steps', ['campaign_id'])
    op.create_index('ix_followup_step_order', 'follow_up_steps', ['campaign_id', 'step_order'], unique=True)

    op.create_table(
        'campaign_follow_up_settings',
        sa.Column('campaign_id', sa.Integer(),
                  sa.ForeignKey('campaigns.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('max_touches_per_week', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('skip_weekends', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('negative_reply_handling', sa.String(length=20), nullable=False, server_default='tag_and_stop'),
        sa.Column('default_send_time', sa.String(length=5), nullable=True),
    )

    op.create_table(
        'follow_up_runs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('campaign_id', sa.Integer(),
                  sa.ForeignKey('campaigns.id', ondelete='CASCADE'), nullable=False),
        sa.Column('recipient_id', sa.Integer(),
                  sa.ForeignKey('recipients.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False, server_default='active'),
        sa.Column('next_step_order', sa.Integer(), nullable=True),
        sa.Column('scheduled_job_id', sa.String(length=60), nullable=True),
        sa.Column('last_message_id', sa.Integer(),
                  sa.ForeignKey('messages.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_follow_up_runs_campaign_id', 'follow_up_runs', ['campaign_id'])
    op.create_index('ix_follow_up_runs_recipient_id', 'follow_up_runs', ['recipient_id'])
    op.create_index('ix_followup_run_recipient', 'follow_up_runs', ['campaign_id', 'recipient_id'], unique=True)

    op.add_column('messages', sa.Column('step_id', sa.Integer(),
                  sa.ForeignKey('follow_up_steps.id', ondelete='SET NULL'), nullable=True))
    op.create_index('ix_messages_step_id', 'messages', ['step_id'])
    op.add_column('messages', sa.Column('opened_at', sa.DateTime(), nullable=True))
    op.add_column('messages', sa.Column('clicked_at', sa.DateTime(), nullable=True))
    op.add_column('messages', sa.Column('replied_at', sa.DateTime(), nullable=True))
    op.add_column('messages', sa.Column('reply_text', sa.Text(), nullable=False, server_default=''))
    op.add_column('messages', sa.Column('reply_sentiment', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('messages', 'reply_sentiment')
    op.drop_column('messages', 'reply_text')
    op.drop_column('messages', 'replied_at')
    op.drop_column('messages', 'clicked_at')
    op.drop_column('messages', 'opened_at')
    op.drop_index('ix_messages_step_id', table_name='messages')
    op.drop_column('messages', 'step_id')

    op.drop_index('ix_followup_run_recipient', table_name='follow_up_runs')
    op.drop_index('ix_follow_up_runs_recipient_id', table_name='follow_up_runs')
    op.drop_index('ix_follow_up_runs_campaign_id', table_name='follow_up_runs')
    op.drop_table('follow_up_runs')

    op.drop_table('campaign_follow_up_settings')

    op.drop_index('ix_followup_step_order', table_name='follow_up_steps')
    op.drop_index('ix_follow_up_steps_campaign_id', table_name='follow_up_steps')
    op.drop_table('follow_up_steps')

    op.drop_column('projects', 'timezone')
