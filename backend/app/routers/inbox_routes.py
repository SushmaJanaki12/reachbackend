"""Inbox + WhatsApp-style activity thread + Graph reply sync."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..deps import get_current_user, user_permissions
from ..database import get_db
from ..models import Campaign, Message, Project, Recipient, User

router = APIRouter(prefix="/api", tags=["inbox"])


class InboxItem(BaseModel):
    recipient_id: int
    campaign_id: int
    campaign_name: str
    name: str
    email: str
    mobile: str
    reply_status: str
    interest_status: str
    campaign_stopped: bool
    followup_count: int
    message_count: int
    last_activity_at: str | None
    needs_attention: bool


class ThreadEvent(BaseModel):
    id: str
    direction: str
    channel: str
    subject: str = ""
    body: str = ""
    status: str = ""
    at: str | None = None
    is_followup: bool = False
    followup_number: int = 0


class ThreadOut(BaseModel):
    recipient_id: int
    campaign_id: int
    campaign_name: str
    name: str
    email: str
    mobile: str
    reply_status: str
    interest_status: str
    campaign_stopped: bool
    followup_count: int
    events: list[ThreadEvent]


class LogReplyIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    channel: str = "email"


def _campaign_ok(db: Session, campaign_id: int, user: User) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    project = db.get(Project, campaign.project_id)
    perms = user_permissions(user)
    if "tracking.view_all" not in perms and "campaign.view" not in perms and "tracking.view_own" not in perms:
        if not project or project.owner_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
    return campaign


def _iso(dt) -> str | None:
    if not dt:
        return None
    return dt.isoformat()


@router.get("/inbox", response_model=list[InboxItem])
def list_inbox(
    project_id: int | None = Query(None),
    campaign_id: int | None = Query(None),
    only_replied: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Recipient).join(Campaign)
    if campaign_id:
        q = q.filter(Recipient.campaign_id == campaign_id)
    if project_id:
        q = q.filter(Campaign.project_id == project_id)
    if only_replied:
        q = q.filter(Recipient.reply_status == "replied")

    items: list[InboxItem] = []
    for rec in q.order_by(Recipient.id.desc()).limit(300).all():
        camp = rec.campaign
        msgs = [m for m in (camp.messages or []) if m.recipient_id == rec.id]
        last = None
        for m in msgs:
            for cand in (m.read_at, m.delivered_at, m.sent_at):
                if cand and (last is None or cand > last):
                    last = cand
        notes = (rec.data or {}).get("chat_log") or []
        interest = rec.interest_status or ""
        needs = rec.reply_status == "replied" and interest in ("", "none")
        items.append(
            InboxItem(
                recipient_id=rec.id,
                campaign_id=camp.id,
                campaign_name=camp.name or "",
                name=rec.name or "",
                email=rec.email or "",
                mobile=rec.mobile or "",
                reply_status=rec.reply_status or "not_replied",
                interest_status=interest,
                campaign_stopped=bool(rec.campaign_stopped),
                followup_count=rec.followup_count or 0,
                message_count=len(msgs) + len(notes),
                last_activity_at=_iso(last),
                needs_attention=bool(needs),
            )
        )
    items.sort(key=lambda x: (0 if x.needs_attention else 1, x.name or ""))
    return items


@router.get("/recipients/{recipient_id}/thread", response_model=ThreadOut)
def recipient_thread(
    recipient_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rec = db.get(Recipient, recipient_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recipient not found")
    camp = _campaign_ok(db, rec.campaign_id, user)
    events: list[ThreadEvent] = []
    for m in sorted([x for x in (camp.messages or []) if x.recipient_id == rec.id], key=lambda x: x.id):
        at = m.sent_at or m.delivered_at or m.read_at
        if getattr(m, "is_followup", False):
            step = f"Follow-up {getattr(m, 'followup_number', '') or ''}".strip()
        else:
            step = "First touch"
        body = f"{step} · {m.channel} · {m.status}"
        if m.error:
            body += f"\n{m.error[:120]}"
        events.append(
            ThreadEvent(
                id=f"msg-{m.id}",
                direction="out",
                channel=m.channel or "email",
                body=body,
                status=m.status or "",
                at=_iso(at),
                is_followup=bool(getattr(m, "is_followup", False)),
                followup_number=int(getattr(m, "followup_number", 0) or 0),
            )
        )
    for i, n in enumerate((rec.data or {}).get("chat_log") or []):
        events.append(
            ThreadEvent(
                id=f"note-{i}",
                direction=n.get("direction") or "in",
                channel=n.get("channel") or "email",
                subject=n.get("subject") or "",
                body=n.get("text") or n.get("body") or "",
                status="logged",
                at=n.get("at"),
            )
        )
    events.sort(key=lambda e: e.at or "")
    return ThreadOut(
        recipient_id=rec.id,
        campaign_id=camp.id,
        campaign_name=camp.name or "",
        name=rec.name or "",
        email=rec.email or "",
        mobile=rec.mobile or "",
        reply_status=rec.reply_status or "not_replied",
        interest_status=rec.interest_status or "",
        campaign_stopped=bool(rec.campaign_stopped),
        followup_count=rec.followup_count or 0,
        events=events,
    )


@router.post("/recipients/{recipient_id}/thread/reply")
def log_inbound_reply(
    recipient_id: int,
    payload: LogReplyIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rec = db.get(Recipient, recipient_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recipient not found")
    _campaign_ok(db, rec.campaign_id, user)
    data = dict(rec.data or {})
    log = list(data.get("chat_log") or [])
    log.append({
        "direction": "in",
        "channel": (payload.channel or "email").lower(),
        "text": payload.text.strip(),
        "at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"),
        "source": "manual",
    })
    data["chat_log"] = log
    rec.data = data
    rec.reply_status = "replied"
    rec.next_followup_at = None
    db.commit()
    return {"ok": True}


@router.post("/campaigns/{campaign_id}/sync-replies")
def sync_campaign_replies(
    campaign_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Pull real replies from the Office 365 mailbox into the chat thread."""
    _campaign_ok(db, campaign_id, user)
    from ..reply_sync import sync_replies_for_campaign
    result = sync_replies_for_campaign(db, campaign_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Sync failed")
    return result
