from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, Role, Project
from ..schemas import UserOut, UserCreate, UserUpdate
from ..security import hash_password
from ..deps import require

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require("user.manage"))):
    return db.query(User).order_by(User.id).all()


@router.post("", response_model=UserOut)
def create_user(payload: UserCreate, db: Session = Depends(get_db), _: User = Depends(require("user.manage"))):
    if db.query(User).filter_by(email=payload.email).first():
        raise HTTPException(status_code=400, detail="Email already in use")
    if not db.get(Role, payload.role_id):
        raise HTTPException(status_code=400, detail="Invalid role")
    user = User(
        name=payload.name, email=payload.email,
        hashed_password=hash_password(payload.password),
        role_id=payload.role_id, is_active=True,
    )
    if payload.project_ids:
        user.projects = db.query(Project).filter(Project.id.in_(payload.project_ids)).all()
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.put("/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db), _: User = Depends(require("user.manage"))):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.name is not None:
        user.name = payload.name
    if payload.role_id is not None:
        user.role_id = payload.role_id
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password:
        user.hashed_password = hash_password(payload.password)
    if payload.project_ids is not None:
        user.projects = db.query(Project).filter(Project.id.in_(payload.project_ids)).all()
    db.commit()
    db.refresh(user)
    return user
