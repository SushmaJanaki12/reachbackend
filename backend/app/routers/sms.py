from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import User, SmsTemplate
from ..schemas import SmsTemplateIn, SmsTemplateOut, SmsValidateIn, SmsValidateOut
from ..deps import require, get_current_user
from ..sms import send_sms, matches_template, SmsError

router = APIRouter(prefix="/api/sms", tags=["sms"])

MANAGE = require("project.configure_channels", "system.configure")


class TestIn(BaseModel):
    to: str
    message: str = "Test SMS from the Reach platform."


@router.get("/status")
def status(_: User = Depends(get_current_user)):
    return {
        "configured": settings.sms_configured,
        "sender": settings.sms_from or None,
        "template_id": settings.sms_template_id or None,
    }


@router.post("/test")
def test(payload: TestIn, _: User = Depends(MANAGE)):
    if not settings.sms_configured:
        raise HTTPException(status_code=400, detail="SMS gateway is not configured")
    try:
        resp = send_sms(payload.to, payload.message)
        return {"ok": True, "response": resp, "to": payload.to}
    except SmsError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------- DLT templates ----------------
@router.get("/templates", response_model=list[SmsTemplateOut])
def list_templates(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(SmsTemplate).order_by(SmsTemplate.id).all()


@router.post("/templates", response_model=SmsTemplateOut)
def create_template(payload: SmsTemplateIn, db: Session = Depends(get_db), _: User = Depends(MANAGE)):
    tpl = SmsTemplate(**payload.model_dump())
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl


@router.put("/templates/{tpl_id}", response_model=SmsTemplateOut)
def update_template(tpl_id: int, payload: SmsTemplateIn, db: Session = Depends(get_db), _: User = Depends(MANAGE)):
    tpl = db.get(SmsTemplate, tpl_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    for k, v in payload.model_dump().items():
        setattr(tpl, k, v)
    db.commit()
    db.refresh(tpl)
    return tpl


@router.delete("/templates/{tpl_id}")
def delete_template(tpl_id: int, db: Session = Depends(get_db), _: User = Depends(MANAGE)):
    tpl = db.get(SmsTemplate, tpl_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    db.delete(tpl)
    db.commit()
    return {"ok": True}


@router.post("/validate", response_model=SmsValidateOut)
def validate(payload: SmsValidateIn, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    tpl = db.get(SmsTemplate, payload.template_ref)
    if not tpl:
        return SmsValidateOut(valid=False, reason="Template not found")
    if matches_template(tpl.body, payload.message):
        return SmsValidateOut(valid=True, reason="Matches the registered DLT template")
    return SmsValidateOut(valid=False, reason="Message text does not match the registered template (only variables may differ)")
