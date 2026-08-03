import csv
import io
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Campaign, Project, Recipient, CampaignContent, CampaignAttachment, Message, User, Template
from ..schemas import (
    CampaignOut, CampaignCreate, CampaignUpdate, ContentIn, ContentOut,
    RecipientOut, RecipientIn, RecipientActiveIn, PreviewIn, PreviewOut,
    TemplatePreviewIn, TemplatePreviewOut, CampaignAttachmentOut,
)
from ..deps import require, get_current_user, user_permissions
from ..campaign_utils import (
    render_template as _render, valid_email as _valid_email, valid_mobile as _valid_mobile,
)
from ..email_template import render_email_template
from ..storage import save_campaign_attachment, delete_campaign_attachment
from ..worker import enqueue_message

router = APIRouter(prefix="/api", tags=["campaigns"])
logger = logging.getLogger(__name__)

# Content is meant to be plain text with {{Placeholder}} tokens -- a since-reverted
# HTML/signature feature let raw markup leak into saved content, so reject it here.
HTML_TAG_RE = re.compile(r"<[a-zA-Z][^>]*>")


# ---------- helpers ----------
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
@router.post("/campaigns/{campaign_id}/dataset", response_model=CampaignOut)
async def upload_dataset(campaign_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                         user: User = Depends(require("dataset.upload"))):
    campaign = _get_campaign(db, campaign_id, user)
    raw = await file.read()
    filename = (file.filename or "").lower()

    rows: list[dict] = []
    if filename.endswith(".csv") or file.content_type in ("text/csv", "application/vnd.ms-excel"):
        text = raw.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        rows = [dict(r) for r in reader]
    elif filename.endswith(".xlsx"):
        from openpyxl import load_workbook

        def cell_to_str(val):
            # openpyxl hands back number-formatted cells (e.g. phone numbers,
            # zip codes) as Python floats, so plain str() would append a
            # spurious ".0" (9876543210.0) -- collapse whole-number floats
            # back to integer text.
            if val is None:
                return ""
            if isinstance(val, float) and val.is_integer():
                return str(int(val))
            return str(val)

        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        headers = [str(h).strip() if h is not None else "" for h in next(it, [])]
        for values in it:
            if values is None:
                continue
            row = {}
            for i, h in enumerate(headers):
                if not h:
                    continue
                val = values[i] if i < len(values) else None
                row[h] = cell_to_str(val)
            if any(v for v in row.values()):
                rows.append(row)
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type. Upload .csv or .xlsx")

    if not rows:
        raise HTTPException(status_code=400, detail="No data rows found in the file")

    # validate mandatory columns (case-insensitive)
    headers_lower = {k.lower(): k for k in rows[0].keys()}

    def find(*names):
        for n in names:
            if n in headers_lower:
                return headers_lower[n]
        return None

    name_col = find("name")
    email_col = find("email", "email address", "email id")
    mobile_col = find("mobile", "mobile number", "phone", "mobile no")
    missing = [label for label, col in
               [("Name", name_col), ("Email Address", email_col), ("Mobile Number", mobile_col)] if col is None]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing mandatory column(s): {', '.join(missing)}")

    # replace existing recipients
    db.query(Recipient).filter_by(campaign_id=campaign.id).delete()
    imported = 0
    for row in rows:
        clean = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k}
        rec = Recipient(
            campaign_id=campaign.id,
            name=str(clean.get(name_col, "")).strip(),
            email=str(clean.get(email_col, "")).strip(),
            mobile=str(clean.get(mobile_col, "")).strip(),
            data=clean,
        )
        db.add(rec)
        imported += 1
    db.commit()
    db.refresh(campaign)
    return _to_out(campaign)


