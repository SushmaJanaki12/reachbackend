from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    Template, TemplateCategory, EmailTemplateContent, WhatsappTemplateContent,
    CampaignContent, Project, Recipient, User,
)
from ..schemas import (
    TemplateOut, TemplateCreate, TemplateUpdate,
    TemplateCategoryIn, TemplateCategoryOut,
    TemplateLibraryPreviewIn, TemplatePreviewOut,
)
from ..deps import require, user_permissions
from ..email_template import render_email_template

router = APIRouter(prefix="/api", tags=["templates"])

CHANNELS = ("email", "whatsapp", "sms")
# SMS templates are still authored/managed via the existing DLT-template
# endpoints in routers/sms.py (matches_template() validation on the send
# path depends on that flow staying as-is) -- this router only lists them
# alongside Email/WhatsApp for a unified library view (see backfill in
# migration a1c4e9f27b53).
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
def list_templates(channel: str | None = None, category_id: int | None = None, status: str | None = None,
                   q: str | None = None, db: Session = Depends(get_db),
                   _: User = Depends(require("template.view"))):
    query = db.query(Template)
    if channel:
        query = query.filter(Template.channel == channel)
    if category_id:
        query = query.filter(Template.category_id == category_id)
    if status:
        query = query.filter(Template.status == status)
    if q:
        query = query.filter(Template.name.ilike(f"%{q}%"))
    return query.order_by(Template.updated_at.desc()).all()


@router.post("/templates", response_model=TemplateOut)
def create_template(payload: TemplateCreate, db: Session = Depends(get_db),
                    user: User = Depends(require("template.edit"))):
    if payload.channel not in CREATABLE_CHANNELS:
        raise HTTPException(
            status_code=400,
            detail="SMS templates are managed under SMS DLT Templates" if payload.channel == "sms"
            else "Invalid channel",
        )
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
    in_use = db.query(CampaignContent).filter_by(source_template_id=template.id).first()
    if in_use:
        raise HTTPException(
            status_code=409,
            detail="This template has been used in a campaign and can't be deleted -- archive it instead",
        )
    db.delete(template)
    db.commit()
    return {"ok": True}


@router.post("/templates/{template_id}/preview", response_model=TemplatePreviewOut)
def preview_template(template_id: int, payload: TemplateLibraryPreviewIn, db: Session = Depends(get_db),
                     user: User = Depends(require("template.view"))):
    template = _get_template(db, template_id)
    if template.channel == "sms":
        raise HTTPException(status_code=400, detail="Use the SMS DLT template validation endpoints instead")

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
