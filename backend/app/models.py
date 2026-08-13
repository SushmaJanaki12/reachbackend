from datetime import datetime

from sqlalchemy import (
    String, Text, Boolean, DateTime, ForeignKey, Table, Column, JSON, func, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


# ---- association tables ----
role_permissions = Table(
    "role_permissions", Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)

user_projects = Table(
    "user_projects", Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("project_id", ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
)


class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    module: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(120))


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    description: Mapped[str] = mapped_column(String(200), default="")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    permissions: Mapped[list[Permission]] = relationship(secondary=role_permissions, lazy="selectin")
    users: Mapped[list["User"]] = relationship(back_populates="role")


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    role: Mapped[Role] = relationship(back_populates="users", lazy="joined")
    projects: Mapped[list["Project"]] = relationship(secondary=user_projects, lazy="selectin")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    logo_url: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|inactive|archived

    # Branding used by the "branded template" email content mode (CompanyName /
    # CompanyLogoUrl come from `name` / `logo_url` above -- not duplicated here).
    company_website: Mapped[str] = mapped_column(String(300), default="")
    company_address: Mapped[str] = mapped_column(String(300), default="")
    sender_name: Mapped[str] = mapped_column(String(160), default="")
    sender_designation: Mapped[str] = mapped_column(String(160), default="")
    sender_phone: Mapped[str] = mapped_column(String(60), default="")
    badge1_url: Mapped[str] = mapped_column(String(300), default="")
    badge2_url: Mapped[str] = mapped_column(String(300), default="")
    badge3_url: Mapped[str] = mapped_column(String(300), default="")

    # Channel availability
    sms_active: Mapped[bool] = mapped_column(Boolean, default=False)
    sms_provider: Mapped[str] = mapped_column(String(80), default="")
    whatsapp_active: Mapped[bool] = mapped_column(Boolean, default=False)
    whatsapp_provider: Mapped[str] = mapped_column(String(80), default="")

    # Per-project SMTP override (optional — falls back to global O365 config).
    # Only used to actually send when smtp_enabled and smtp_host/port/from_email
    # are all present -- see app/mailer.py::send_campaign_email.
    smtp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    smtp_provider: Mapped[str] = mapped_column(String(20), default="custom")  # gmail|outlook|zoho|custom
    smtp_host: Mapped[str] = mapped_column(String(200), default="")
    smtp_port: Mapped[int] = mapped_column(default=587)
    smtp_encryption: Mapped[str] = mapped_column(String(20), default="starttls")  # none|starttls|ssl
    smtp_username: Mapped[str] = mapped_column(String(200), default="")
    smtp_password: Mapped[str] = mapped_column(String(500), default="")  # encrypted at rest, see app/crypto.py
    smtp_from_name: Mapped[str] = mapped_column(String(160), default="")
    smtp_from_email: Mapped[str] = mapped_column(String(300), default="")
    smtp_reply_to: Mapped[str] = mapped_column(String(300), default="")
    # If the project SMTP send fails mid-campaign: retry via O365 (True) or
    # hard-fail and flag the recipient as failed (False, default).
    smtp_fallback_on_failure: Mapped[bool] = mapped_column(Boolean, default=False)
    smtp_max_per_minute: Mapped[int] = mapped_column(default=0)  # 0 = unlimited
    smtp_last_tested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    smtp_last_test_status: Mapped[str] = mapped_column(String(20), default="never")  # ok|failed|never

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    campaigns: Mapped[list["Campaign"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class SmtpSettings(Base):
    """Admin-level (workspace-default) SMTP configuration -- tier 3 in the
    campaign email resolver, between a project's own override (tier 2) and
    the hardcoded O365/Graph fallback (tier 4). See app/mailer.py.

    Exactly one row may have is_active=True at a time; enforced by a partial
    unique index (see migration), not just at the application layer.
    """
    __tablename__ = "smtp_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(20), default="custom")  # gmail|outlook|zoho|custom
    smtp_host: Mapped[str] = mapped_column(String(200))
    smtp_port: Mapped[int] = mapped_column(default=587)
    encryption: Mapped[str] = mapped_column(String(20), default="starttls")  # none|starttls|ssl
    username: Mapped[str] = mapped_column(String(200), default="")
    password: Mapped[str] = mapped_column(String(500), default="")  # encrypted at rest, see app/crypto.py
    from_email: Mapped[str] = mapped_column(String(300))
    from_name: Mapped[str] = mapped_column(String(160), default="")
    reply_to: Mapped[str] = mapped_column(String(300), default="")
    max_per_minute: Mapped[int] = mapped_column(default=0)  # 0 = unlimited
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_test_status: Mapped[str] = mapped_column(String(20), default="never")  # ok|failed|never
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    project: Mapped[Project] = relationship(back_populates="campaigns")
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|active|sending|completed

    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    whatsapp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sms_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    # Optional link to a registered DLT SMS template (for compliant SMS)
    sms_template_ref: Mapped[int | None] = mapped_column(ForeignKey("sms_templates.id"), nullable=True)

    # Follow-up sequence (Saleshandy-style)
    followup_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    followup_interval_days: Mapped[int] = mapped_column(default=3)
    max_followups: Mapped[int] = mapped_column(default=3)
    ai_goal: Mapped[str] = mapped_column(String(300), default="")
    ai_tone: Mapped[str] = mapped_column(String(40), default="professional")  # professional|friendly|direct

    # Warmup / deliverability controls (daily volume ramp for inbox placement)
    warmup_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    warmup_daily_cap: Mapped[int] = mapped_column(default=50)  # max emails/day when warmup is on
    warmup_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    recipients: Mapped[list["Recipient"]] = relationship(back_populates="campaign", cascade="all, delete-orphan",
                                                          order_by="Recipient.id")
    contents: Mapped[list["CampaignContent"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")
    messages: Mapped[list["Message"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")
    attachments: Mapped[list["CampaignAttachment"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")
    sequence_steps: Mapped[list["CampaignSequenceStep"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan", order_by="CampaignSequenceStep.step_number"
    )


class Recipient(Base):
    __tablename__ = "recipients"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    campaign: Mapped[Campaign] = relationship(back_populates="recipients")
    name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    mobile: Mapped[str] = mapped_column(String(60), default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)  # all columns
    active: Mapped[bool] = mapped_column(default=True)  # inactive recipients are skipped on send

    # Engagement / sequence state
    # reply_status: not_replied | replied
    reply_status: Mapped[str] = mapped_column(String(20), default="not_replied")
    # interest_status: none | interested | not_interested  (only meaningful when replied)
    interest_status: Mapped[str] = mapped_column(String(20), default="none")
    campaign_stopped: Mapped[bool] = mapped_column(Boolean, default=False)
    stop_reason: Mapped[str] = mapped_column(String(80), default="")
    followup_count: Mapped[int] = mapped_column(default=0)
    last_followup_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_followup_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    call_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    call_notes: Mapped[str] = mapped_column(String(500), default="")


class CampaignContent(Base):
    __tablename__ = "campaign_content"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    campaign: Mapped[Campaign] = relationship(back_populates="contents")
    channel: Mapped[str] = mapped_column(String(20))  # email|whatsapp|sms
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")

    # "plain" (default, free-typed text) or "template" (email-only: fixed
    # branded HTML shell filled from `template_fields`, see app/email_template.py).
    content_mode: Mapped[str] = mapped_column(String(20), default="plain")
    template_fields: Mapped[dict] = mapped_column(JSON, default=dict)

    # Which library `templates` row this content was copied from, if any (see
    # Template below). This is a snapshot, not a live pointer: once copied,
    # editing the source template never changes this row, and editing this
    # row never changes the source template. Kept only so reporting can
    # answer "which campaigns used template X" without a hand-maintained
    # back-reference.
    source_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("templates.id", ondelete="SET NULL"), nullable=True
    )



class CampaignSequenceStep(Base):
    """Multi-channel sequence step (email + WhatsApp + SMS).

    step_number 0 = first touch (usually mirrors campaign content);
    1..N = automatic follow-ups after `delay_days` at `send_time` (HH:MM UTC).
    Each step can enable any combination of channels with its own copy.
    """
    __tablename__ = "campaign_sequence_steps"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    campaign: Mapped[Campaign] = relationship(back_populates="sequence_steps")
    step_number: Mapped[int] = mapped_column(default=0)  # 0=initial, 1+=follow-up
    label: Mapped[str] = mapped_column(String(120), default="")
    delay_days: Mapped[int] = mapped_column(default=0)
    send_time: Mapped[str] = mapped_column(String(5), default="10:00")  # HH:MM (24h, UTC)

    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    email_subject: Mapped[str] = mapped_column(String(300), default="")
    email_body: Mapped[str] = mapped_column(Text, default="")

    whatsapp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    whatsapp_body: Mapped[str] = mapped_column(Text, default="")

    sms_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sms_body: Mapped[str] = mapped_column(Text, default="")

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Legacy single-channel fields (kept for older rows / migrations)
    channel: Mapped[str] = mapped_column(String(20), default="email")
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (
        Index("ix_sequence_step_campaign_num", "campaign_id", "step_number", unique=True),
    )


class CampaignAttachment(Base):
    """A file attached to a campaign's email content -- the same set is sent
    to every recipient (no per-recipient personalization). Stored on local
    disk under app/storage.py's UPLOAD_DIR, same as project logos/badges;
    `storage_path` is the filename within that directory, read back into
    memory at send time (see app/worker.py) to build the attachment payload
    passed into app/mailer.py::send_campaign_email."""
    __tablename__ = "campaign_attachments"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    campaign: Mapped[Campaign] = relationship(back_populates="attachments")
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    storage_path: Mapped[str] = mapped_column(String(300))
    size_bytes: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TemplateCategory(Base):
    __tablename__ = "template_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)


class Template(Base):
    """Workspace-wide reusable message template (shared across all projects --
    rendered with whichever project's branding is active at use-time). One
    row here is the umbrella metadata; the actual channel content lives in
    a 1:1 EmailTemplateContent/WhatsappTemplateContent row, or (for SMS) in
    the pre-existing SmsTemplate row via SmsTemplate.parent_template_id.

    `channel` is immutable after creation -- a different channel needs a
    different content shape, so users duplicate into a new template instead
    of converting one in place.
    """
    __tablename__ = "templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    channel: Mapped[str] = mapped_column(String(20))  # email|whatsapp|sms
    category_id: Mapped[int | None] = mapped_column(ForeignKey("template_categories.id"), nullable=True)
    category: Mapped[TemplateCategory | None] = relationship()
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|published|archived
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    email_content: Mapped["EmailTemplateContent"] = relationship(
        back_populates="template", uselist=False, cascade="all, delete-orphan"
    )
    whatsapp_content: Mapped["WhatsappTemplateContent"] = relationship(
        back_populates="template", uselist=False, cascade="all, delete-orphan"
    )


class EmailTemplateContent(Base):
    """1:1 with a Template where channel == 'email'. Same structured-field
    shape as CampaignContent.template_fields (see schemas.TemplateFields) --
    rendered through the same fixed branded shell in app/email_template.py,
    not a free-form HTML editor (that path was deliberately closed off, see
    HTML_TAG_RE in routers/campaigns.py)."""
    __tablename__ = "email_template_content"
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id", ondelete="CASCADE"), primary_key=True)
    template: Mapped[Template] = relationship(back_populates="email_content")
    subject: Mapped[str] = mapped_column(String(300), default="")
    fields: Mapped[dict] = mapped_column(JSON, default=dict)  # TemplateFields shape
    branding_override: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class WhatsappTemplateContent(Base):
    """1:1 with a Template where channel == 'whatsapp'. Catalogs a template
    already approved in WhatsApp Business Manager -- this app does not
    author/approve WhatsApp templates itself, so these fields mirror Meta's
    HSM structure rather than offering free-form authoring."""
    __tablename__ = "whatsapp_template_content"
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id", ondelete="CASCADE"), primary_key=True)
    template: Mapped[Template] = relationship(back_populates="whatsapp_content")
    meta_template_name: Mapped[str] = mapped_column(String(160))
    meta_template_id: Mapped[str] = mapped_column(String(120))
    language_code: Mapped[str] = mapped_column(String(20))
    header_type: Mapped[str] = mapped_column(String(20), default="none")  # none|text|image|document
    header_content: Mapped[str] = mapped_column(String(300), default="")
    body_text: Mapped[str] = mapped_column(Text)
    footer_text: Mapped[str] = mapped_column(String(160), default="")
    buttons: Mapped[list] = mapped_column(JSON, default=list)


class SmsTemplate(Base):
    __tablename__ = "sms_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    template_id: Mapped[str] = mapped_column(String(60))   # DLT template id registered with the operator
    sender_id: Mapped[str] = mapped_column(String(20), default="")  # DLT sender / header
    body: Mapped[str] = mapped_column(Text)               # exact registered text, variables as {#var#} or {{var}}
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Library umbrella row for this SMS template (see Template above). Nullable
    # so pre-existing rows created before this module shipped keep working
    # unchanged -- a backfill migration links them to a generated Template row.
    parent_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("templates.id", ondelete="SET NULL"), nullable=True
    )


class Suppression(Base):
    __tablename__ = "suppression_list"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    contact: Mapped[str] = mapped_column(String(200), index=True)
    channel: Mapped[str] = mapped_column(String(20))  # email|whatsapp|sms
    reason: Mapped[str] = mapped_column(String(40), default="manual")  # unsubscribed|bounced|manual
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_suppression_lookup", "project_id", "contact", "channel"),
    )


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    campaign: Mapped[Campaign] = relationship(back_populates="messages")
    recipient_id: Mapped[int] = mapped_column(ForeignKey("recipients.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(20))
    to_address: Mapped[str] = mapped_column(String(200), default="")
    recipient_name: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending|queued|processing|sent|delivered|read|failed|suppressed
    provider_id: Mapped[str] = mapped_column(String(120), default="")
    error: Mapped[str] = mapped_column(String(300), default="")
    # Non-fatal: names of placeholders that had no matching value at send time
    # (message still sent, with those placeholders blanked rather than left broken).
    warnings: Mapped[str] = mapped_column(String(300), default="")
    is_followup: Mapped[bool] = mapped_column(Boolean, default=False)
    followup_number: Mapped[int] = mapped_column(default=0)
    sequence_step: Mapped[str] = mapped_column(String(40), default="initial")  # initial|followup|reminder
    sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    read_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
