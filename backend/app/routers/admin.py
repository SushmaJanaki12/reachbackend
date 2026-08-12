"""Operational visibility into the send pipeline (P0.2): is the RQ worker
process actually alive, and is any campaign stuck in "sending" because it
isn't?

Nothing here writes to the queue/worker -- it only reads RQ's own worker
registry (Worker.all) and Redis queue state, plus Message/Campaign rows
already being written by the normal send path (see worker.py, campaigns.py).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from rq import Worker
from sqlalchemy.orm import Session

from ..campaign_utils import redis_conn, send_queue
from ..config import settings
from ..database import get_db
from ..deps import require
from ..models import Campaign, Message, User

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _oldest_job_age_seconds(now: datetime) -> float | None:
    job_ids = send_queue.job_ids
    if not job_ids:
        return None
    job = send_queue.fetch_job(job_ids[0])
    enqueued_at = _aware(job.enqueued_at) if job else None
    if enqueued_at is None:
        return None
    return (now - enqueued_at).total_seconds()


def _worker_summary(now: datetime) -> dict:
    workers = Worker.all(connection=redis_conn, queue=send_queue)
    heartbeats = [hb for w in workers if (hb := _aware(w.last_heartbeat)) is not None]
    last_heartbeat = max(heartbeats) if heartbeats else None
    stale = last_heartbeat is None or (now - last_heartbeat).total_seconds() > settings.worker_heartbeat_stale_seconds
    return {
        "worker_count": len(workers),
        "last_heartbeat": last_heartbeat.isoformat() if last_heartbeat else None,
        "healthy": bool(workers) and not stale,
        "workers": [
            {"name": w.name, "state": w.state, "last_heartbeat": (h.isoformat() if (h := _aware(w.last_heartbeat)) else None)}
            for w in workers
        ],
    }


def _stuck_campaigns(db: Session, now: datetime) -> list[dict]:
    threshold = settings.stuck_campaign_minutes * 60
    out = []
    for campaign in db.query(Campaign).filter(Campaign.status == "sending").all():
        sending_since = _aware(campaign.sending_since)
        if sending_since is None or (now - sending_since).total_seconds() < threshold:
            continue  # too young to call stuck regardless of activity
        last_activity = db.query(Message.updated_at).filter(
            Message.campaign_id == campaign.id).order_by(Message.updated_at.desc()).first()
        last_activity_at = _aware(last_activity[0]) if last_activity else sending_since
        if (now - last_activity_at).total_seconds() < threshold:
            continue  # still making progress, just a big/slow batch
        out.append({
            "id": campaign.id, "name": campaign.name,
            "sending_since": sending_since.isoformat(),
            "last_activity_at": last_activity_at.isoformat(),
            "minutes_stuck": round((now - last_activity_at).total_seconds() / 60, 1),
        })
    return out


@router.get("/queue-status")
def queue_status(db: Session = Depends(get_db), _: User = Depends(require("system.configure"))):
    now = datetime.now(timezone.utc)
    return {
        "queue_depth": send_queue.count,
        "oldest_job_age_seconds": _oldest_job_age_seconds(now),
        "stuck_campaigns": _stuck_campaigns(db, now),
        **_worker_summary(now),
    }