@router.delete("/campaigns/{campaign_id}/dataset", response_model=CampaignOut)
def delete_dataset(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(require("dataset.upload"))):
    campaign = _get_campaign(db, campaign_id, user)
    db.query(Recipient).filter_by(campaign_id=campaign.id).delete()
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
    # Only the email channel supports the branded-template mode; whatsapp/sms
    # always stay plain text regardless of what the client sends.
    content_mode = payload.content_mode if channel == "email" else "plain"
    if content_mode not in ("plain", "template"):
        raise HTTPException(status_code=400, detail="Invalid content mode")
    # The subject line is always plain text, in both modes. The body is only
    # checked when it's actually going to be used (plain mode) -- in template
    # mode the structured fields are the source of truth and body is ignored.
    if channel == "email" and HTML_TAG_RE.search(payload.subject):
        raise HTTPException(
            status_code=400,
            detail="Email subject must be plain text -- HTML markup is not allowed",
        )
    if channel == "email" and content_mode == "plain" and HTML_TAG_RE.search(payload.body):
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
    content.content_mode = content_mode
    if content_mode == "template":
        content.body = ""
        content.template_fields = payload.template_fields.model_dump()
    else:
        content.body = payload.body
        content.template_fields = {}
    db.commit()
    db.refresh(content)
    return content


@router.post("/campaigns/{campaign_id}/content/{channel}/from-template/{template_id}", response_model=ContentOut)
def set_content_from_template(campaign_id: int, channel: str, template_id: int, db: Session = Depends(get_db),
                              user: User = Depends(require("content.edit"))):
    """Copy a library template's resolved content into this campaign's own
    content storage. From this point on it's an independent copy -- editing
    it here never touches the source `templates` row, and editing the source
    template later never changes what this campaign is shown to have sent
    (source_template_id is kept only so reporting can trace it back)."""
    if channel not in ("email", "whatsapp"):
        raise HTTPException(status_code=400, detail="Invalid channel")
    campaign = _get_campaign(db, campaign_id, user)
    template = db.get(Template, template_id)
    if not template or template.channel != channel:
        raise HTTPException(status_code=404, detail="Template not found")
    if template.status != "published":
        raise HTTPException(status_code=400, detail="Only published templates can be used in a campaign")

    content = db.query(CampaignContent).filter_by(campaign_id=campaign.id, channel=channel).first()
    if not content:
        content = CampaignContent(campaign_id=campaign.id, channel=channel)
        db.add(content)

    if channel == "email":
        if not template.email_content:
            raise HTTPException(status_code=400, detail="This template has no email content")
        content.subject = template.email_content.subject
        content.content_mode = "template"
        content.body = ""
        content.template_fields = dict(template.email_content.fields or {})
    else:  # whatsapp
        if not template.whatsapp_content:
            raise HTTPException(status_code=400, detail="This template has no WhatsApp content")
        wc = template.whatsapp_content
        content.subject = ""
        content.content_mode = "plain"
        content.body = wc.body_text
        content.template_fields = {}

    content.source_template_id = template.id
    db.commit()
    db.refresh(content)
    return content


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


@router.post("/campaigns/{campaign_id}/preview-template", response_model=TemplatePreviewOut)
def preview_template(campaign_id: int, payload: TemplatePreviewIn, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """Live preview for the branded-template email content mode -- renders the
    fixed HTML shell (never user-typed markup) with the campaign's unsaved
    structured field values, for the sandboxed iframe preview on the frontend."""
    campaign = _get_campaign(db, campaign_id, user)
    recipient = None
    if payload.recipient_id:
        recipient = db.get(Recipient, payload.recipient_id)
        if recipient is None or recipient.campaign_id != campaign.id:
            raise HTTPException(status_code=404, detail="Recipient not found")
    if recipient is None and campaign.recipients:
        recipient = campaign.recipients[0]
    missing: list[str] = []
    html_out = render_email_template(campaign.project, payload.fields.model_dump(), recipient, missing)
    return TemplatePreviewOut(html=html_out, missing=sorted(set(missing)))


# ---------- send ----------
@router.post("/campaigns/{campaign_id}/send", response_model=CampaignOut)
def send_campaign(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(require("campaign.send"))):
    campaign = _get_campaign(db, campaign_id, user)
    project = campaign.project

    if campaign.status == "sending":
        raise HTTPException(status_code=409, detail="Campaign is currently sending, please wait")

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
