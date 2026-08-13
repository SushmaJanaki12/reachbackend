"""add sequence engagement and followup fields

Revision ID: e7a1b2c3d4f5
Revises: 
Create Date: 2026-08-03
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# NOTE: set revises to your latest revision id if chaining; otherwise run as needed.
revision: str = "e7a1b2c3d4f5"
#down_revision: Union[str, None] = None
down_revision: Union[str, None] = "a1c4e9f27b53"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # campaigns
    op.add_column("campaigns", sa.Column("followup_enabled", sa.Boolean(), server_default="true", nullable=False))
    op.add_column("campaigns", sa.Column("followup_interval_days", sa.Integer(), server_default="3", nullable=False))
    op.add_column("campaigns", sa.Column("max_followups", sa.Integer(), server_default="3", nullable=False))
    op.add_column("campaigns", sa.Column("ai_goal", sa.String(length=300), server_default="", nullable=False))
    op.add_column("campaigns", sa.Column("ai_tone", sa.String(length=40), server_default="professional", nullable=False))
    # recipients
    op.add_column("recipients", sa.Column("reply_status", sa.String(length=20), server_default="not_replied", nullable=False))
    op.add_column("recipients", sa.Column("interest_status", sa.String(length=20), server_default="none", nullable=False))
    op.add_column("recipients", sa.Column("campaign_stopped", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("recipients", sa.Column("stop_reason", sa.String(length=80), server_default="", nullable=False))
    op.add_column("recipients", sa.Column("followup_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("recipients", sa.Column("last_followup_at", sa.DateTime(), nullable=True))
    op.add_column("recipients", sa.Column("next_followup_at", sa.DateTime(), nullable=True))
    op.add_column("recipients", sa.Column("call_scheduled_at", sa.DateTime(), nullable=True))
    op.add_column("recipients", sa.Column("call_notes", sa.String(length=500), server_default="", nullable=False))
    # messages
    op.add_column("messages", sa.Column("is_followup", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("messages", sa.Column("followup_number", sa.Integer(), server_default="0", nullable=False))
    op.add_column("messages", sa.Column("sequence_step", sa.String(length=40), server_default="initial", nullable=False))


def downgrade() -> None:
    for col in ("is_followup", "followup_number", "sequence_step"):
        op.drop_column("messages", col)
    for col in (
        "reply_status", "interest_status", "campaign_stopped", "stop_reason",
        "followup_count", "last_followup_at", "next_followup_at",
        "call_scheduled_at", "call_notes",
    ):
        op.drop_column("recipients", col)
    for col in ("followup_enabled", "followup_interval_days", "max_followups", "ai_goal", "ai_tone"):
        op.drop_column("campaigns", col)
