"""Add campaign sequence steps and warmup fields.

Revision ID: f1a2b3c4d5e6
Revises: e7a1b2c3d4f5
Create Date: 2026-08-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e7a1b2c3d4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table_name: str, column_name: str) -> bool:
    """Return whether a column already exists in the target database.

    This revision can be applied to databases where the campaign warmup
    columns were provisioned before the migration was introduced.
    """
    return column_name in {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _has_index(table_name: str, index_name: str) -> bool:
    return index_name in {
        index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    }


def upgrade() -> None:
    warmup_columns = (
        ("warmup_enabled", sa.Column("warmup_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False)),
        ("warmup_daily_cap", sa.Column("warmup_daily_cap", sa.Integer(), server_default="50", nullable=False)),
        ("warmup_started_at", sa.Column("warmup_started_at", sa.DateTime(), nullable=True)),
    )
    for name, column in warmup_columns:
        if not _has_column("campaigns", name):
            op.add_column("campaigns", column)

    if not _has_table("campaign_sequence_steps"):
        op.create_table(
            "campaign_sequence_steps",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
            sa.Column("step_number", sa.Integer(), server_default="0", nullable=False),
            sa.Column("label", sa.String(120), server_default="", nullable=False),
            sa.Column("delay_days", sa.Integer(), server_default="0", nullable=False),
            sa.Column("channel", sa.String(20), server_default="email", nullable=False),
            sa.Column("subject", sa.String(300), server_default="", nullable=False),
            sa.Column("body", sa.Text(), server_default="", nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        )
    if not _has_index("campaign_sequence_steps", "ix_campaign_sequence_steps_campaign_id"):
        op.create_index("ix_campaign_sequence_steps_campaign_id", "campaign_sequence_steps", ["campaign_id"])
    if not _has_index("campaign_sequence_steps", "ix_sequence_step_campaign_num"):
        op.create_index(
            "ix_sequence_step_campaign_num",
            "campaign_sequence_steps",
            ["campaign_id", "step_number"],
            unique=True,
        )


def downgrade() -> None:
    op.drop_index("ix_sequence_step_campaign_num", table_name="campaign_sequence_steps")
    op.drop_index("ix_campaign_sequence_steps_campaign_id", table_name="campaign_sequence_steps")
    op.drop_table("campaign_sequence_steps")
    op.drop_column("campaigns", "warmup_started_at")
    op.drop_column("campaigns", "warmup_daily_cap")
    op.drop_column("campaigns", "warmup_enabled")
