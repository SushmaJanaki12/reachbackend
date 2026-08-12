from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, File
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    Template, TemplateCategory, EmailTemplateContent, WhatsappTemplateContent, TemplateAttachment,
    Project, Recipient, User,
)
from ..pagination import Pagination, paginate
from ..schemas import (
    TemplateOut, TemplateCreate, TemplateUpdate,
    TemplateCategoryIn, TemplateCategoryOut,
    TemplateLibraryPreviewIn, TemplatePreviewOut, TemplateAttachmentOut,
)
from ..deps import require, user_permissions
from ..email_template import render_email_template
from ..storage import save_campaign_attachment, delete_campaign_attachment

router = APIRouter(prefix="/api", tags=["templates"])

# SMS templates are DLT-registered (India telecom compliance) and have no
# draft/published/archived lifecycle or per-project branding -- they stay in
# their own table (SmsTemplate, managed via /api/sms/templates) rather than
# living in this umbrella table. The Templates page merges both sources
# client-side into one list.
CREATABLE_CHANNELS = ("email", "whatsapp")


def _blank_project() -> SimpleNamespace:
    """Stand-in for a Project when previewing a template with no project
    context selected -- renders the branded shell with blank branding rather
    than guessing which real project's branding to use."""
    return SimpleNamespace(
        logo_url="", name="", company_website="", company_address="",
        sender_name="", sender_designation="", sender_phone="",
        badge1_url="", badge2_url="", badge3_url="",
    )


def _accessible_project(db: Session, project_id: int, user: User) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    perms = user_permissions(user)
    see_all = "user.manage" in perms or "system.configure" in perms
    if not see_all and project.id not in {p.id for p in user.projects}:
        raise HTTPException(status_code=403, detail="No access to this project")
    return project


