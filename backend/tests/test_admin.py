from datetime import datetime, timedelta, timezone

from rq import Worker
from rq.utils import utcformat

from app.campaign_utils import redis_conn, send_queue
from app.config import settings
from app.database import SessionLocal
from app.models import Campaign, Message
from tests.conftest import make_campaign, drain_queue, upload_dataset

CSV = "Name,Email Address,Mobile Number\nAlice,alice@example.com,9876543210\n"


def _ready_campaign(client, headers, project):
    c = make_campaign(client, headers, project["id"])
    upload_dataset(client, headers, c["id"], CSV)
    client.put(f"/api/campaigns/{c['id']}/content/email", headers=headers,
               json={"subject": "Hi {{Name}}", "body": "Hello {{Name}}"})
    client.put(f"/api/campaigns/{c['id']}", headers=headers, json={"email_enabled": True})
    return c


def test_queue_status_forbidden_for_non_admin(client, user_headers):
    r = client.get("/api/admin/queue-status", headers=user_headers)
    assert r.status_code == 403


def test_queue_status_no_worker_reports_unhealthy(client, admin_headers):
    r = client.get("/api/admin/queue-status", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["worker_count"] == 0
    assert body["healthy"] is False
    assert body["last_heartbeat"] is None


def test_queue_status_healthy_with_live_worker(client, admin_headers):
    worker = Worker([send_queue], connection=redis_conn)
    worker.register_birth()
    try:
        r = client.get("/api/admin/queue-status", headers=admin_headers)
        body = r.json()
        assert body["worker_count"] == 1
        assert body["healthy"] is True
        assert body["last_heartbeat"] is not None
    finally:
        worker.register_death()


def test_queue_status_stale_heartbeat_reports_unhealthy(client, admin_headers):
    """A worker whose process died without deregistering (e.g. killed -9)
    stays in RQ's registry until its TTL lapses (~7 min by default) -- the
    'worker not responding' signal must come from heartbeat freshness, not
    mere registry presence, or Settings would stay silent for minutes."""
    worker = Worker([send_queue], connection=redis_conn)
    worker.register_birth()
    try:
        stale = datetime.now(timezone.utc) - timedelta(seconds=settings.worker_heartbeat_stale_seconds + 30)
        redis_conn.hset(worker.key, "last_heartbeat", utcformat(stale))

        r = client.get("/api/admin/queue-status", headers=admin_headers)
        body = r.json()
        assert body["worker_count"] == 1  # still registered...
        assert body["healthy"] is False   # ...but not responding
    finally:
        worker.register_death()


def test_queue_status_reflects_queue_depth_and_oldest_job_age(client, admin_headers, project):
    c = _ready_campaign(client, admin_headers, project)
    send = client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    assert send.status_code == 200
    try:
        r = client.get("/api/admin/queue-status", headers=admin_headers)
        body = r.json()
        assert body["queue_depth"] >= 1
        assert body["oldest_job_age_seconds"] is not None
        assert body["oldest_job_age_seconds"] >= 0
    finally:
        drain_queue()  # don't leak an unprocessed job into later tests


def test_stuck_campaign_flagged_after_threshold_with_no_activity(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    db = SessionLocal()
    try:
        campaign = db.get(Campaign, c["id"])
        campaign.status = "sending"
        campaign.sending_since = datetime.now(timezone.utc) - timedelta(
            minutes=settings.stuck_campaign_minutes + 5)
        db.commit()
    finally:
        db.close()

    r = client.get("/api/admin/queue-status", headers=admin_headers)
    stuck_ids = [s["id"] for s in r.json()["stuck_campaigns"]]
    assert c["id"] in stuck_ids


def test_recently_started_send_not_flagged_stuck(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    db = SessionLocal()
    try:
        campaign = db.get(Campaign, c["id"])
        campaign.status = "sending"
        campaign.sending_since = datetime.now(timezone.utc)  # just started
        db.commit()
    finally:
        db.close()

    r = client.get("/api/admin/queue-status", headers=admin_headers)
    stuck_ids = [s["id"] for s in r.json()["stuck_campaigns"]]
    assert c["id"] not in stuck_ids


def test_stuck_campaign_not_flagged_with_recent_message_activity(client, admin_headers, project):
    """An old, slow-but-still-moving campaign (recent Message.updated_at)
    must not be flagged just because it's taken a long time overall."""
    c = _ready_campaign(client, admin_headers, project)
    send = client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    assert send.status_code == 200
    drain_queue()

    db = SessionLocal()
    try:
        campaign = db.get(Campaign, c["id"])
        campaign.status = "sending"  # force back to sending after drain completed it
        campaign.sending_since = datetime.now(timezone.utc) - timedelta(
            minutes=settings.stuck_campaign_minutes + 5)
        db.commit()
    finally:
        db.close()

    r = client.get("/api/admin/queue-status", headers=admin_headers)
    stuck_ids = [s["id"] for s in r.json()["stuck_campaigns"]]
    # Message rows were touched by drain_queue() moments ago -- well within
    # the stuck-campaign window -- so this must not be flagged.
    assert c["id"] not in stuck_ids
