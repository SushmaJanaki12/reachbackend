"""Admin config + manual controls for real inbound-reply capture (P1.3).
See app/reply_capture.py for the IMAP polling logic this wraps.
"""
import imaplib

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..crypto import encrypt_secret, decrypt_secret
from ..database import get_db
from ..deps import require
from ..models import ReplyCaptureSettings, User
from ..reply_capture import poll_once
from ..schemas import ReplyCaptureSettingsOut, ReplyCaptureSettingsUpdate

router = APIRouter(prefix="/api/admin/reply-capture", tags=["admin-reply-capture"])


def _get_or_create(db: Session) -> ReplyCaptureSettings:
    row = db.query(ReplyCaptureSettings).first()
    if row is None:
        row = ReplyCaptureSettings()
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _to_out(row: ReplyCaptureSettings) -> ReplyCaptureSettingsOut:
    out = ReplyCaptureSettingsOut.model_validate(row)
    out.has_password = bool(row.imap_password)
    return out


@router.get("", response_model=ReplyCaptureSettingsOut)
def get_settings(db: Session = Depends(get_db), _: User = Depends(require("system.configure"))):
    return _to_out(_get_or_create(db))


@router.put("", response_model=ReplyCaptureSettingsOut)
def update_settings(payload: ReplyCaptureSettingsUpdate, db: Session = Depends(get_db),
                     _: User = Depends(require("system.configure"))):
    row = _get_or_create(db)
    data = payload.model_dump(exclude_unset=True)
    # A blank password means "leave the saved one alone" -- same convention
    # as the project/admin SMTP forms (app/routers/projects.py, admin_smtp.py).
    if "imap_password" in data:
        if data["imap_password"]:
            data["imap_password"] = encrypt_secret(data["imap_password"])
        else:
            del data["imap_password"]
    for k, v in data.items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.post("/test-connection")
def test_connection(db: Session = Depends(get_db), _: User = Depends(require("system.configure"))):
    """Real IMAP connect + login + folder select, using the stored
    (decrypted server-side only) credentials. Never sends the password to
    the client."""
    row = _get_or_create(db)
    if not row.imap_host or not row.imap_username:
        raise HTTPException(status_code=400, detail="IMAP host and username are required")
    imap_cls = imaplib.IMAP4_SSL if row.imap_use_ssl else imaplib.IMAP4
    try:
        conn = imap_cls(row.imap_host, row.imap_port)
        try:
            conn.login(row.imap_username, decrypt_secret(row.imap_password))
            conn.select(row.poll_folder or "INBOX")
        finally:
            conn.logout()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"IMAP connection failed: {e}")
    return {"ok": True}


@router.post("/poll-now")
def poll_now(_: User = Depends(require("system.configure"))):
    """Runs one poll cycle synchronously -- lets an admin verify reply
    capture end to end without waiting for the periodic background poll
    (see app/worker.py's self-rescheduling job)."""
    stats = poll_once()
    if stats is None:
        raise HTTPException(
            status_code=400,
            detail="Reply capture is not enabled/configured, or the last poll failed -- "
                   "check GET /api/admin/reply-capture for last_poll_error",
        )
    return stats
