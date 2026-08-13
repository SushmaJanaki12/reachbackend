"""Multi-channel sequence steps with send_time.

Revision ID: f2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-08-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f2b3c4d5e6f7"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("campaign_sequence_steps", sa.Column("send_time", sa.String(5), server_default="10:00", nullable=False))
    op.add_column("campaign_sequence_steps", sa.Column("email_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False))
    op.add_column("campaign_sequence_steps", sa.Column("email_subject", sa.String(300), server_default="", nullable=False))
    op.add_column("campaign_sequence_steps", sa.Column("email_body", sa.Text(), server_default="", nullable=False))
    op.add_column("campaign_sequence_steps", sa.Column("whatsapp_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("campaign_sequence_steps", sa.Column("whatsapp_body", sa.Text(), server_default="", nullable=False))
    op.add_column("campaign_sequence_steps", sa.Column("sms_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("campaign_sequence_steps", sa.Column("sms_body", sa.Text(), server_default="", nullable=False))
    # backfill email fields from legacy subject/body
    op.execute(
        "UPDATE campaign_sequence_steps SET email_subject = COALESCE(subject, ''), "
        "email_body = COALESCE(body, ''), email_enabled = true "
        "WHERE (email_subject = '' OR email_subject IS NULL) AND (subject IS NOT NULL OR body IS NOT NULL)"
    )


def downgrade() -> None:
    op.drop_column("campaign_sequence_steps", "sms_body")
    op.drop_column("campaign_sequence_steps", "sms_enabled")
    op.drop_column("campaign_sequence_steps", "whatsapp_body")
    op.drop_column("campaign_sequence_steps", "whatsapp_enabled")
    op.drop_column("campaign_sequence_steps", "email_body")
    op.drop_column("campaign_sequence_steps", "email_subject")
    op.drop_column("campaign_sequence_steps", "email_enabled")
    op.drop_column("campaign_sequence_steps", "send_time")