def _get_template(db: Session, template_id: int) -> Template:
    template = db.get(Template, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


def _apply_content(db: Session, template: Template, payload) -> None:
    if template.channel == "email":
        content = template.email_content
        if content is None:
            content = EmailTemplateContent(template_id=template.id)
            db.add(content)
        if payload.email_content is not None:
            content.subject = payload.email_content.subject
            content.fields = payload.email_content.fields.model_dump()
            content.branding_override = payload.email_content.branding_override
        template.email_content = content
    elif template.channel == "whatsapp":
        content = template.whatsapp_content
        if content is None:
            content = WhatsappTemplateContent(template_id=template.id)
            db.add(content)
        if payload.whatsapp_content is not None:
            wc = payload.whatsapp_content
            content.meta_template_name = wc.meta_template_name
            content.meta_template_id = wc.meta_template_id
            content.language_code = wc.language_code
            content.header_type = wc.header_type
            content.header_content = wc.header_content
            content.body_text = wc.body_text
            content.footer_text = wc.footer_text
            content.buttons = wc.buttons
        template.whatsapp_content = content


# ---------- categories ----------
@router.get("/template-categories", response_model=list[TemplateCategoryOut])
def list_categories(db: Session = Depends(get_db), _: User = Depends(require("template.view"))):
    return db.query(TemplateCategory).order_by(TemplateCategory.name).all()


@router.post("/template-categories", response_model=TemplateCategoryOut)
def create_category(payload: TemplateCategoryIn, db: Session = Depends(get_db),
                    _: User = Depends(require("template.edit"))):
    if db.query(TemplateCategory).filter_by(name=payload.name).first():
        raise HTTPException(status_code=400, detail="Category already exists")
    category = TemplateCategory(name=payload.name)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


# ---------- templates ----------
@router.get("/templates", response_model=list[TemplateOut])
def list_templates(response: Response, channel: str | None = None, category_id: int | None = None,
                   status: str | None = None, q: str | None = None, pagination: Pagination = Depends(),
                   db: Session = Depends(get_db), _: User = Depends(require("template.view"))):
    query = db.query(Template)
    if channel:
        query = query.filter(Template.channel == channel)
    if category_id:
        query = query.filter(Template.category_id == category_id)
    if status:
        query = query.filter(Template.status == status)
    if q:
        query = query.filter(Template.name.ilike(f"%{q}%"))
    query = query.order_by(Template.updated_at.desc())
    return paginate(query, pagination, response)


@router.post("/templates", response_model=TemplateOut)
def create_template(payload: TemplateCreate, db: Session = Depends(get_db),
                    user: User = Depends(require("template.edit"))):
    if payload.channel not in CREATABLE_CHANNELS:
        raise HTTPException(status_code=400, detail="Invalid channel")
    if payload.channel == "whatsapp" and payload.whatsapp_content is None:
        raise HTTPException(status_code=400, detail="whatsapp_content is required for a WhatsApp template")
    template = Template(
        name=payload.name, description=payload.description, channel=payload.channel,
        category_id=payload.category_id, created_by=user.id,
    )
    db.add(template)
    db.flush()
    _apply_content(db, template, payload)
    db.commit()
    db.refresh(template)
    return template


@router.get("/templates/{template_id}", response_model=TemplateOut)
def get_template(template_id: int, db: Session = Depends(get_db), _: User = Depends(require("template.view"))):
    return _get_template(db, template_id)


@router.put("/templates/{template_id}", response_model=TemplateOut)
def update_template(template_id: int, payload: TemplateUpdate, db: Session = Depends(get_db),
                    _: User = Depends(require("template.edit"))):
    template = _get_template(db, template_id)
    if payload.name is not None:
        template.name = payload.name
    if payload.description is not None:
        template.description = payload.description
    if payload.category_id is not None:
        template.category_id = payload.category_id
    if payload.status is not None:
        if payload.status not in ("draft", "published"):
            raise HTTPException(
                status_code=400,
                detail="Use POST /templates/{id}/archive to archive a template",
            )
        template.status = payload.status
    _apply_content(db, template, payload)
    db.commit()
    db.refresh(template)
    return template


@router.post("/templates/{template_id}/duplicate", response_model=TemplateOut)
def duplicate_template(template_id: int, db: Session = Depends(get_db),
                       user: User = Depends(require("template.edit"))):
    source = _get_template(db, template_id)
    copy = Template(
        name=f"{source.name} (Copy)", description=source.description, channel=source.channel,
        category_id=source.category_id, status="draft", created_by=user.id,
    )
    db.add(copy)
    db.flush()
    if source.channel == "email" and source.email_content:
        db.add(EmailTemplateContent(
            template_id=copy.id, subject=source.email_content.subject,
            fields=dict(source.email_content.fields or {}),
            branding_override=dict(source.email_content.branding_override) if source.email_content.branding_override else None,
        ))
    elif source.channel == "whatsapp" and source.whatsapp_content:
        wc = source.whatsapp_content
        db.add(WhatsappTemplateContent(
            template_id=copy.id, meta_template_name=wc.meta_template_name,
            meta_template_id=wc.meta_template_id, language_code=wc.language_code,
            header_type=wc.header_type, header_content=wc.header_content,
            body_text=wc.body_text, footer_text=wc.footer_text, buttons=list(wc.buttons or []),
        ))
    db.commit()
    db.refresh(copy)
    return copy


@router.post("/templates/{template_id}/archive", response_model=TemplateOut)
def archive_template(template_id: int, db: Session = Depends(get_db),
                     _: User = Depends(require("template.archive"))):
    template = _get_template(db, template_id)
    template.status = "archived"
    db.commit()
    db.refresh(template)
    return template


@router.delete("/templates/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db),
                    _: User = Depends(require("template.delete"))):
    template = _get_template(db, template_id)
    for att in template.attachments:
        delete_campaign_attachment(att.storage_path)
    db.delete(template)
    db.commit()
    return {"ok": True}


@router.post("/templates/{template_id}/preview", response_model=TemplatePreviewOut)
def preview_template(template_id: int, payload: TemplateLibraryPreviewIn, db: Session = Depends(get_db),
                     user: User = Depends(require("template.view"))):
    template = _get_template(db, template_id)

    recipient = None
    if payload.recipient_id:
        recipient = db.get(Recipient, payload.recipient_id)
        if recipient is None:
            raise HTTPException(status_code=404, detail="Recipient not found")
        _accessible_project(db, recipient.campaign.project_id, user)

    if template.channel == "email":
        content = template.email_content
        fields = dict(content.fields or {}) if content else {}
        project = _blank_project()
        missing: list[str] = []
        html_out = render_email_template(project, fields, recipient, missing)
        return TemplatePreviewOut(html=html_out, missing=sorted(set(missing)))

    # whatsapp: catalog-only (see CREATABLE_CHANNELS note) -- no Meta-side
    # component-parameter resolution is modeled here, so this just renders
    # the stored header/body/footer as a plain preview, unresolved.
    content = template.whatsapp_content
    if content is None:
        return TemplatePreviewOut(html="", missing=[])
    import html as _html
    parts = []
    if content.header_content:
        parts.append(f"<div><strong>{_html.escape(content.header_content)}</strong></div>")
    parts.append(f"<div>{_html.escape(content.body_text).replace(chr(10), '<br>')}</div>")
    if content.footer_text:
        parts.append(f"<div style='color:#888;font-size:0.85em'>{_html.escape(content.footer_text)}</div>")
    return TemplatePreviewOut(html="".join(parts), missing=[])


# ---------- attachments (email templates only) ----------
@router.get("/templates/{template_id}/attachments", response_model=list[TemplateAttachmentOut])
def list_attachments(template_id: int, db: Session = Depends(get_db), _: User = Depends(require("template.view"))):
    template = _get_template(db, template_id)
    return template.attachments


@router.post("/templates/{template_id}/attachments", response_model=TemplateAttachmentOut)
async def upload_attachment(template_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                            _: User = Depends(require("template.edit"))):
    template = _get_template(db, template_id)
    if template.channel != "email":
        raise HTTPException(status_code=400, detail="Attachments are only supported on Email templates")
    existing_total = sum(a.size_bytes for a in template.attachments)
    storage_path, size_bytes, content_type = await save_campaign_attachment(file, existing_total)
    att = TemplateAttachment(
        template_id=template.id, filename=file.filename or "attachment",
        content_type=content_type, storage_path=storage_path, size_bytes=size_bytes,
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return att


@router.delete("/templates/{template_id}/attachments/{attachment_id}")
def remove_attachment(template_id: int, attachment_id: int, db: Session = Depends(get_db),
                      _: User = Depends(require("template.edit"))):
    template = _get_template(db, template_id)
    att = db.get(TemplateAttachment, attachment_id)
    if not att or att.template_id != template.id:
        raise HTTPException(status_code=404, detail="Attachment not found")
    delete_campaign_attachment(att.storage_path)
    db.delete(att)
    db.commit()
    return {"ok": True}
