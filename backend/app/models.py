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

    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    recipients: Mapped[list["Recipient"]] = relationship(back_populates="campaign", cascade="all, delete-orphan",
                                                          order_by="Recipient.id")
    contents: Mapped[list["CampaignContent"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")
    messages: Mapped[list["Message"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")
    attachments: Mapped[list["CampaignAttachment"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")


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
