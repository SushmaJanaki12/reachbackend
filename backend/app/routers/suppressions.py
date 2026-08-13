from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Project, Suppression, User
from ..schemas import SuppressionIn, SuppressionOut
from ..deps import require, user_permissions

router = APIRouter(prefix="/api/projects/{project_id}/suppressions", tags=["suppressions"])


def _accessible_project(db: Session, project_id: int, user: User) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    perms = user_permissions(user)
    see_all = "user.manage" in perms or "system.configure" in perms
    if not see_all and project.id not in {p.id for p in user.projects}:
        raise HTTPException(status_code=403, detail="No access to this project")
    return project


def normalize_contact(contact: str) -> str:
    return (contact or "").strip().lower()


@router.get("", response_model=list[SuppressionOut])
def list_suppressions(project_id: int, db: Session = Depends(get_db),
                      user: User = Depends(require("suppression.manage"))):
    _accessible_project(db, project_id, user)
    return db.query(Suppression).filter_by(project_id=project_id).order_by(Suppression.id.desc()).all()


@router.post("", response_model=SuppressionOut)
def add_suppression(project_id: int, payload: SuppressionIn, db: Session = Depends(get_db),
                    user: User = Depends(require("suppression.manage"))):
    _accessible_project(db, project_id, user)
    if payload.channel not in ("email", "whatsapp", "sms"):
        raise HTTPException(status_code=400, detail="Invalid channel")
    contact = normalize_contact(payload.contact)
    if not contact:
        raise HTTPException(status_code=400, detail="Contact is required")
    existing = db.query(Suppression).filter_by(
        project_id=project_id, contact=contact, channel=payload.channel).first()
    if existing:
        return existing
    row = Suppression(project_id=project_id, contact=contact, channel=payload.channel,
                      reason=payload.reason or "manual")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{suppression_id}")
def remove_suppression(project_id: int, suppression_id: int, db: Session = Depends(get_db),
                       user: User = Depends(require("suppression.manage"))):
    _accessible_project(db, project_id, user)
    row = db.get(Suppression, suppression_id)
    if not row or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Suppression entry not found")
    db.delete(row)
    db.commit()
    return {"ok": True}
