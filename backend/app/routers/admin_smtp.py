"""Admin-level (workspace-default) SMTP configuration -- tier 3 of the
campaign email resolver (app/mailer.py::send_campaign_email), between a
project's own override and the hardcoded O365/Graph fallback. See
docs referenced in that resolver for the full tier order.

Reuses app/smtp_mailer.py for both the real send (send_email_smtp) and the
real connection check (test_smtp_connection) -- this module only supplies a
config source, not a second sending/verification implementation.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..crypto import encrypt_secret, decrypt_secret
from ..database import get_db
from ..deps import require
from ..models import SmtpSettings, User
from ..schemas import SmtpSettingsCreate, SmtpSettingsOut, SmtpSettingsUpdate, SendTestEmailIn
from ..smtp_mailer import send_email_smtp, test_smtp_connection, SmtpMailError

router = APIRouter(prefix="/api/admin/smtp-settings", tags=["admin-smtp"])


def _to_out(row: SmtpSettings) -> SmtpSettingsOut:
    out = SmtpSettingsOut.model_validate(row)
    out.has_password = bool(row.password)
    return out


def _get_or_404(db: Session, config_id: int) -> SmtpSettings:
    row = db.get(SmtpSettings, config_id)
    if not row:
        raise HTTPException(status_code=404, detail="SMTP configuration not found")
    return row


@router.get("", response_model=list[SmtpSettingsOut])
def list_configs(db: Session = Depends(get_db), _: User = Depends(require("system.configure"))):
    rows = db.query(SmtpSettings).order_by(SmtpSettings.id.desc()).all()
    return [_to_out(r) for r in rows]


@router.post("", response_model=SmtpSettingsOut)
def create_config(payload: SmtpSettingsCreate, db: Session = Depends(get_db),
                   _: User = Depends(require("system.configure"))):
    data = payload.model_dump()
    data["password"] = encrypt_secret(data["password"])
    row = SmtpSettings(**data)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.put("/{config_id}", response_model=SmtpSettingsOut)
def update_config(config_id: int, payload: SmtpSettingsUpdate, db: Session = Depends(get_db),
                   _: User = Depends(require("system.configure"))):
    row = _get_or_404(db, config_id)
    data = payload.model_dump(exclude_unset=True)
    # A blank password means "leave the saved one alone" -- same convention
    # as the project-level SMTP form (see app/routers/projects.py).
    if "password" in data:
        if data["password"]:
            data["password"] = encrypt_secret(data["password"])
        else:
            del data["password"]
    for k, v in data.items():
        setattr(row, k, v)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.post("/{config_id}/activate", response_model=SmtpSettingsOut)
def activate_config(config_id: int, db: Session = Depends(get_db),
                     _: User = Depends(require("system.configure"))):
    """Sets this row's is_active=true and every other row's is_active=false
    in one transaction. The DB also enforces "at most one active row" via a
    partial unique index, so a race or a direct API call can't leave two
    rows active even if this transaction were somehow bypassed."""
    row = _get_or_404(db, config_id)
    db.query(SmtpSettings).filter(SmtpSettings.id != config_id, SmtpSettings.is_active.is_(True)) \
        .update({"is_active": False})
    row.is_active = True
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.post("/{config_id}/test-connection")
def test_connection(config_id: int, db: Session = Depends(get_db),
                     _: User = Depends(require("system.configure"))):
    """Real smtplib connect + STARTTLS/SSL handshake + login, using the
    stored (decrypted server-side only) credentials. Never sends the
    password to the client."""
    row = _get_or_404(db, config_id)
    try:
        message = test_smtp_connection(
            row.smtp_host, row.smtp_port, row.encryption,
            row.username, decrypt_secret(row.password),
        )
    except SmtpMailError as e:
        row.last_tested_at = datetime.now(timezone.utc)
        row.last_test_status = "failed"
        db.commit()
        raise HTTPException(status_code=400, detail=str(e))
    row.last_tested_at = datetime.now(timezone.utc)
    row.last_test_status = "ok"
    db.commit()
    return {"ok": True, "message": message}


@router.post("/{config_id}/send-test-email")
def send_test_email(config_id: int, payload: SendTestEmailIn, db: Session = Depends(get_db),
                     _: User = Depends(require("system.configure"))):
    """Sends one real email via this config, independent of whether it's the
    active one -- so an admin can verify a config before activating it."""
    row = _get_or_404(db, config_id)
    try:
        pid = send_email_smtp(
            payload.to, "Reach — test email",
            "This is a test email from the Reach platform.\n\nIf you received this, this SMTP configuration works.",
            host=row.smtp_host, port=row.smtp_port, username=row.username,
            password=decrypt_secret(row.password), from_email=row.from_email,
            from_name=row.from_name, reply_to=row.reply_to, encryption=row.encryption,
        )
    except SmtpMailError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "provider_id": pid, "to": payload.to}
