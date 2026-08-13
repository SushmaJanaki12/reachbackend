from fastapi import APIRouter, Depends, HTTPException
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
    return q.order_by(Message.id.desc()).all()


@router.get("/campaigns/{campaign_id}/summary", response_model=SummaryOut)
def summary(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = _get_campaign(db, campaign_id, user)
    msgs = list(campaign.messages or [])
    recs = list(campaign.recipients or [])

    def count(channel, statuses):
        return sum(1 for m in msgs if m.channel == channel and m.status in statuses)

    sent_states = {"sent", "delivered", "read"}
    pending_states = {"pending", "queued", "processing"}

    total_recipients = len(recs)
    replied = sum(1 for r in recs if (r.reply_status or "") == "replied")
    not_replied = sum(1 for r in recs if (r.reply_status or "not_replied") != "replied")
    interested = sum(1 for r in recs if (r.interest_status or "") == "interested")
    not_interested = sum(1 for r in recs if (r.interest_status or "") == "not_interested")
    stopped = sum(1 for r in recs if bool(r.campaign_stopped))

    email_sent = count("email", sent_states)
    whatsapp_sent = count("whatsapp", sent_states)
    sms_sent = count("sms", sent_states)
    total_sent = sum(1 for m in msgs if m.status in sent_states)
    failed = sum(1 for m in msgs if m.status == "failed")
    queued = sum(1 for m in msgs if m.status == "queued")
    processing = sum(1 for m in msgs if m.status == "processing")
    pending = sum(1 for m in msgs if m.status in pending_states)
    delivered = sum(1 for m in msgs if m.status in {"delivered", "read"})
    suppressed = sum(1 for m in msgs if m.status == "suppressed")

    reply_rate = round((replied / total_recipients) * 100, 1) if total_recipients else 0.0
    send_rate = round((total_sent / len(msgs)) * 100, 1) if msgs else 0.0
    fail_rate = round((failed / len(msgs)) * 100, 1) if msgs else 0.0

    return SummaryOut(
        total_recipients=total_recipients,
        total_messages=len(msgs),
        email_sent=email_sent,
        whatsapp_sent=whatsapp_sent,
        sms_sent=sms_sent,
        delivered=delivered,
        failed=failed,
        pending=pending,
        suppressed=suppressed,
        status=campaign.status or "",
        replied=replied,
        not_replied=not_replied,
        interested=interested,
        not_interested=not_interested,
        stopped=stopped,
        queued=queued,
        processing=processing,
        total_sent=total_sent,
        reply_rate_pct=reply_rate,
        send_rate_pct=send_rate,
        fail_rate_pct=fail_rate,
    )


@router.get("/campaigns/{campaign_id}/report.csv")
def export_report(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    perms = user_permissions(user)
    if "report.export" not in perms:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    campaign = _get_campaign(db, campaign_id, user)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "Channel", "Recipient", "To", "Status", "Step", "Follow-up #",
        "Error", "Warnings", "Sent At", "Delivered At", "Read At",
    ])
    for m in sorted(campaign.messages, key=lambda x: (x.channel, x.id)):
        step = "Follow-up" if getattr(m, "is_followup", False) else "First touch"
        w.writerow([
            m.channel,
            m.recipient_name,
            m.to_address,
            m.status,
            step,
            getattr(m, "followup_number", 0) or 0,
            m.error,
            m.warnings,
            m.sent_at or "",
            m.delivered_at or "",
            m.read_at or "",
        ])
    # Engagement sheet-style second section
    w.writerow([])
    w.writerow(["--- Engagement ---"])
    w.writerow(["Name", "Email", "Mobile", "Reply", "Interest", "Stopped", "Follow-ups sent", "Next send"])
    for r in campaign.recipients or []:
        w.writerow([
            r.name, r.email, r.mobile,
            r.reply_status or "",
            r.interest_status or "",
            "yes" if r.campaign_stopped else "no",
            r.followup_count or 0,
            r.next_followup_at or "",
        ])
    buf.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="campaign_{campaign_id}_report.csv"'}
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers=headers)
