from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Project, Campaign, Recipient, Message, User
from ..deps import get_current_user, user_permissions

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

SUCCESS = {"sent", "delivered", "read"}


@router.get("/overview")
def overview(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    perms = user_permissions(user)
    see_all = "user.manage" in perms or "system.configure" in perms

    if see_all:
        projects = db.query(Project).order_by(Project.id.desc()).all()
    else:
        projects = sorted(user.projects, key=lambda p: p.id, reverse=True)
    pids = [p.id for p in projects]

    # Test campaigns carry only fabricated (Simulate-driven) engagement data --
    # excluded here so it never inflates the real cross-campaign analytics
    # shown on this dashboard (see routers/followups.py::simulate_event).
    campaigns = (db.query(Campaign)
                 .filter(Campaign.project_id.in_(pids), Campaign.is_test_campaign.is_(False)).all()
                 if pids else [])
    cids = [c.id for c in campaigns]

    # recipients per campaign
    rc = {}
    if cids:
        rows = (db.query(Recipient.campaign_id, func.count(Recipient.id))
                .filter(Recipient.campaign_id.in_(cids)).group_by(Recipient.campaign_id).all())
        rc = {cid: n for cid, n in rows}
    recipients_total = sum(rc.values())

    # messages
    msgs = []
    if cids:
        msgs = db.query(Message.channel, Message.status).filter(Message.campaign_id.in_(cids)).all()

    by_channel = {"email": 0, "whatsapp": 0, "sms": 0}
    delivery = {"success": 0, "failed": 0, "pending": 0}
    for channel, status in msgs:
        if status in SUCCESS:
            by_channel[channel] = by_channel.get(channel, 0) + 1
            delivery["success"] += 1
        elif status == "failed":
            delivery["failed"] += 1
        else:
            delivery["pending"] += 1

    # campaign status split
    camp_status = {"draft": 0, "active": 0, "sending": 0, "completed": 0}
    camp_by_project = {}
    for c in campaigns:
        camp_status[c.status] = camp_status.get(c.status, 0) + 1
        camp_by_project[c.project_id] = camp_by_project.get(c.project_id, 0) + 1

    total_messages = len(msgs)
    success_rate = round(delivery["success"] / total_messages * 100) if total_messages else 0

    recent_projects = [{
        "id": p.id, "name": p.name, "email": p.email, "status": p.status,
        "campaign_count": camp_by_project.get(p.id, 0),
    } for p in projects[:6]]

    top_campaigns = sorted(campaigns, key=lambda c: rc.get(c.id, 0), reverse=True)[:5]
    pname = {p.id: p.name for p in projects}
    top_campaigns = [{
        "id": c.id, "name": c.name, "project": pname.get(c.project_id, ""),
        "recipients": rc.get(c.id, 0), "status": c.status,
    } for c in top_campaigns if rc.get(c.id, 0) > 0]

    return {
        "totals": {
            "projects": len(projects),
            "projects_active": sum(1 for p in projects if p.status == "active"),
            "campaigns": len(campaigns),
            "recipients": recipients_total,
            "messages": total_messages,
            "messages_sent": delivery["success"],
            "success_rate": success_rate,
        },
        "campaign_status": camp_status,
        "by_channel": by_channel,
        "delivery": delivery,
        "recent_projects": recent_projects,
        "top_campaigns": top_campaigns,
    }
