from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
import csv
import io

from ..database import get_db
from ..models import Campaign, Message, MessageHistory, Project, User
from ..schemas import MessageOut, SendRunOut, SummaryOut
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


def _rows_for_run(db: Session, campaign: Campaign, run: str) -> list:
    """Resolves the `?run=` query param used by /tracking, /summary and
    /report.csv into the actual Message/MessageHistory rows to show (P0.5:
    a resend archives the prior send's rows into MessageHistory rather than
    deleting them, so the live `messages` table alone only ever reflects the
    *current* run -- "current"/omitted is the default and needs no history
    lookup at all)."""
    if run in ("current", str(campaign.current_send_run)):
        return db.query(Message).filter_by(campaign_id=campaign.id).order_by(Message.id).all()
    if run == "all":
        historical = (
            db.query(MessageHistory).filter_by(campaign_id=campaign.id)
            .order_by(MessageHistory.sent_run_number, MessageHistory.id).all()
        )
        current = db.query(Message).filter_by(campaign_id=campaign.id).order_by(Message.id).all()
        return [*historical, *current]
    try:
        run_number = int(run)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run")
    return (
        db.query(MessageHistory).filter_by(campaign_id=campaign.id, sent_run_number=run_number)
        .order_by(MessageHistory.id).all()
    )


def _to_message_out(row) -> MessageOut:
    # MessageHistory ids live in their own sequence from Message's -- negate
    # them so a mixed ("all") result can never collide two rows onto the same
    # `id` (the frontend keys table rows on it).
    is_hist = isinstance(row, MessageHistory)
    return MessageOut(
        id=-row.id if is_hist else row.id, channel=row.channel, recipient_name=row.recipient_name,
        to_address=row.to_address, status=row.status, error=row.error, warnings=row.warnings,
        sent_at=row.sent_at, delivered_at=row.delivered_at, read_at=row.read_at, step_id=row.step_id,
        opened_at=row.opened_at, clicked_at=row.clicked_at, replied_at=row.replied_at,
        reply_sentiment=row.reply_sentiment, engagement_source=row.engagement_source,
    )


@router.get("/campaigns/{campaign_id}/tracking/{channel}", response_model=list[MessageOut])
def tracking(campaign_id: int, channel: str, run: str = "current",
             db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = _get_campaign(db, campaign_id, user)
    rows = _rows_for_run(db, campaign, run)
    if channel != "all":
        rows = [r for r in rows if r.channel == channel]
    return [_to_message_out(r) for r in rows]


@router.get("/campaigns/{campaign_id}/send-runs", response_model=list[SendRunOut])
def list_send_runs(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Every send this campaign has had, oldest first -- backs the run
    selector on Tracking & Reports. A campaign that's never been resent has
    exactly one entry (the current, and only, run)."""
    campaign = _get_campaign(db, campaign_id, user)
    runs: dict[int, dict] = {}

    current_count = db.query(Message).filter_by(campaign_id=campaign.id).count()
    if current_count:
        first_sent = db.query(func.min(Message.sent_at)).filter_by(campaign_id=campaign.id).scalar()
        runs[campaign.current_send_run] = {"message_count": current_count, "first_sent_at": first_sent}

    hist = (
        db.query(MessageHistory.sent_run_number, func.count(MessageHistory.id), func.min(MessageHistory.sent_at))
        .filter_by(campaign_id=campaign.id).group_by(MessageHistory.sent_run_number).all()
    )
    for run_number, count, first_sent in hist:
        runs[run_number] = {"message_count": count, "first_sent_at": first_sent}

    return [
        SendRunOut(run_number=n, is_current=(n == campaign.current_send_run),
                   message_count=d["message_count"], first_sent_at=d["first_sent_at"])
        for n, d in sorted(runs.items())
    ]


@router.get("/campaigns/{campaign_id}/summary", response_model=SummaryOut)
def summary(campaign_id: int, run: str = "current",
            db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = _get_campaign(db, campaign_id, user)
    msgs = _rows_for_run(db, campaign, run)

    def count(channel, statuses):
        return sum(1 for m in msgs if m.channel == channel and m.status in statuses)

    sent_states = {"sent", "delivered", "read"}
    return SummaryOut(
        total_recipients=len({m.recipient_id for m in msgs}),
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
def export_report(campaign_id: int, run: str = "current",
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    perms = user_permissions(user)
    if "report.export" not in perms:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    campaign = _get_campaign(db, campaign_id, user)
    msgs = _rows_for_run(db, campaign, run)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Channel", "Recipient", "To", "Status", "Error", "Warnings", "Sent At", "Delivered At", "Read At"])
    for m in sorted(msgs, key=lambda x: (x.channel, x.id)):
        w.writerow([m.channel, m.recipient_name, m.to_address, m.status, m.error, m.warnings,
                    m.sent_at or "", m.delivered_at or "", m.read_at or ""])
    buf.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="campaign_{campaign_id}_report.csv"'}
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers=headers)
