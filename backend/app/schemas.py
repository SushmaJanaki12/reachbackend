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


# ---------- admin SMTP settings ----------
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
    has_password: bool = False
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


# ---------- campaigns ----------
class CampaignCreate(BaseModel):
    project_id: int
    name: str
    description: str = ""


class CampaignUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    email_enabled: bool | None = None
    whatsapp_enabled: bool | None = None
    sms_enabled: bool | None = None
    sms_template_ref: int | None = None
    followup_enabled: bool | None = None
    followup_interval_days: int | None = None
    max_followups: int | None = None
    ai_goal: str | None = None
    ai_tone: str | None = None


class BulletIn(BaseModel):
    label: str = ""
    text: str = ""


class TemplateFields(BaseModel):
    """Structured content for email.content_mode == 'template'."""
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


class ContentIn(BaseModel):
    subject: str = ""
    body: str = ""
    content_mode: str = "plain"
    template_fields: TemplateFields = TemplateFields()


class ContentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    channel: str
    subject: str
    body: str
    content_mode: str = "plain"
    template_fields: TemplateFields = TemplateFields()


class TemplatePreviewIn(BaseModel):
    fields: TemplateFields
    recipient_id: int | None = None


class TemplatePreviewOut(BaseModel):
    html: str
    missing: list[str] = []


class RecipientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str
    mobile: str
    data: dict
    active: bool
    reply_status: str = "not_replied"
    interest_status: str = "none"
    campaign_stopped: bool = False
    stop_reason: str = ""
    followup_count: int = 0
    last_followup_at: datetime | None = None
    next_followup_at: datetime | None = None
    call_scheduled_at: datetime | None = None
    call_notes: str = ""


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
    followup_enabled: bool = True
    followup_interval_days: int = 3
    max_followups: int = 3
    ai_goal: str = ""
    ai_tone: str = "professional"
    warmup_enabled: bool = False
    warmup_daily_cap: int = 50
    warmup_started_at: datetime | None = None
    created_at: datetime | None = None
    recipient_count: int = 0
    columns: list[str] = []
    project_name: str = ""


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


# ---------- message templates (library) ----------
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
    header_type: str = "none"
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


class TemplateCreate(BaseModel):
    name: str
    description: str = ""
    channel: str
    category_id: int | None = None
    email_content: EmailTemplateContentIn | None = None
    whatsapp_content: WhatsappTemplateContentIn | None = None


class TemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category_id: int | None = None
    status: str | None = None
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


class TemplateLibraryPreviewIn(BaseModel):
    recipient_id: int | None = None


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
    recipient_id: int | None = None
    is_followup: bool = False
    followup_number: int = 0
    sequence_step: str = "initial"
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    read_at: datetime | None = None


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
    # Engagement / pipeline (production reports)
    replied: int = 0
    not_replied: int = 0
    interested: int = 0
    not_interested: int = 0
    stopped: int = 0
    queued: int = 0
    processing: int = 0
    total_sent: int = 0
    reply_rate_pct: float = 0.0
    send_rate_pct: float = 0.0
    fail_rate_pct: float = 0.0


# ---------- campaign AI review ----------
class ChannelReviewOut(BaseModel):
    score: int = 0
    feedback: list[str] = []


class EstimatedMetricsOut(BaseModel):
    open_rate: str = ""
    click_rate: str = ""
    reply_rate: str = ""


class SpamRiskOut(BaseModel):
    level: str = "low"  # low|medium|high
    reasons: list[str] = []


class CampaignReviewOut(BaseModel):
    campaign_score: int
    grade: str
    summary: str
    estimated_metrics: EstimatedMetricsOut
    strengths: list[str] = []
    issues: list[str] = []
    recommendations: list[str] = []
    channel_reviews: dict[str, ChannelReviewOut]
    spam_risk: SpamRiskOut
    cta_review: str = ""
    personalization_review: str = ""
    grammar_review: str = ""
    consistency_review: str = ""
    final_recommendation: str = ""
    review_source: str = "rules"  # openai | rules
    inbox_tips: list[str] = []


class CampaignReviewPreviewIn(BaseModel):
    """Review content that may not be saved on a campaign yet."""
    name: str = ""
    description: str = ""
    email_enabled: bool = True
    whatsapp_enabled: bool = False
    sms_enabled: bool = False
    email_subject: str = ""
    email_body: str = ""
    email_content_mode: str = "plain"
    email_template_fields: TemplateFields = TemplateFields()
    whatsapp_body: str = ""
    sms_body: str = ""


