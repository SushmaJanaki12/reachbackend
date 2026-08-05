import copy
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import (
    Campaign, Project, Recipient, CampaignContent, CampaignAttachment, Message, User,
    DatasetValidationSession, ValidationOverrideLog,
)
from ..schemas import (
    CampaignOut, CampaignCreate, CampaignUpdate, ContentIn, ContentOut,
    RecipientOut, RecipientIn, RecipientActiveIn, PreviewIn, PreviewOut,
    CampaignAttachmentOut,
    ValidationSessionOut, ColumnMappingSuggestion, ColumnMappingIn, ApplyFixesIn, DatasetImportIn,
    ContentGenerateIn, ContentGenerateOut,
)
from ..deps import require, get_current_user, user_permissions
from ..campaign_utils import (
    render_template as _render, valid_email as _valid_email, valid_mobile as _valid_mobile,
)
from ..storage import save_campaign_attachment, delete_campaign_attachment
from ..worker import enqueue_message
from .. import dataset_validation as dv
from ..dataset_validation import parsing as dv_parsing, fixes as dv_fixes, report as dv_report
from ..dataset_validation.mapping import apply_mapping as dv_apply_mapping
from .. import content_ai

router = APIRouter(prefix="/api", tags=["campaigns"])
logger = logging.getLogger(__name__)

# Content is meant to be plain text with {{Placeholder}} tokens -- a since-reverted
# HTML/signature feature let raw markup leak into saved content, so reject it here.
HTML_TAG_RE = re.compile(r"<[a-zA-Z][^>]*>")


# ---------- helpers ----------
def _reset_if_completed(campaign: Campaign) -> None:
    """Changing who's in a campaign's recipient list also cascade-deletes any
    Message rows tied to the removed recipients (see Message.recipient_id's
    ondelete=CASCADE) -- so a "completed" campaign whose dataset was then
    edited would otherwise keep showing as sent (and refuse to re-send, see
    the 409 in send_campaign) even though the current recipients were never
    actually messaged."""
    if campaign.status == "completed":
        campaign.status = "draft"


def _accessible_project(db: Session, project_id: int, user: User) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    perms = user_permissions(user)
    see_all = "user.manage" in perms or "system.configure" in perms
    if not see_all and project.id not in {p.id for p in user.projects}:
        raise HTTPException(status_code=403, detail="No access to this project")
    return project


def _get_campaign(db: Session, campaign_id: int, user: User) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    _accessible_project(db, campaign.project_id, user)
    return campaign


def _columns(campaign: Campaign) -> list[str]:
    cols: list[str] = []
    for r in campaign.recipients:
        for k in (r.data or {}).keys():
            if k not in cols:
                cols.append(k)
    return cols


def _to_out(campaign: Campaign) -> CampaignOut:
    out = CampaignOut.model_validate(campaign)
    out.recipient_count = len(campaign.recipients)
    out.columns = _columns(campaign)
    out.project_name = campaign.project.name if campaign.project else ""
    out.last_import_batch_id = next(
        (r.batch_import_id for r in sorted(campaign.recipients, key=lambda r: -r.id) if r.batch_import_id), None)
    return out


