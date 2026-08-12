import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..mailer import send_system_email, MailError
from ..models import PasswordResetToken, User
from ..security import hash_password, verify_password, create_access_token
from ..schemas import ForgotPasswordIn, MeOut, ResetPasswordIn, Token
from ..deps import get_current_user, user_permissions

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)


@router.post("/login", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # OAuth2 form uses "username" field; we treat it as email
    user = db.query(User).filter(User.email == form.username).first()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Account is deactivated")
    return Token(access_token=create_access_token(user.id))


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user)):
    out = MeOut.model_validate(user)
    out.permissions = sorted(user_permissions(user))
    out.project_ids = [p.id for p in user.projects]
    return out


_GENERIC_FORGOT_RESPONSE = {"ok": True, "detail": "If that email is registered, a password reset link has been sent."}


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordIn, db: Session = Depends(get_db)):
    """Always responds the same way whether or not the email is registered
    (or active) -- distinguishing the two would let this endpoint be used to
    enumerate real accounts."""
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not user.is_active:
        return _GENERIC_FORGOT_RESPONSE

    # Superseded by this one -- an old link from an earlier request must not
    # remain redeemable once a newer one has been issued.
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None),
    ).update({"used_at": datetime.now(timezone.utc)})

    token = secrets.token_urlsafe(32)
    db.add(PasswordResetToken(
        user_id=user.id, token=token,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.password_reset_token_ttl_minutes),
    ))
    db.commit()

    link = f"{settings.frontend_base_url.rstrip('/')}/reset-password?token={token}"
    body = (
        f"Hi {user.name},\n\n"
        f"Someone requested a password reset for your Reach account. This link is valid for "
        f"{settings.password_reset_token_ttl_minutes} minutes and can only be used once:\n\n{link}\n\n"
        "If you didn't request this, you can safely ignore this email."
    )
    try:
        send_system_email(db, user.email, "Reset your Reach password", body)
    except MailError as e:
        # The token is already stored -- surfacing this to the caller would
        # both leak "yes, that email exists" and expose mail-provider
        # internals, so it's logged for an admin to notice instead.
        logger.warning("forgot-password: failed to send reset email to user %s: %s", user.id, e)
    return _GENERIC_FORGOT_RESPONSE


@router.post("/reset-password")
def reset_password(payload: ResetPasswordIn, db: Session = Depends(get_db)):
    row = db.query(PasswordResetToken).filter_by(token=payload.token).first()
    if row is None or row.used_at is not None:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired. Request a new one.")
    now = datetime.now(timezone.utc)
    expires_at = row.expires_at if row.expires_at.tzinfo is not None else row.expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired. Request a new one.")
    if not payload.new_password or len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired. Request a new one.")

    user.hashed_password = hash_password(payload.new_password)
    row.used_at = now
    db.commit()
    return {"ok": True}
