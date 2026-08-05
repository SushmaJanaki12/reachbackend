"""add_dataset_validation

Revision ID: b2e6f1a9d4c7
Revises: a1c4e9f27b53
Create Date: 2026-08-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2e6f1a9d4c7'
down_revision: Union[str, None] = 'a1c4e9f27b53'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('recipients', sa.Column('batch_import_id', sa.String(length=36), nullable=True))
    op.create_index('ix_recipients_batch_import_id', 'recipients', ['batch_import_id'])

    op.create_table(
        'dataset_validation_sessions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('campaign_id', sa.Integer(), sa.ForeignKey('campaigns.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('original_filename', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('column_mapping', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('mapping_confirmed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('raw_rows', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('working_rows', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('issues', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('summary', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('quality_score', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),
        sa.Column('batch_import_id', sa.String(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('imported_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_dataset_validation_sessions_campaign_id', 'dataset_validation_sessions', ['campaign_id'])

    op.create_table(
        'validation_override_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('session_id', sa.Integer(),
                  sa.ForeignKey('dataset_validation_sessions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('campaign_id', sa.Integer(), sa.ForeignKey('campaigns.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('warning_row_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('warning_types', sa.JSON(), nullable=False, server_default='[]'),
    )
    op.create_index('ix_validation_override_logs_campaign_id', 'validation_override_logs', ['campaign_id'])


def downgrade() -> None:
    op.drop_index('ix_validation_override_logs_campaign_id', table_name='validation_override_logs')
    op.drop_table('validation_override_logs')
    op.drop_index('ix_dataset_validation_sessions_campaign_id', table_name='dataset_validation_sessions')
    op.drop_table('dataset_validation_sessions')
    op.drop_index('ix_recipients_batch_import_id', table_name='recipients')
    op.drop_column('recipients', 'batch_import_id')
