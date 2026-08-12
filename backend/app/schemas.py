from datetime import datetime
from typing import Literal
from pydantic import BaseModel, EmailStr, ConfigDict


# ---------- auth ----------
class LoginIn(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- forgot / reset password (P1.7) ----------
class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str


# ---------- permissions / roles ----------
class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    module: str
    label: str


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str
    is_system: bool
    permissions: list[PermissionOut] = []


class RoleIn(BaseModel):
    name: str
    description: str = ""
    permission_codes: list[str] = []


# ---------- users ----------
class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: EmailStr
    is_active: bool
    role: RoleOut
    created_at: datetime | None = None


class MeOut(UserOut):
    permissions: list[str] = []
    project_ids: list[int] = []


class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    role_id: int
    project_ids: list[int] = []


class UserUpdate(BaseModel):
    name: str | None = None
    role_id: int | None = None
    is_active: bool | None = None
    password: str | None = None
    project_ids: list[int] | None = None


# ---------- projects ----------
class ProjectBase(BaseModel):
    name: str
    email: EmailStr
    description: str = ""
    notes: str = ""
    status: str = "active"
    sms_active: bool = False
    sms_provider: str = ""
    whatsapp_active: bool = False
    whatsapp_provider: str = ""
    smtp_enabled: bool = False
    smtp_provider: Literal["gmail", "outlook", "zoho", "custom"] = "custom"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_encryption: Literal["none", "starttls", "ssl"] = "starttls"
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_name: str = ""
    smtp_from_email: str = ""
    smtp_reply_to: str = ""
    smtp_fallback_on_failure: bool = False
    smtp_max_per_minute: int = 0
    company_website: str = ""
    company_address: str = ""
    sender_name: str = ""
    sender_designation: str = ""
    sender_phone: str = ""
    badge1_url: str = ""
    badge2_url: str = ""
    badge3_url: str = ""


class ProjectCreate(ProjectBase):
    member_ids: list[int] = []


class ProjectUpdate(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    description: str | None = None
    notes: str | None = None
    status: str | None = None
    sms_active: bool | None = None
    sms_provider: str | None = None
    whatsapp_active: bool | None = None
    whatsapp_provider: str | None = None
    smtp_enabled: bool | None = None
    smtp_provider: Literal["gmail", "outlook", "zoho", "custom"] | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_encryption: Literal["none", "starttls", "ssl"] | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_name: str | None = None
    smtp_from_email: str | None = None
    smtp_reply_to: str | None = None
    smtp_fallback_on_failure: bool | None = None
    smtp_max_per_minute: int | None = None
    company_website: str | None = None
    company_address: str | None = None
    sender_name: str | None = None
    sender_designation: str | None = None
    sender_phone: str | None = None
    badge1_url: str | None = None
    badge2_url: str | None = None
    badge3_url: str | None = None
    member_ids: list[int] | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str
    description: str
    notes: str
    logo_url: str
    status: str
    sms_active: bool
    sms_provider: str
    whatsapp_active: bool
    whatsapp_provider: str
    smtp_enabled: bool = False
    smtp_provider: str = "custom"
    smtp_host: str
    smtp_port: int
    smtp_encryption: str = "starttls"
    smtp_username: str
    smtp_from_name: str = ""
    smtp_from_email: str = ""
    smtp_reply_to: str = ""
    smtp_fallback_on_failure: bool = False
    smtp_max_per_minute: int = 0
    smtp_last_tested_at: datetime | None = None
    smtp_last_test_status: str = "never"
    company_website: str = ""
    company_address: str = ""
    sender_name: str = ""
    sender_designation: str = ""
    sender_phone: str = ""
    badge1_url: str = ""
    badge2_url: str = ""
    badge3_url: str = ""
    created_at: datetime | None = None
    campaign_count: int = 0


# ---------- admin SMTP settings (workspace-default sender, Part 2) ----------
class SmtpSettingsBase(BaseModel):
    provider: Literal["gmail", "outlook", "zoho", "custom"] = "custom"
    smtp_host: str
    smtp_port: int = 587
    encryption: Literal["none", "starttls", "ssl"] = "starttls"
    username: str = ""
    password: str = ""
    from_email: EmailStr
    from_name: str = ""
    reply_to: str = ""
    max_per_minute: int = 0


class SmtpSettingsCreate(SmtpSettingsBase):
    pass


class SmtpSettingsUpdate(BaseModel):
    provider: Literal["gmail", "outlook", "zoho", "custom"] | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    encryption: Literal["none", "starttls", "ssl"] | None = None
    username: str | None = None
    password: str | None = None
    from_email: EmailStr | None = None
    from_name: str | None = None
    reply_to: str | None = None
    max_per_minute: int | None = None


class SmtpSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    provider: str
    smtp_host: str
    smtp_port: int
    encryption: str
    username: str
    has_password: bool = False  # password itself is never returned, in any form
    from_email: str
    from_name: str
    reply_to: str
    max_per_minute: int
    is_active: bool
    last_tested_at: datetime | None = None
    last_test_status: str = "never"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SendTestEmailIn(BaseModel):
    to: EmailStr


# ---------- reply capture (P1.3) ----------
class ReplyCaptureSettingsUpdate(BaseModel):
    enabled: bool | None = None
    mailbox_address: str | None = None
    imap_host: str | None = None
    imap_port: int | None = None
    imap_use_ssl: bool | None = None
    imap_username: str | None = None
    imap_password: str | None = None
    poll_folder: str | None = None
    poll_interval_seconds: int | None = None


class ReplyCaptureSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    enabled: bool
    mailbox_address: str
    imap_host: str
    imap_port: int
    imap_use_ssl: bool
    imap_username: str
    has_password: bool = False  # imap_password itself is never returned
    poll_folder: str
    poll_interval_seconds: int
    last_polled_at: datetime | None = None
    last_poll_status: str = "never"
    last_poll_error: str = ""
    updated_at: datetime | None = None


# ---------- campaigns ----------
class CampaignCreate(BaseModel):
    project_id: int
    name: str
    description: str = ""
    # Immutable after creation -- see Campaign.is_test_campaign in models.py.
    is_test_campaign: bool = False


class CampaignUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    email_enabled: bool | None = None
    whatsapp_enabled: bool | None = None
    sms_enabled: bool | None = None
    sms_template_ref: int | None = None


class ContentIn(BaseModel):
    subject: str = ""
    body: str = ""


class ContentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    channel: str
    subject: str
    body: str


class ContentGenerateIn(BaseModel):
    prompt: str


class ContentGenerateOut(BaseModel):
    subject: str = ""
    body: str = ""


class RecipientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str
    mobile: str
    data: dict
    active: bool


class RecipientIn(BaseModel):
    name: str
    email: str = ""
    mobile: str = ""


class RecipientActiveIn(BaseModel):
    active: bool


class CampaignAttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime | None = None


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    name: str
    description: str
    status: str
    email_enabled: bool
    whatsapp_enabled: bool
    sms_enabled: bool
    sms_template_ref: int | None = None
    is_test_campaign: bool = False
    created_at: datetime | None = None
    recipient_count: int = 0
    columns: list[str] = []
    project_name: str = ""
    last_import_batch_id: str | None = None


# ---------- message templates (library) ----------
class BulletIn(BaseModel):
    label: str = ""
    text: str = ""


class TemplateFields(BaseModel):
    """Structured content for an Email template -- see app/email_template.py.
    Never contains raw HTML, only plain field values."""
    headline: str = ""
    opening_line: str = ""
    show_bullets: bool = False
    campaign_name: str = ""
    bullets: list[BulletIn] = []
    show_callout: bool = False
    callout_label: str = ""
    callout_text: str = ""
    show_cta: bool = False
    action_url: str = ""
    action_label: str = ""
    show_badges: bool = False
    show_secondary: bool = False
    secondary_action_url: str = ""
    secondary_action_label: str = ""


class TemplateCategoryIn(BaseModel):
    name: str


class TemplateCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class EmailTemplateContentIn(BaseModel):
    subject: str = ""
    fields: TemplateFields = TemplateFields()
    branding_override: dict | None = None


class EmailTemplateContentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    subject: str
    fields: dict
    branding_override: dict | None = None


class WhatsappTemplateContentIn(BaseModel):
    meta_template_name: str
    meta_template_id: str
    language_code: str
    header_type: str = "none"  # none|text|image|document
    header_content: str = ""
    body_text: str
    footer_text: str = ""
    buttons: list = []


class WhatsappTemplateContentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    meta_template_name: str
    meta_template_id: str
    language_code: str
    header_type: str
    header_content: str
    body_text: str
    footer_text: str
    buttons: list


class TemplateAttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime | None = None


class TemplateCreate(BaseModel):
    name: str
    description: str = ""
    channel: str  # email|whatsapp -- immutable after creation
    category_id: int | None = None
    email_content: EmailTemplateContentIn | None = None
    whatsapp_content: WhatsappTemplateContentIn | None = None


class TemplateUpdate(BaseModel):
    """Channel is deliberately not editable here -- duplicate into a new
    template instead of converting one in place."""
    name: str | None = None
    description: str | None = None
    category_id: int | None = None
    status: str | None = None  # draft|published|archived
    email_content: EmailTemplateContentIn | None = None
    whatsapp_content: WhatsappTemplateContentIn | None = None


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str
    channel: str
    category: TemplateCategoryOut | None = None
    status: str
    created_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    email_content: EmailTemplateContentOut | None = None
    whatsapp_content: WhatsappTemplateContentOut | None = None
    attachments: list[TemplateAttachmentOut] = []


class TemplateLibraryPreviewIn(BaseModel):
    recipient_id: int | None = None


class TemplatePreviewOut(BaseModel):
    html: str
    missing: list[str] = []


# ---------- SMS templates (DLT) ----------
class SmsTemplateIn(BaseModel):
    name: str
    template_id: str
    sender_id: str = ""
    body: str
    is_active: bool = True


class SmsTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    template_id: str
    sender_id: str
    body: str
    is_active: bool
    created_at: datetime | None = None


class SmsValidateIn(BaseModel):
    template_ref: int
    message: str


class SmsValidateOut(BaseModel):
    valid: bool
    reason: str = ""


class PreviewIn(BaseModel):
    channel: str
    subject: str = ""
    body: str = ""
    recipient_id: int | None = None


class PreviewOut(BaseModel):
    subject: str
    body: str
    missing: list[str] = []


# ---------- suppression list ----------
class SuppressionIn(BaseModel):
    contact: str
    channel: str
    reason: str = "manual"


class SuppressionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    contact: str
    channel: str
    reason: str
    created_at: datetime | None = None


# ---------- tracking ----------
class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    channel: str
    recipient_name: str
    to_address: str
    status: str
    error: str
    warnings: str = ""
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    read_at: datetime | None = None
    step_id: int | None = None
    opened_at: datetime | None = None
    clicked_at: datetime | None = None
    replied_at: datetime | None = None
    reply_sentiment: str | None = None
    engagement_source: str | None = None


class SummaryOut(BaseModel):
    total_recipients: int
    total_messages: int
    email_sent: int
    whatsapp_sent: int
    sms_sent: int
    delivered: int
    failed: int
    pending: int
    suppressed: int
    status: str


class SendRunOut(BaseModel):
    # One entry per distinct send of a campaign (P0.5: resend archives the
    # prior run rather than overwriting it) -- backs the run selector on
    # Tracking & Reports (?run= on /tracking/{channel} and /summary).
    run_number: int
    is_current: bool
    message_count: int
    first_sent_at: datetime | None = None


# ---------- follow-ups ----------
class FollowUpStepStats(BaseModel):
    sent: int = 0
    open_rate: float | None = None
    click_rate: float | None = None
    reply_rate: float | None = None


class FollowUpStepIn(BaseModel):
    trigger_type: Literal["no_reply", "not_opened", "not_clicked"] = "no_reply"
    delay_value: int = 3
    delay_unit: Literal["hours", "days"] = "days"
    send_time: str | None = None
    primary_channel: Literal["email", "whatsapp", "sms"] = "email"
    fallback_channel: Literal["email", "whatsapp", "sms"] | None = None
    subject: str = ""
    body_template: str = ""


class FollowUpStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    campaign_id: int
    step_order: int
    trigger_type: str
    delay_value: int
    delay_unit: str
    send_time: str | None = None
    primary_channel: str
    fallback_channel: str | None = None
    subject: str
    body_template: str
    stats: FollowUpStepStats = FollowUpStepStats()


class CampaignFollowUpSettingsIn(BaseModel):
    max_touches_per_week: int = 3
    skip_weekends: bool = True
    negative_reply_handling: Literal["stop_only", "tag_and_stop"] = "tag_and_stop"
    default_send_time: str | None = None
    restart_on_resend: bool = False


class CampaignFollowUpSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    campaign_id: int
    max_touches_per_week: int
    skip_weekends: bool
    negative_reply_handling: str
    default_send_time: str | None = None
    restart_on_resend: bool = False


class SimulateEventIn(BaseModel):
    event: Literal["opened", "clicked", "replied"]
    reply_text: str | None = None


class FollowUpStepMoveIn(BaseModel):
    direction: Literal["up", "down"]


# ---------- dataset validation (AI Smart Data Validation) ----------
class ValidationIssueOut(BaseModel):
    row_number: int
    field: str | None
    severity: str
    issue_type: str
    description: str
    suggested_fix: str | None
    fix_id: str


class QualityScoreOut(BaseModel):
    overall: int
    label: str
    breakdown: dict[str, int]


class ValidationSummaryOut(BaseModel):
    total_rows: int
    empty_rows_skipped: int
    valid_rows: int
    invalid_rows: int
    warning_rows: int
    duplicate_rows: int
    ready_for_import: int
    ready_for_import_with_overrides: int


class ColumnMappingSuggestion(BaseModel):
    header: str
    target_field: str | None
    sample_values: list[str] = []


class ValidationSessionOut(BaseModel):
    id: int
    campaign_id: int
    original_filename: str
    status: str
    mapping_confirmed: bool
    column_mapping: dict[str, str | None]
    mapping_suggestions: list[ColumnMappingSuggestion] = []
    target_fields: list[str] = []
    mandatory_targets: list[str] = []
    issues: list[ValidationIssueOut]
    summary: ValidationSummaryOut
    quality_score: QualityScoreOut
    encoding_warning: bool = False


class ColumnMappingIn(BaseModel):
    column_mapping: dict[str, str | None]


class ApplyFixesIn(BaseModel):
    fix_ids: list[str] = []
    accept_all: bool = False


class DatasetImportIn(BaseModel):
    mode: Literal["valid_only", "ignore_warnings"] = "valid_only"
