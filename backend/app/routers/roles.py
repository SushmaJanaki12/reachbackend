from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Role, Permission, User
from ..schemas import RoleOut, RoleIn, PermissionOut
from ..deps import require, get_current_user

router = APIRouter(prefix="/api", tags=["roles"])


@router.get("/permissions", response_model=list[PermissionOut])
def list_permissions(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Permission).order_by(Permission.module, Permission.id).all()


@router.get("/roles", response_model=list[RoleOut])
def list_roles(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Role).order_by(Role.id).all()


@router.post("/roles", response_model=RoleOut)
def create_role(payload: RoleIn, db: Session = Depends(get_db), _: User = Depends(require("role.manage"))):
    if db.query(Role).filter_by(name=payload.name).first():
        raise HTTPException(status_code=400, detail="Role name already exists")
    role = Role(name=payload.name, description=payload.description)
    role.permissions = db.query(Permission).filter(Permission.code.in_(payload.permission_codes)).all()
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


@router.put("/roles/{role_id}", response_model=RoleOut)
def update_role(role_id: int, payload: RoleIn, db: Session = Depends(get_db), _: User = Depends(require("role.manage"))):
    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.name == "Admin":
        raise HTTPException(status_code=400, detail="The Admin role cannot be modified")
    role.description = payload.description
    role.permissions = db.query(Permission).filter(Permission.code.in_(payload.permission_codes)).all()
    db.commit()
    db.refresh(role)
    return role


@router.delete("/roles/{role_id}")
def delete_role(role_id: int, db: Session = Depends(get_db), _: User = Depends(require("role.manage"))):
    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system:
        raise HTTPException(status_code=400, detail="System roles cannot be deleted")
    user_count = db.query(User).filter_by(role_id=role.id).count()
    if user_count:
        raise HTTPException(
            status_code=400,
            detail=f"{user_count} user{'s' if user_count != 1 else ''} still {'have' if user_count != 1 else 'has'} this role. Reassign them before deleting.",
        )
    db.delete(role)
    db.commit()
    return {"ok": True}
