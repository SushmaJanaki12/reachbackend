from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import csv
import io

from ..database import get_db
from ..models import Campaign, Message, Project, User
from ..schemas import MessageOut, SummaryOut
from ..deps import get_current_user, user_permissions

router = APIRouter(prefix="/api", tags=["tracking"])


def _get_campaign(db: Session, campaign_id: int, user: User) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    project: Project = campaign.project
    perms = user_permissions(user)
    see_all = "user.manage" in perms or "system.configure" in perms
    if not see_all and project.id not in {p.id for p in user.projects}:
        raise HTTPException(status_code=403, detail="No access to this campaign")
    return campaign


@router.get("/campaigns/{campaign_id}/tracking/{channel}", response_model=list[MessageOut])
def tracking(campaign_id: int, channel: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = _get_campaign(db, campaign_id, user)
    q = db.query(Message).filter_by(campaign_id=campaign.id)
    if channel != "all":
        q = q.filter_by(channel=channel)
    return q.order_by(Message.id).all()


@router.get("/campaigns/{campaign_id}/summary", response_model=SummaryOut)
def summary(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = _get_campaign(db, campaign_id, user)
    msgs = campaign.messages

    def count(channel, statuses):
        return sum(1 for m in msgs if m.channel == channel and m.status in statuses)

    sent_states = {"sent", "delivered", "read"}
    return SummaryOut(
        total_recipients=len(campaign.recipients),
        total_messages=len(msgs),
        email_sent=count("email", sent_states),
        whatsapp_sent=count("whatsapp", sent_states),
        sms_sent=count("sms", sent_states),
        delivered=sum(1 for m in msgs if m.status in {"delivered", "read"}),
        failed=sum(1 for m in msgs if m.status == "failed"),
        pending=sum(1 for m in msgs if m.status == "pending"),
        suppressed=sum(1 for m in msgs if m.status == "suppressed"),
        status=campaign.status,
    )


@router.get("/campaigns/{campaign_id}/report.csv")
def export_report(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    perms = user_permissions(user)
    if "report.export" not in perms:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    campaign = _get_campaign(db, campaign_id, user)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Channel", "Recipient", "To", "Status", "Error", "Warnings", "Sent At", "Delivered At", "Read At"])
    for m in sorted(campaign.messages, key=lambda x: (x.channel, x.id)):
        w.writerow([m.channel, m.recipient_name, m.to_address, m.status, m.error, m.warnings,
                    m.sent_at or "", m.delivered_at or "", m.read_at or ""])
    buf.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="campaign_{campaign_id}_report.csv"'}
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers=headers)
