from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..crypto import encrypt_secret, decrypt_secret
from ..database import get_db
from ..models import Project, User
from ..schemas import ProjectOut, ProjectCreate, ProjectUpdate
from ..deps import require, get_current_user, user_permissions
from ..smtp_mailer import test_smtp_connection, SmtpMailError
from ..storage import save_image_upload, delete_upload_if_local, delete_campaign_attachment

router = APIRouter(prefix="/api/projects", tags=["projects"])


def can_see_all(user: User) -> bool:
    perms = user_permissions(user)
    return "user.manage" in perms or "system.configure" in perms


def visible_or_404(db: Session, project_id: int, user: User) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not can_see_all(user) and project.id not in {p.id for p in user.projects}:
        raise HTTPException(status_code=403, detail="No access to this project")
    return project


def _to_out(p: Project) -> ProjectOut:
    out = ProjectOut.model_validate(p)
    out.campaign_count = len(p.campaigns)
    return out


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if can_see_all(user):
        projects = db.query(Project).order_by(Project.id.desc()).all()
    else:
        ids = {p.id for p in user.projects}
        projects = db.query(Project).filter(Project.id.in_(ids)).order_by(Project.id.desc()).all()
    return [_to_out(p) for p in projects]


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _to_out(visible_or_404(db, project_id, user))


@router.post("", response_model=ProjectOut)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db), _: User = Depends(require("project.create"))):
    data = payload.model_dump(exclude={"member_ids"})
    data["smtp_password"] = encrypt_secret(data["smtp_password"])
    project = Project(**data)
    if payload.member_ids:
        members = db.query(User).filter(User.id.in_(payload.member_ids)).all()
        for m in members:
            m.projects.append(project)
    db.add(project)
    db.commit()
    db.refresh(project)
    return _to_out(project)


@router.put("/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, payload: ProjectUpdate, db: Session = Depends(get_db),
                   user: User = Depends(require("project.edit"))):
    project = visible_or_404(db, project_id, user)
    data = payload.model_dump(exclude_unset=True, exclude={"member_ids"})
    # A blank password means "leave the saved one alone" -- ProjectOut never
    # returns the password to the frontend, so a re-opened form always starts
    # blank and would otherwise silently wipe out the working credentials on
    # every unrelated save.
    if "smtp_password" in data:
        if data["smtp_password"]:
            data["smtp_password"] = encrypt_secret(data["smtp_password"])
        else:
            del data["smtp_password"]
    for k, v in data.items():
        setattr(project, k, v)
    if payload.member_ids is not None:
        # reset memberships
        current = db.query(User).filter(User.projects.any(Project.id == project.id)).all()
        for u in current:
            u.projects = [p for p in u.projects if p.id != project.id]
        members = db.query(User).filter(User.id.in_(payload.member_ids)).all()
        for m in members:
            m.projects.append(project)
    db.commit()
    db.refresh(project)
    return _to_out(project)


@router.delete("/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db), user: User = Depends(require("project.delete"))):
    project = visible_or_404(db, project_id, user)
    if any(c.status == "sending" for c in project.campaigns):
        raise HTTPException(
            status_code=409,
            detail="This project has a campaign that is currently sending; wait for it to finish before deleting",
        )
    for campaign in project.campaigns:
        for att in campaign.attachments:
            delete_campaign_attachment(att.storage_path)
    delete_upload_if_local(project.logo_url)
    delete_upload_if_local(project.badge1_url)
    delete_upload_if_local(project.badge2_url)
    delete_upload_if_local(project.badge3_url)
    db.delete(project)
    db.commit()
    return {"ok": True}


@router.post("/{project_id}/logo", response_model=ProjectOut)
async def upload_logo(project_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                      user: User = Depends(require("project.edit"))):
    project = visible_or_404(db, project_id, user)
    old_url = project.logo_url
    project.logo_url = await save_image_upload(file)
    db.commit()
    db.refresh(project)
    delete_upload_if_local(old_url)
    return _to_out(project)


class SmtpTestIn(BaseModel):
    smtp_host: str
    smtp_port: int = 587
    smtp_encryption: str = "starttls"
    smtp_username: str = ""
    smtp_password: str = ""


@router.post("/{project_id}/smtp-test")
def test_smtp(project_id: int, payload: SmtpTestIn, db: Session = Depends(get_db),
              user: User = Depends(require("project.edit"))):
    """Verify SMTP credentials by opening a connection (and, for
    starttls/ssl, completing the TLS handshake). No email is sent.

    A blank password in the payload means "use the one already saved for
    this project" -- ProjectOut never returns the password to the frontend,
    so re-testing a previously saved config without retyping it must still
    work. Records last_tested_at/last_test_status either way, so a stale
    "connection verified" checkmark can't linger after credentials change.
    """
    project = visible_or_404(db, project_id, user)
    if not payload.smtp_host:
        raise HTTPException(status_code=400, detail="SMTP host is required")
    password = payload.smtp_password or decrypt_secret(project.smtp_password)

    def _record(status: str) -> None:
        project.smtp_last_tested_at = datetime.now(timezone.utc)
        project.smtp_last_test_status = status
        db.commit()

    try:
        message = test_smtp_connection(
            payload.smtp_host, payload.smtp_port, payload.smtp_encryption,
            payload.smtp_username, password,
        )
    except SmtpMailError as e:
        _record("failed")
        raise HTTPException(status_code=400, detail=str(e))
    _record("ok")
    return {"ok": True, "message": message}
