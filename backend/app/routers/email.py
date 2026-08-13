from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from ..config import settings
from ..models import User
from ..deps import require, get_current_user
from ..mailer import verify_connection, send_email, MailError

router = APIRouter(prefix="/api/email", tags=["email"])


class TestIn(BaseModel):
    to: EmailStr


@router.get("/status")
def status(_: User = Depends(get_current_user)):
    return {
        "configured": settings.email_configured,
        "provider": "Office 365 (Microsoft Graph)" if settings.email_configured else None,
        "from_email": settings.o365_from_email or None,
    }


@router.post("/verify")
def verify(_: User = Depends(require("project.configure_channels", "system.configure"))):
    if not settings.email_configured:
        raise HTTPException(status_code=400, detail="Office 365 email is not configured")
    try:
        return verify_connection()
    except MailError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/test")
def test(payload: TestIn, _: User = Depends(require("project.configure_channels", "system.configure"))):
    if not settings.email_configured:
        raise HTTPException(status_code=400, detail="Office 365 email is not configured")
    try:
        pid = send_email(payload.to, "Reach — test email",
                         "This is a test email from the Reach platform.\n\nIf you received this, Office 365 sending works.")
        return {"ok": True, "provider_id": pid, "to": payload.to}
    except MailError as e:
        raise HTTPException(status_code=400, detail=str(e))
