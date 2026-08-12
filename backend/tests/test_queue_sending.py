import time
from concurrent.futures import ThreadPoolExecutor

import app.worker as worker_mod
from app.config import settings
from app.database import SessionLocal
from app.models import Campaign, Message
from tests.conftest import make_campaign, drain_queue, upload_dataset

CSV = (
    "Name,Email Address,Mobile Number\n"
    "Alice,alice@example.com,9876543210\n"
    "Bob,bob@example.com,9123456789\n"
)


def _upload(client, headers, cid, csv=CSV):
    return upload_dataset(client, headers, cid, csv)


def _ready_campaign(client, admin_headers, project, csv=CSV):
    c = make_campaign(client, admin_headers, project["id"])
    _upload(client, admin_headers, c["id"], csv)
    client.put(f"/api/campaigns/{c['id']}/content/email", headers=admin_headers,
              json={"subject": "Hi {{Name}}", "body": "Hello {{Name}}"})
    client.put(f"/api/campaigns/{c['id']}", headers=admin_headers, json={"email_enabled": True})
    return c


def _configure_real_email(monkeypatch):
    s = worker_mod.settings
    monkeypatch.setattr(s, "azure_tenant_id", "tenant")
    monkeypatch.setattr(s, "o365_client_id", "client")
    monkeypatch.setattr(s, "o365_client_secret", "secret")
    monkeypatch.setattr(s, "o365_from_email", "from@acme.com")
    calls = []
    monkeypatch.setattr(worker_mod, "send_campaign_email",
                        lambda project, to, subject, body, is_html=False, attachments=None, reply_to=None:
                            (calls.append(to), "provider-id")[1])
    return calls


def test_send_enqueues_without_blocking_on_provider(client, admin_headers, project, monkeypatch):
    calls = _configure_real_email(monkeypatch)
    c = _ready_campaign(client, admin_headers, project)

    send = client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    assert send.status_code == 200
    assert send.json()["status"] == "sending"
    # The provider must not have been called yet -- sending only enqueued jobs.
    assert calls == []

    rows = client.get(f"/api/campaigns/{c['id']}/recipients", headers=admin_headers).json()
    assert len(rows) == 2
    db = SessionLocal()
    try:
        msgs = db.query(Message).filter_by(campaign_id=c["id"]).all()
        assert len(msgs) == 2
        assert all(m.status == "queued" for m in msgs)
    finally:
        db.close()


def test_worker_resumes_after_crash_without_reprocessing(client, admin_headers, project, monkeypatch):
    calls = _configure_real_email(monkeypatch)
    c = _ready_campaign(client, admin_headers, project)
    client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)

    db = SessionLocal()
    try:
        msgs = db.query(Message).filter_by(campaign_id=c["id"]).order_by(Message.id).all()
        assert len(msgs) == 2
        first_id, second_id = msgs[0].id, msgs[1].id
    finally:
        db.close()

    # Simulate one worker cycle that only gets through the first job before "crashing".
    worker_mod.process_message(first_id)
    assert len(calls) == 1

    db = SessionLocal()
    try:
        first = db.get(Message, first_id)
        second = db.get(Message, second_id)
        assert first.status == "sent"
        assert second.status == "queued"  # untouched by the crash
    finally:
        db.close()

    # A fresh worker run picks up where it left off: only the still-queued job runs.
    worker_mod.process_message(second_id)
    assert len(calls) == 2

    db = SessionLocal()
    try:
        second = db.get(Message, second_id)
        assert second.status == "sent"
    finally:
        db.close()


def test_redelivered_job_does_not_doublesend(client, admin_headers, project, monkeypatch):
    calls = _configure_real_email(monkeypatch)
    c = _ready_campaign(client, admin_headers, project)
    client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)

    db = SessionLocal()
    try:
        msg_id = db.query(Message).filter_by(campaign_id=c["id"]).first().id
    finally:
        db.close()

    worker_mod.process_message(msg_id)
    assert len(calls) == 1

    # Queue redelivers the same job (e.g. after a visibility timeout) -- must be a no-op.
    worker_mod.process_message(msg_id)
    worker_mod.process_message(msg_id)
    assert len(calls) == 1


def test_rate_limiting_throttles_sends(client, admin_headers, project, monkeypatch):
    s = worker_mod.settings
    monkeypatch.setattr(s, "azure_tenant_id", "tenant")
    monkeypatch.setattr(s, "o365_client_id", "client")
    monkeypatch.setattr(s, "o365_client_secret", "secret")
    monkeypatch.setattr(s, "o365_from_email", "from@acme.com")
    monkeypatch.setattr(s, "email_rate_per_second", 2)

    calls = []
    monkeypatch.setattr(worker_mod, "send_campaign_email",
                        lambda project, to, subject, body, is_html=False, attachments=None, reply_to=None:
                            (calls.append(to), "provider-id")[1])

    csv = "Name,Email Address,Mobile Number\n" + "".join(
        f"P{i},p{i}@example.com,90000000{i:02d}\n" for i in range(4)
    )
    c = _ready_campaign(client, admin_headers, project, csv=csv)

    client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)

    started = time.monotonic()
    drain_queue()
    elapsed = time.monotonic() - started

    assert len(calls) == 4
    # At 2/sec, 4 sends can't complete near-instantly -- proves throttling ran.
    assert elapsed >= 0.4


def test_concurrent_completion_only_fires_once(client, admin_headers, project):
    """Two workers that both finish the campaign's last message at the same
    instant must not both trigger completion side effects. Old code did
    read-then-write (both threads could read status=="sending" before
    either commits its own write); the fix is a conditional
    `UPDATE ... WHERE status='sending'`, so only whichever call's UPDATE
    actually flips the row gets True back -- see worker._maybe_complete_campaign."""
    c = make_campaign(client, admin_headers, project["id"])
    db = SessionLocal()
    try:
        campaign = db.get(Campaign, c["id"])
        campaign.status = "sending"
        db.commit()
    finally:
        db.close()

    def _attempt(_):
        db = SessionLocal()
        try:
            return worker_mod._maybe_complete_campaign(db, c["id"])
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(_attempt, range(2)))

    assert sorted(results) == [False, True]

    db = SessionLocal()
    try:
        assert db.get(Campaign, c["id"]).status == "completed"
    finally:
        db.close()


def test_redis_queue_uses_dedicated_test_db():
    """Root cause of the 'stuck in queued forever' bug: REDIS_URL had no
    test/dev separation the way DATABASE_URL does (reach vs reach_test).
    conftest's autouse _isolated_queue fixture empties the 'sends' queue
    before/after every test -- against the default DB 0, that silently wiped
    out real in-flight campaign jobs any time pytest ran, leaving their
    Message rows stuck at 'queued' in Postgres with nothing left in Redis to
    ever process them. Guard against the isolation regressing."""
    assert settings.redis_url != "redis://localhost:6379/0"
    assert settings.redis_url.startswith("redis://localhost:6379/")

    from redis import Redis
    prod_conn = Redis.from_url("redis://localhost:6379/0")
    prod_conn.rpush("canary:not-a-test-key", "should-survive-test-runs")
    try:
        # Run something that would previously have shared -- and wiped -- this
        # connection's queue if test isolation regressed.
        from tests.conftest import drain_queue as _drain
        _drain()
        assert prod_conn.lrange("canary:not-a-test-key", 0, -1) == [b"should-survive-test-runs"]
    finally:
        prod_conn.delete("canary:not-a-test-key")
