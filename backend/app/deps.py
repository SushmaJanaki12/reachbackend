from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    sub = decode_token(token)
    if sub is None:
        raise cred_exc
    user = db.get(User, int(sub))
    if user is None or not user.is_active:
        raise cred_exc
    return user


def user_permissions(user: User) -> set[str]:
    return {p.code for p in user.role.permissions}


def require(*codes: str):
    """Dependency factory: require the user to hold at least one of the given permission codes."""
    def checker(user: User = Depends(get_current_user)) -> User:
        perms = user_permissions(user)
        if not any(c in perms for c in codes):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return checker
