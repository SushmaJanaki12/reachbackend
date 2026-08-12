import secrets
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


class PasswordResetToken(Base):
    """Self-service forgot/reset-password flow (P1.7). A row is single-use --
    `used_at` gets set at redemption and the row is never revived -- and
    short-lived (see Settings.password_reset_token_ttl_minutes), unlike the
    long-lived access token issued at login."""
    __tablename__ = "password_reset_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    logo_url: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|inactive|archived

    # Branding used by the message template library's Email content (see
    # app/email_template.py) -- CompanyName/CompanyLogoUrl come from `name` /
    # `logo_url` above, not duplicated here.
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

    # IANA timezone name used for follow-up send-time/weekend-skip math.
    # There's no per-recipient timezone anywhere in the data model (not even
    # in the CSV import), so this one project-level value stands in for
    # "the recipient's local timezone" for every recipient in the project.
    timezone: Mapped[str] = mapped_column(String(60), default="UTC")


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


class ReplyCaptureSettings(Base):
    """Workspace-wide config for real inbound-reply capture (P1.3, see
    app/reply_capture.py): one IMAP mailbox this app polls, shared across
    every project/campaign regardless of which tier (project SMTP, admin
    SMTP, or O365/Graph) actually sent the original message -- there's no
    provider-agnostic inbound-parse webhook available, so polling one
    mailbox is the only mechanism that covers all of them uniformly.

    A single row is expected (id=1 in practice, not DB-enforced -- the
    router always upserts/reads the first row, same "there's realistically
    only one" shape as this being workspace-wide rather than per-project).
    """
    __tablename__ = "reply_capture_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Base address replies are routed to, e.g. "replies@reach-tracking.com".
    # Outbound campaign emails get Reply-To set to "local+{token}@domain" --
    # the +token subaddress is how an inbound reply gets matched back to the
    # Message it was a reply to (see app/reply_capture.py::reply_to_alias).
    mailbox_address: Mapped[str] = mapped_column(String(200), default="")
    imap_host: Mapped[str] = mapped_column(String(200), default="")
    imap_port: Mapped[int] = mapped_column(default=993)
    imap_use_ssl: Mapped[bool] = mapped_column(Boolean, default=True)
    imap_username: Mapped[str] = mapped_column(String(200), default="")
    imap_password: Mapped[str] = mapped_column(String(500), default="")  # encrypted at rest, see app/crypto.py
    poll_folder: Mapped[str] = mapped_column(String(120), default="INBOX")
    poll_interval_seconds: Mapped[int] = mapped_column(default=120)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_poll_status: Mapped[str] = mapped_column(String(20), default="never")  # ok|failed|never
    last_poll_error: Mapped[str] = mapped_column(String(300), default="")
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

    # Set only at creation (not exposed on CampaignUpdate) -- flipping it
    # later would either unlock Simulate against a campaign that already has
    # real recipients, or silently reclassify a test campaign's fabricated
    # engagement data as real. Gates followups.simulate_event (see
    # routers/followups.py) and excludes the campaign from dashboard rollups.
    is_test_campaign: Mapped[bool] = mapped_column(Boolean, default=False)

    # Optional link to a registered DLT SMS template (for compliant SMS)
    sms_template_ref: Mapped[int | None] = mapped_column(ForeignKey("sms_templates.id"), nullable=True)

    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Set when status flips to "sending" (send_campaign), left alone after --
    # the stuck-campaign safeguard (GET /api/admin/queue-status) uses it as
    # the floor for "how long has this campaign been sending" before any
    # Message row exists yet to measure activity from instead.
    sending_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Which "send" the live Message rows currently belong to (P0.5, revised
    # 2026-08-11: resend is allowed repeatedly rather than blocked after the
    # first send). Bumped by app/campaign_resend.py::archive_campaign_history
    # each time a resend archives the prior run's Message/FollowUpRun rows
    # into MessageHistory/FollowUpRunHistory and clears the live tables --
    # every Message this campaign creates from then on (original blast and
    # follow-up steps alike) is stamped with this value.
    current_send_run: Mapped[int] = mapped_column(default=1)

    recipients: Mapped[list["Recipient"]] = relationship(back_populates="campaign", cascade="all, delete-orphan",
                                                          order_by="Recipient.id")
    contents: Mapped[list["CampaignContent"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")
    messages: Mapped[list["Message"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")
    attachments: Mapped[list["CampaignAttachment"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")
    followup_steps: Mapped[list["FollowUpStep"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan", order_by="FollowUpStep.step_order")
    followup_settings: Mapped["CampaignFollowUpSettings"] = relationship(
        back_populates="campaign", uselist=False, cascade="all, delete-orphan")
    followup_runs: Mapped[list["FollowUpRun"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")


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
    # Tags which validated-import batch this row came from (see
    # DatasetValidationSession below) -- lets a bad import be undone by
    # batch without touching recipients from other uploads.
    batch_import_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)


class DatasetValidationSession(Base):
    """Staging area for the AI Smart Data Validation flow: a file is parsed
    and validated into here first, and only copied into `Recipient` rows on
    an explicit /import call. `raw_rows` is the untouched parse of the
    uploaded file (kept for the error report's original row numbers);
    `working_rows` is the copy that accepted AI-suggested fixes get applied
    to, per the suggest-and-confirm flow (never auto-applied)."""
    __tablename__ = "dataset_validation_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    campaign: Mapped[Campaign] = relationship()
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    original_filename: Mapped[str] = mapped_column(String(255), default="")

    column_mapping: Mapped[dict] = mapped_column(JSON, default=dict)  # {source_header: target_field}
    mapping_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)

    raw_rows: Mapped[list] = mapped_column(JSON, default=list)
    working_rows: Mapped[list] = mapped_column(JSON, default=list)
    issues: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    quality_score: Mapped[dict] = mapped_column(JSON, default=dict)

    status: Mapped[str] = mapped_column(String(20), default="active")  # active|imported|cancelled
    batch_import_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ValidationOverrideLog(Base):
    """Audit trail for the admin-only 'Ignore Warnings' import action (PRD
    Sec. 11.1) -- who force-imported warning-flagged rows, when, how many,
    and which warning types were bypassed."""
    __tablename__ = "validation_override_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("dataset_validation_sessions.id", ondelete="SET NULL"), nullable=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    warning_row_count: Mapped[int] = mapped_column(default=0)
    warning_types: Mapped[list] = mapped_column(JSON, default=list)


class CampaignContent(Base):
    __tablename__ = "campaign_content"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    campaign: Mapped[Campaign] = relationship(back_populates="contents")
    channel: Mapped[str] = mapped_column(String(20))  # email|whatsapp|sms
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")


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
    rendered with whichever project's branding is active at preview-time).
    One row here is the umbrella metadata; the actual channel content lives in
    a 1:1 EmailTemplateContent/WhatsappTemplateContent row. SMS templates are
    managed separately as `SmsTemplate` rows (DLT registration has no
    "draft/published" concept and no per-project branding), surfaced
    alongside these in the Templates page but not stored in this table.

    `channel` is immutable after creation -- a different channel needs a
    different content shape, so users duplicate into a new template instead
    of converting one in place.
    """
    __tablename__ = "templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    channel: Mapped[str] = mapped_column(String(20))  # email|whatsapp
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
    attachments: Mapped[list["TemplateAttachment"]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )


class EmailTemplateContent(Base):
    """1:1 with a Template where channel == 'email'. Same structured-field
    shape as schemas.TemplateFields -- rendered through the fixed branded
    shell in app/email_template.py, not a free-form HTML editor."""
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


class TemplateAttachment(Base):
    """A file attached to an Email template -- shown to anyone using the
    template as a suggested/standard attachment. Same local-disk storage as
    CampaignAttachment (see app/storage.py)."""
    __tablename__ = "template_attachments"
    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id", ondelete="CASCADE"), index=True)
    template: Mapped[Template] = relationship(back_populates="attachments")
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    storage_path: Mapped[str] = mapped_column(String(300))
    size_bytes: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SmsTemplate(Base):
    __tablename__ = "sms_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    template_id: Mapped[str] = mapped_column(String(60))   # DLT template id registered with the operator
    sender_id: Mapped[str] = mapped_column(String(20), default="")  # DLT sender / header
    body: Mapped[str] = mapped_column(Text)               # exact registered text, variables as {#var#} or {{var}}
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


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
    sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    read_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    # Unguessable per-message id for the tracking pixel / click-redirect URLs
    # (app/routers/tracking_pixel.py) -- deliberately not the raw integer PK,
    # which would let anyone increment through it and mark other recipients'
    # messages "opened". Generated once at row creation, never reused.
    tracking_token: Mapped[str] = mapped_column(String(48), unique=True, index=True,
                                                 default=lambda: secrets.token_urlsafe(24))
    # Which send this row belongs to -- see Campaign.current_send_run. Set at
    # creation time (send_campaign for the original blast, advance_followup_run
    # for a follow-up step's send) from the owning campaign's current value;
    # never changed afterward. A resend archives every row sharing the old
    # value into MessageHistory before the live table is cleared for the next one.
    sent_run_number: Mapped[int] = mapped_column(default=1)
    # Bumped on every column write (status, error, engagement fields, ...) --
    # the stuck-campaign safeguard (GET /api/admin/queue-status) uses the
    # most recent value across a campaign's messages as its "still making
    # progress" signal, since there's no per-row send-attempt log to read
    # activity from otherwise.
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Follow-ups: NULL means this Message is the original campaign blast;
    # otherwise it's the send for this particular FollowUpStep in the
    # recipient's sequence (see app/followups.py).
    step_id: Mapped[int | None] = mapped_column(ForeignKey("follow_up_steps.id", ondelete="SET NULL"),
                                                  nullable=True, index=True)
    # Engagement state -- populated either by real tracking capture (not yet
    # built) or, for now, via the "simulate event" testing endpoint. Trigger
    # evaluation in app/followups.py reads these directly.
    opened_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    clicked_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    replied_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    reply_text: Mapped[str] = mapped_column(Text, default="")
    reply_sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # interested|not_interested|unclear -- see app/reply_classifier.py
    engagement_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 'simulated' when opened_at/clicked_at/replied_at were written by the
    # Simulate testing endpoint (app/followups.py::record_engagement_event)
    # rather than real capture; null otherwise. Follow-up step performance
    # stats (routers/followups.py::_step_stats) exclude simulated rows so
    # QA/demo activity on a test campaign never leaks into real metrics.


class FollowUpStep(Base):
    """One step in a campaign's automated follow-up sequence. Steps run in
    `step_order`; each has its own trigger condition + delay (see
    app/followups.py::advance_followup_run) rather than firing on a blind
    timer."""
    __tablename__ = "follow_up_steps"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    campaign: Mapped[Campaign] = relationship(back_populates="followup_steps")
    step_order: Mapped[int] = mapped_column()

    trigger_type: Mapped[str] = mapped_column(String(20))  # no_reply|not_opened|not_clicked
    delay_value: Mapped[int] = mapped_column()
    delay_unit: Mapped[str] = mapped_column(String(10), default="days")  # hours|days
    send_time: Mapped[str | None] = mapped_column(String(5), nullable=True)  # "HH:MM" local, falls back to
    # CampaignFollowUpSettings.default_send_time when unset

    primary_channel: Mapped[str] = mapped_column(String(20), default="email")
    fallback_channel: Mapped[str | None] = mapped_column(String(20), nullable=True)

    subject: Mapped[str] = mapped_column(String(300), default="")
    body_template: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_followup_step_order", "campaign_id", "step_order", unique=True),
    )


class CampaignFollowUpSettings(Base):
    """1:1 campaign-level knobs for the follow-up engine. No separate
    "enabled" flag -- the engine is live whenever the campaign has at least
    one FollowUpStep, mirroring the reference mockup (which has no such
    toggle)."""
    __tablename__ = "campaign_follow_up_settings"
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True)
    campaign: Mapped[Campaign] = relationship(back_populates="followup_settings")

    max_touches_per_week: Mapped[int] = mapped_column(default=3)
    skip_weekends: Mapped[bool] = mapped_column(Boolean, default=True)
    negative_reply_handling: Mapped[str] = mapped_column(String(20), default="tag_and_stop")  # stop_only|tag_and_stop
    default_send_time: Mapped[str | None] = mapped_column(String(5), nullable=True)  # "HH:MM" local
    # P0.5 (revised 2026-08-11): a resend archives the prior send's
    # FollowUpRun rows rather than leaving them live -- this decides whether
    # a fresh run then starts immediately for recipients who already had one
    # (True) or stays off until manually restarted, e.g. via a new step edit
    # (False, default -- the spec's stated "safest default" pending a
    # separate product decision on restart semantics; see
    # app/followups.py::maybe_start_run).
    restart_on_resend: Mapped[bool] = mapped_column(Boolean, default=False)


class FollowUpRun(Base):
    """Tracks one recipient's live position in a campaign's follow-up
    sequence. Re-evaluated by app/followups.py::advance_followup_run both on
    its scheduled RQ timer (`scheduled_job_id`) and immediately whenever an
    engagement event lands on `last_message`, so an early-satisfied trigger
    doesn't have to wait out a stale timer."""
    __tablename__ = "follow_up_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    campaign: Mapped[Campaign] = relationship(back_populates="followup_runs")
    recipient_id: Mapped[int] = mapped_column(ForeignKey("recipients.id", ondelete="CASCADE"), index=True)

    status: Mapped[str] = mapped_column(String(24), default="active")
    # active|stopped_interested|stopped_not_interested|completed
    next_step_order: Mapped[int | None] = mapped_column(nullable=True)
    scheduled_job_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    last_message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    last_message: Mapped["Message"] = relationship(foreign_keys=[last_message_id])

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_followup_run_recipient", "campaign_id", "recipient_id", unique=True),
    )


class MessageHistory(Base):
    """Snapshot of a Message row as it stood right before a resend cleared it
    from the live `messages` table (P0.5, revised 2026-08-11: resend now
    archives-and-clears rather than being blocked -- see
    app/campaign_resend.py::archive_campaign_history, called from
    routers/campaigns.py::send_campaign). One row per archived Message,
    tagged with the run it belonged to so Tracking & Reports and Follow-ups
    Performance can be scoped to a specific past send instead of blending
    runs together.

    `recipient_id`/`step_id` are deliberately plain columns, not foreign
    keys -- the Recipient or FollowUpStep a historical row pointed to may
    since have been deleted (dataset re-import, step edit) without that
    invalidating the archived snapshot, which already carries its own copy
    of recipient_name/to_address/etc.
    """
    __tablename__ = "message_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    sent_run_number: Mapped[int] = mapped_column(index=True)
    recipient_id: Mapped[int] = mapped_column(index=True)
    channel: Mapped[str] = mapped_column(String(20))
    to_address: Mapped[str] = mapped_column(String(200), default="")
    recipient_name: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    provider_id: Mapped[str] = mapped_column(String(120), default="")
    error: Mapped[str] = mapped_column(String(300), default="")
    warnings: Mapped[str] = mapped_column(String(300), default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    tracking_token: Mapped[str] = mapped_column(String(48), index=True)
    step_id: Mapped[int | None] = mapped_column(nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reply_text: Mapped[str] = mapped_column(Text, default="")
    reply_sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    engagement_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    archived_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_message_history_campaign_run", "campaign_id", "sent_run_number"),
    )


class FollowUpRunHistory(Base):
    """Snapshot of a FollowUpRun row archived alongside its MessageHistory
    rows on resend (see MessageHistory above) -- keeps the resend from
    silently discarding where each recipient's follow-up sequence had gotten
    to. Not surfaced in any UI yet; exists so that data isn't simply lost."""
    __tablename__ = "follow_up_run_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    sent_run_number: Mapped[int] = mapped_column(index=True)
    recipient_id: Mapped[int] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(24))
    next_step_order: Mapped[int | None] = mapped_column(nullable=True)
    archived_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