# ---------- campaign CRUD ----------
@router.get("/campaigns", response_model=list[CampaignOut])
def list_all_campaigns(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """All campaigns across the projects the user can see."""
    perms = user_permissions(user)
    see_all = "user.manage" in perms or "system.configure" in perms
    if see_all:
        pids = [pid for (pid,) in db.query(Project.id).all()]
    else:
        pids = [p.id for p in user.projects]
    if not pids:
        return []
    campaigns = db.query(Campaign).filter(Campaign.project_id.in_(pids)).order_by(Campaign.id.desc()).all()
    return [_to_out(c) for c in campaigns]


@router.get("/projects/{project_id}/campaigns", response_model=list[CampaignOut])
def list_campaigns(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _accessible_project(db, project_id, user)
    campaigns = db.query(Campaign).filter_by(project_id=project_id).order_by(Campaign.id.desc()).all()
    return [_to_out(c) for c in campaigns]


@router.get("/campaigns/{campaign_id}", response_model=CampaignOut)
def get_campaign(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _to_out(_get_campaign(db, campaign_id, user))


@router.post("/campaigns", response_model=CampaignOut)
def create_campaign(payload: CampaignCreate, db: Session = Depends(get_db),
                    user: User = Depends(require("campaign.create"))):
    _accessible_project(db, payload.project_id, user)
    campaign = Campaign(project_id=payload.project_id, name=payload.name,
                        description=payload.description, created_by=user.id)
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return _to_out(campaign)


@router.put("/campaigns/{campaign_id}", response_model=CampaignOut)
def update_campaign(campaign_id: int, payload: CampaignUpdate, db: Session = Depends(get_db),
                    user: User = Depends(require("campaign.edit"))):
    campaign = _get_campaign(db, campaign_id, user)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(campaign, k, v)
    db.commit()
    db.refresh(campaign)
    return _to_out(campaign)


@router.delete("/campaigns/{campaign_id}")
def delete_campaign(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(require("campaign.delete"))):
    campaign = _get_campaign(db, campaign_id, user)
    if campaign.status == "sending":
        raise HTTPException(status_code=409, detail="Campaign is currently sending, please wait for it to finish before deleting")
    for att in campaign.attachments:
        delete_campaign_attachment(att.storage_path)
    db.delete(campaign)
    db.commit()
    return {"ok": True}


# ---------- dataset ----------
def _mapping_suggestions(headers: list[str], rows: list[dict],
                          column_mapping: dict[str, str | None]) -> list[ColumnMappingSuggestion]:
    return [
        ColumnMappingSuggestion(
            header=h, target_field=column_mapping.get(h),
            sample_values=[v for r in rows[:3] if (v := r["values"].get(h, ""))],
        )
        for h in headers
    ]


def _serialize_session(session: DatasetValidationSession, headers: list[str] | None = None,
                        encoding_warning: bool = False) -> ValidationSessionOut:
    headers = headers if headers is not None else list(session.column_mapping.keys())
    return ValidationSessionOut(
        id=session.id, campaign_id=session.campaign_id, original_filename=session.original_filename,
        status=session.status, mapping_confirmed=session.mapping_confirmed,
        column_mapping=session.column_mapping,
        mapping_suggestions=_mapping_suggestions(headers, session.working_rows, session.column_mapping),
        target_fields=dv.TARGET_FIELDS, mandatory_targets=list(dv.MANDATORY_TARGETS),
        issues=session.issues, summary=session.summary, quality_score=session.quality_score,
        encoding_warning=encoding_warning,
    )


def _get_session(db: Session, campaign: Campaign, session_id: int) -> DatasetValidationSession:
    session = db.get(DatasetValidationSession, session_id)
    if not session or session.campaign_id != campaign.id:
        raise HTTPException(status_code=404, detail="Validation session not found")
    if session.status == "active" and session.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
        raise HTTPException(status_code=410, detail="Validation session has expired; please re-upload the file")
    return session


def _re_evaluate(session: DatasetValidationSession) -> None:
    result = dv.evaluate(session.working_rows, session.column_mapping,
                          session.summary.get("empty_rows_skipped", 0))
    session.issues = result["issues"]
    session.summary = result["summary"]
    session.quality_score = result["quality_score"]


@router.post("/campaigns/{campaign_id}/dataset/validate", response_model=ValidationSessionOut)
async def validate_dataset(campaign_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                            user: User = Depends(require("dataset.upload"))):
    campaign = _get_campaign(db, campaign_id, user)
    raw = await file.read()
    max_bytes = int(settings.dataset_validation_max_file_mb * 1024 * 1024)
    if len(raw) > max_bytes:
        raise HTTPException(status_code=400,
                             detail=f"File exceeds the maximum of {settings.dataset_validation_max_file_mb} MB")

    try:
        parsed = dv_parsing.parse_file(file.filename, file.content_type, raw, settings.dataset_validation_max_rows)
    except dv_parsing.ParseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not parsed.rows:
        raise HTTPException(status_code=400, detail="No data rows found in the file")

    column_mapping = dv.suggest_mapping(parsed.headers, parsed.rows)
    result = dv.evaluate(parsed.rows, column_mapping, parsed.empty_rows_skipped)

    session = DatasetValidationSession(
        campaign_id=campaign.id, created_by=user.id, original_filename=file.filename or "upload",
        column_mapping=column_mapping, mapping_confirmed=False,
        raw_rows=parsed.rows, working_rows=copy.deepcopy(parsed.rows),
        issues=result["issues"], summary=result["summary"], quality_score=result["quality_score"],
        status="active",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.dataset_validation_session_ttl_minutes),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return _serialize_session(session, parsed.headers, parsed.encoding_warning)


@router.post("/campaigns/{campaign_id}/dataset/validate/{session_id}/mapping", response_model=ValidationSessionOut)
def confirm_dataset_mapping(campaign_id: int, session_id: int, payload: ColumnMappingIn,
                             db: Session = Depends(get_db), user: User = Depends(require("dataset.upload"))):
    campaign = _get_campaign(db, campaign_id, user)
    session = _get_session(db, campaign, session_id)
    if session.status != "active":
        raise HTTPException(status_code=400, detail="This validation session is no longer active")

    session.column_mapping = payload.column_mapping
    session.mapping_confirmed = True
    _re_evaluate(session)
    db.commit()
    db.refresh(session)
    return _serialize_session(session)


@router.post("/campaigns/{campaign_id}/dataset/validate/{session_id}/fixes", response_model=ValidationSessionOut)
def apply_dataset_fixes(campaign_id: int, session_id: int, payload: ApplyFixesIn,
                         db: Session = Depends(get_db), user: User = Depends(require("dataset.upload"))):
    campaign = _get_campaign(db, campaign_id, user)
    session = _get_session(db, campaign, session_id)
    if session.status != "active":
        raise HTTPException(status_code=400, detail="This validation session is no longer active")

    working_rows, _applied = dv_fixes.apply_fixes(
        copy.deepcopy(session.working_rows), session.column_mapping, session.issues,
        set(payload.fix_ids), payload.accept_all,
    )
    session.working_rows = working_rows
    _re_evaluate(session)
    db.commit()
    db.refresh(session)
    return _serialize_session(session)


@router.get("/campaigns/{campaign_id}/dataset/validate/{session_id}/report")
def download_validation_report(campaign_id: int, session_id: int, format: str = "csv",
                                db: Session = Depends(get_db), user: User = Depends(require("dataset.upload"))):
    campaign = _get_campaign(db, campaign_id, user)
    session = _get_session(db, campaign, session_id)
    if format == "xlsx":
        content = dv_report.to_xlsx(session.issues)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = "validation-report.xlsx"
    else:
        content = dv_report.to_csv(session.issues)
        media_type = "text/csv"
        filename = "validation-report.csv"
    return Response(content=content, media_type=media_type,
                     headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/campaigns/{campaign_id}/dataset/validate/{session_id}/import", response_model=CampaignOut)
def import_validated_dataset(campaign_id: int, session_id: int, payload: DatasetImportIn,
                              db: Session = Depends(get_db), user: User = Depends(require("dataset.upload"))):
    campaign = _get_campaign(db, campaign_id, user)
    session = _get_session(db, campaign, session_id)
    if session.status != "active":
        raise HTTPException(status_code=400, detail="This validation session is no longer active")
    if not session.mapping_confirmed:
        raise HTTPException(status_code=400, detail="Confirm the column mapping before importing")

    ignore_warnings = payload.mode == "ignore_warnings"
    if ignore_warnings and "dataset.override_warnings" not in user_permissions(user):
        raise HTTPException(status_code=403, detail="Insufficient permissions to ignore validation warnings")

    ready_rows = dv.rows_ready_for_import(session.working_rows, session.issues, ignore_warnings)
    if not ready_rows:
        raise HTTPException(status_code=400, detail="No rows are eligible for import")

    batch_id = str(uuid.uuid4())
    db.query(Recipient).filter_by(campaign_id=campaign.id).delete()
    _reset_if_completed(campaign)
    for row in ready_rows:
        mapped = dv_apply_mapping(row["values"], session.column_mapping)
        clean = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row["values"].items() if k}
        db.add(Recipient(
            campaign_id=campaign.id, name=mapped["name"], email=mapped["email"], mobile=mapped["mobile"],
            data=clean, batch_import_id=batch_id,
        ))

    session.status = "imported"
    session.batch_import_id = batch_id
    session.imported_at = datetime.now(timezone.utc)

    if ignore_warnings:
        ready_row_numbers = {r["row_number"] for r in ready_rows}
        warning_issues = [i for i in session.issues if i["severity"] == "warning"
                           and i["row_number"] in ready_row_numbers]
        db.add(ValidationOverrideLog(
            session_id=session.id, campaign_id=campaign.id, user_id=user.id,
            warning_row_count=len({i["row_number"] for i in warning_issues}),
            warning_types=sorted({i["issue_type"] for i in warning_issues}),
        ))

    db.commit()
    db.refresh(campaign)
    return _to_out(campaign)


@router.delete("/campaigns/{campaign_id}/dataset/validate/{session_id}")
def cancel_dataset_validation(campaign_id: int, session_id: int, db: Session = Depends(get_db),
                               user: User = Depends(require("dataset.upload"))):
    campaign = _get_campaign(db, campaign_id, user)
    session = _get_session(db, campaign, session_id)
    session.status = "cancelled"
    db.commit()
    return {"ok": True}


@router.post("/campaigns/{campaign_id}/dataset/batches/{batch_import_id}/undo", response_model=CampaignOut)
def undo_import_batch(campaign_id: int, batch_import_id: str, db: Session = Depends(get_db),
                       user: User = Depends(require("dataset.upload"))):
    """Cheap rollback enabled by tagging every import with a batch id (PRD
    Sec. 15) -- removes only the recipients that came from that one import,
    leaving any other batch (or manually-added recipients) untouched."""
    campaign = _get_campaign(db, campaign_id, user)
    deleted = db.query(Recipient).filter_by(campaign_id=campaign.id, batch_import_id=batch_import_id).delete()
    if not deleted:
        raise HTTPException(status_code=404, detail="No recipients found for that import batch")
    _reset_if_completed(campaign)
    db.commit()
    db.refresh(campaign)
    return _to_out(campaign)


@router.delete("/campaigns/{campaign_id}/dataset", response_model=CampaignOut)
def delete_dataset(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(require("dataset.upload"))):
    campaign = _get_campaign(db, campaign_id, user)
    db.query(Recipient).filter_by(campaign_id=campaign.id).delete()
    _reset_if_completed(campaign)
    db.commit()
    db.refresh(campaign)
    return _to_out(campaign)


@router.get("/campaigns/{campaign_id}/recipients", response_model=list[RecipientOut])
def list_recipients(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = _get_campaign(db, campaign_id, user)
    return campaign.recipients


def _recipient_data(campaign: Campaign, name: str, email: str, mobile: str) -> dict:
    """Build placeholder data, reusing the campaign's existing column keys when present."""
    existing = list(campaign.recipients[0].data.keys()) if campaign.recipients else []

    def find(*cands):
        for k in existing:
            if k.lower() in cands:
                return k
        return None

    name_k = find("name") or "Name"
    email_k = find("email", "email address", "email id") or "Email Address"
    mobile_k = find("mobile", "mobile number", "phone", "mobile no") or "Mobile Number"
    data = {name_k: name, email_k: email, mobile_k: mobile}
    for k in existing:
        data.setdefault(k, "")
    return data


@router.post("/campaigns/{campaign_id}/recipients", response_model=RecipientOut)
def add_recipient(campaign_id: int, payload: RecipientIn, db: Session = Depends(get_db),
                  user: User = Depends(require("dataset.upload"))):
    campaign = _get_campaign(db, campaign_id, user)
    name, email, mobile = payload.name.strip(), payload.email.strip(), payload.mobile.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if not email and not mobile:
        raise HTTPException(status_code=400, detail="Provide an email address or a mobile number")
    rec = Recipient(campaign_id=campaign.id, name=name, email=email, mobile=mobile,
                    data=_recipient_data(campaign, name, email, mobile))
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


@router.patch("/campaigns/{campaign_id}/recipients/{recipient_id}", response_model=RecipientOut)
def set_recipient_active(campaign_id: int, recipient_id: int, payload: RecipientActiveIn,
                         db: Session = Depends(get_db), user: User = Depends(require("dataset.upload"))):
    campaign = _get_campaign(db, campaign_id, user)
    rec = db.get(Recipient, recipient_id)
    if not rec or rec.campaign_id != campaign.id:
        raise HTTPException(status_code=404, detail="Recipient not found")
    rec.active = payload.active
    db.commit()
    db.refresh(rec)
    return rec


@router.delete("/campaigns/{campaign_id}/recipients/{recipient_id}")
def remove_recipient(campaign_id: int, recipient_id: int, db: Session = Depends(get_db),
                     user: User = Depends(require("dataset.upload"))):
    campaign = _get_campaign(db, campaign_id, user)
    rec = db.get(Recipient, recipient_id)
    if not rec or rec.campaign_id != campaign.id:
        raise HTTPException(status_code=404, detail="Recipient not found")
    db.delete(rec)
    db.commit()
    return {"ok": True}


# ---------- content ----------
@router.get("/campaigns/{campaign_id}/content", response_model=list[ContentOut])
def get_content(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = _get_campaign(db, campaign_id, user)
    return campaign.contents


@router.put("/campaigns/{campaign_id}/content/{channel}", response_model=ContentOut)
def set_content(campaign_id: int, channel: str, payload: ContentIn, db: Session = Depends(get_db),
                user: User = Depends(require("content.edit"))):
    if channel not in ("email", "whatsapp", "sms"):
        raise HTTPException(status_code=400, detail="Invalid channel")
    if channel == "email" and HTML_TAG_RE.search(payload.subject):
        raise HTTPException(
            status_code=400,
            detail="Email subject must be plain text -- HTML markup is not allowed",
        )
    if channel == "email" and HTML_TAG_RE.search(payload.body):
        raise HTTPException(
            status_code=400,
            detail="Email subject/body must be plain text -- HTML markup is not allowed",
        )
    campaign = _get_campaign(db, campaign_id, user)
    content = db.query(CampaignContent).filter_by(campaign_id=campaign.id, channel=channel).first()
    if not content:
        content = CampaignContent(campaign_id=campaign.id, channel=channel)
        db.add(content)
    content.subject = payload.subject
    content.body = payload.body
    db.commit()
    db.refresh(content)
    return content


@router.post("/campaigns/{campaign_id}/content/{channel}/generate", response_model=ContentGenerateOut)
def generate_content(campaign_id: int, channel: str, payload: ContentGenerateIn, db: Session = Depends(get_db),
                      user: User = Depends(require("content.edit"))):
    """Drafts subject/body from a free-text prompt (replaces the old manual
    branded-template authoring mode) -- never saved automatically, the
    caller still edits/saves the result through the normal content editor."""
    if channel not in ("email", "whatsapp", "sms"):
        raise HTTPException(status_code=400, detail="Invalid channel")
    if not payload.prompt.strip():
        raise HTTPException(status_code=400, detail="Enter a prompt to generate content")
    if not settings.ai_suggestions_configured:
        raise HTTPException(status_code=400, detail="Generative AI isn't configured for this workspace")

    campaign = _get_campaign(db, campaign_id, user)
    result = content_ai.generate(payload.prompt.strip(), channel, _columns(campaign), campaign.project)
    if result is None:
        raise HTTPException(status_code=502, detail="Content generation failed, please try again")
    return ContentGenerateOut(**result)


# ---------- attachments ----------
@router.get("/campaigns/{campaign_id}/attachments", response_model=list[CampaignAttachmentOut])
def list_attachments(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = _get_campaign(db, campaign_id, user)
    return campaign.attachments


@router.post("/campaigns/{campaign_id}/attachments", response_model=CampaignAttachmentOut)
async def upload_attachment(campaign_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                            user: User = Depends(require("content.edit"))):
    campaign = _get_campaign(db, campaign_id, user)
    existing_total = sum(a.size_bytes for a in campaign.attachments)
    storage_path, size_bytes, content_type = await save_campaign_attachment(file, existing_total)
    att = CampaignAttachment(
        campaign_id=campaign.id, filename=file.filename or "attachment",
        content_type=content_type, storage_path=storage_path, size_bytes=size_bytes,
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return att


@router.delete("/campaigns/{campaign_id}/attachments/{attachment_id}")
def remove_attachment(campaign_id: int, attachment_id: int, db: Session = Depends(get_db),
                      user: User = Depends(require("content.edit"))):
    campaign = _get_campaign(db, campaign_id, user)
    att = db.get(CampaignAttachment, attachment_id)
    if not att or att.campaign_id != campaign.id:
        raise HTTPException(status_code=404, detail="Attachment not found")
    delete_campaign_attachment(att.storage_path)
    db.delete(att)
    db.commit()
    return {"ok": True}


@router.post("/campaigns/{campaign_id}/preview", response_model=PreviewOut)
def preview(campaign_id: int, payload: PreviewIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = _get_campaign(db, campaign_id, user)
    recipient = None
    if payload.recipient_id:
        recipient = db.get(Recipient, payload.recipient_id)
        if recipient is None or recipient.campaign_id != campaign.id:
            raise HTTPException(status_code=404, detail="Recipient not found")
    if recipient is None and campaign.recipients:
        recipient = campaign.recipients[0]
    data = dict((recipient.data if recipient else {}) or {})
    missing: list[str] = []
    return PreviewOut(
        subject=_render(payload.subject, data, missing),
        body=_render(payload.body, data, missing),
        missing=sorted(set(missing)),
    )


# ---------- send ----------
@router.post("/campaigns/{campaign_id}/send", response_model=CampaignOut)
def send_campaign(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(require("campaign.send"))):
    campaign = _get_campaign(db, campaign_id, user)
    project = campaign.project

    if campaign.status == "sending":
        raise HTTPException(status_code=409, detail="Campaign is currently sending, please wait")
    # A "completed" campaign is deliberately re-sendable -- e.g. a follow-up
    # blast to the same dataset. The "clear previous run" step below replaces
    # last run's Message rows, so tracking always reflects only the latest send.

    active_recipients = [r for r in campaign.recipients if r.active]
    if not active_recipients:
        raise HTTPException(status_code=400, detail="Upload a recipient dataset before sending")

    channels = []
    if campaign.email_enabled:
        channels.append("email")
    if campaign.whatsapp_enabled and project.whatsapp_active:
        channels.append("whatsapp")
    if campaign.sms_enabled and project.sms_active:
        channels.append("sms")
    if not channels:
        raise HTTPException(status_code=400, detail="No active channels for this campaign (check project channel config)")

    content_map = {c.channel: c for c in campaign.contents}
    for ch in channels:
        if ch not in content_map:
            raise HTTPException(status_code=400, detail=f"No content authored for channel: {ch}")

    # clear previous run
    db.query(Message).filter_by(campaign_id=campaign.id).delete()
    db.commit()

    queued_ids = []
    for rec in active_recipients:
        for ch in channels:
            to = rec.email if ch == "email" else rec.mobile
            valid = _valid_email(to) if ch == "email" else _valid_mobile(to)
            msg = Message(
                campaign_id=campaign.id, recipient_id=rec.id, channel=ch,
                to_address=to, recipient_name=rec.name,
            )
            if not valid:
                msg.status = "failed"
                msg.error = "Invalid email address" if ch == "email" else "Invalid mobile number"
            else:
                msg.status = "queued"
            db.add(msg)
            # Commit each row as soon as it's created so a mid-loop crash never
            # leaves a message unaccounted for.
            db.commit()
            if msg.status == "queued":
                queued_ids.append(msg.id)

    campaign.status = "sending"
    db.commit()
    db.refresh(campaign)

    # Enqueue only after every Message row is committed -- a worker picking up
    # the first job must always find the rest of the campaign's rows in place.
    for mid in queued_ids:
        enqueue_message(mid)

    logger.info("campaign %s: send requested, %s message(s) enqueued across channels %s",
                campaign.id, len(queued_ids), channels)
    return _to_out(campaign)