# ---------- AI Smart Data Validation ----------
class ValidationIssueOut(BaseModel):
    type: str
    field: str = ""
    severity: str = "error"  # error|warning
    description: str = ""
    suggested_fix: str = ""


class ValidationRowOut(BaseModel):
    row_number: int
    name: str = ""
    email: str = ""
    mobile: str = ""
    status: str  # valid|warning|invalid
    issues: list[ValidationIssueOut] = []
    personalization_ready: bool = False


class ScoreBreakdownOut(BaseModel):
    valid_emails_pct: float = 0
    valid_phones_pct: float = 0
    duplicates: int = 0
    missing_fields: int = 0
    invalid_phones: int = 0
    personalization_readiness_pct: float = 0
    overall_quality: int = 0


class ValidationSummaryOut(BaseModel):
    total_rows: int = 0
    valid_rows: int = 0
    invalid_rows: int = 0
    warning_rows: int = 0
    duplicates: int = 0
    errors: int = 0
    warnings: int = 0
    ready_for_import: int = 0


class ColumnMappingOut(BaseModel):
    name: str | None = None
    email: str | None = None
    mobile: str | None = None
    sno: str | None = None
    headers: list[str] = []
    suggestions: list[str] = []


class DatasetValidationReport(BaseModel):
    quality_score: int
    score_breakdown: ScoreBreakdownOut
    summary: ValidationSummaryOut
    column_mapping: ColumnMappingOut
    recommendations: list[str] = []
    rows: list[ValidationRowOut] = []
    importable_count: int = 0


class DatasetImportResult(BaseModel):
    imported: int
    skipped: int = 0
    campaign: "CampaignOut"


# ---------- AI content + engagement sequence ----------
class AiGenerateIn(BaseModel):
    channel: str = "email"  # email|whatsapp|sms
    goal: str = ""
    tone: str = "professional"
    product: str = ""
    sender_name: str = ""
    company: str = ""
    followup_number: int = 0
    extra_context: str = ""
    save_to_campaign: bool = False


class AiGenerateOut(BaseModel):
    channel: str
    subject: str = ""
    body: str = ""
    tone: str = "professional"
    goal: str = ""
    followup_number: int = 0
    source: str = "template"
    inbox_tips: list[str] = []
    score: dict | None = None


class EngagementUpdateIn(BaseModel):
    reply_status: str | None = None  # not_replied|replied
    interest_status: str | None = None  # none|interested|not_interested
    call_scheduled_at: datetime | None = None
    call_notes: str | None = None


class FollowupSettingsIn(BaseModel):
    followup_enabled: bool | None = None
    followup_interval_days: int | None = None
    max_followups: int | None = None
    ai_goal: str | None = None
    ai_tone: str | None = None
    warmup_enabled: bool | None = None
    warmup_daily_cap: int | None = None


class SequenceStepIn(BaseModel):
    step_number: int = 0
    label: str = ""
    delay_days: int = 0
    send_time: str = "10:00"  # HH:MM 24h UTC
    email_enabled: bool = True
    email_subject: str = ""
    email_body: str = ""
    whatsapp_enabled: bool = False
    whatsapp_body: str = ""
    sms_enabled: bool = False
    sms_body: str = ""
    enabled: bool = True


class SequenceStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    campaign_id: int
    step_number: int
    label: str = ""
    delay_days: int = 0
    send_time: str = "10:00"
    email_enabled: bool = True
    email_subject: str = ""
    email_body: str = ""
    whatsapp_enabled: bool = False
    whatsapp_body: str = ""
    sms_enabled: bool = False
    sms_body: str = ""
    enabled: bool = True


class SequenceStepsBulkIn(BaseModel):
    """Replace the full ordered list of sequence steps for a campaign."""
    steps: list[SequenceStepIn]


class RecipientEngagementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str
    mobile: str
    active: bool
    reply_status: str = "not_replied"
    interest_status: str = "none"
    campaign_stopped: bool = False
    stop_reason: str = ""
    followup_count: int = 0
    last_followup_at: datetime | None = None
    next_followup_at: datetime | None = None
    call_scheduled_at: datetime | None = None
    call_notes: str = ""