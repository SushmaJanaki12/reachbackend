from app.database import SessionLocal
from app.models import Message
from tests.conftest import make_campaign, drain_queue, upload_dataset

CSV = "Name,Email Address,Mobile Number\nAlice,alice@example.com,9876543210\n"


def _sent_message(client, admin_headers, project, body="Hello {{Name}}, visit https://example.com/promo today."):
    c = make_campaign(client, admin_headers, project["id"])
    upload_dataset(client, admin_headers, c["id"], CSV)
    client.put(f"/api/campaigns/{c['id']}/content/email", headers=admin_headers,
               json={"subject": "Hi {{Name}}", "body": body})
    client.put(f"/api/campaigns/{c['id']}", headers=admin_headers, json={"email_enabled": True})
    client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    drain_queue()
    db = SessionLocal()
    try:
        msg = db.query(Message).filter_by(campaign_id=c["id"]).one()
        return c, msg.id, msg.tracking_token
    finally:
        db.close()


def test_open_pixel_sets_opened_at_with_real_source(client, admin_headers, project):
    c, msg_id, token = _sent_message(client, admin_headers, project)

    r = client.get(f"/track/open/{token}.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert "no-store" in r.headers["cache-control"]

    db = SessionLocal()
    try:
        msg = db.get(Message, msg_id)
        assert msg.opened_at is not None
        assert msg.engagement_source == "real"
    finally:
        db.close()


def test_open_pixel_first_open_wins(client, admin_headers, project):
    """A repeat pixel fetch (image proxies/prefetch, multiple opens) must not
    move the timestamp forward -- first open wins, same semantics Simulate
    already guarantees."""
    c, msg_id, token = _sent_message(client, admin_headers, project)

    client.get(f"/track/open/{token}.png")
    db = SessionLocal()
    try:
        first_opened_at = db.get(Message, msg_id).opened_at
    finally:
        db.close()

    client.get(f"/track/open/{token}.png")
    db = SessionLocal()
    try:
        assert db.get(Message, msg_id).opened_at == first_opened_at
    finally:
        db.close()


def test_open_pixel_unknown_token_still_returns_image(client):
    """A stale/forged token must never surface as a broken image."""
    r = client.get("/track/open/not-a-real-token.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"


def test_click_redirect_sets_clicked_and_opened_then_redirects(client, admin_headers, project):
    c, msg_id, token = _sent_message(client, admin_headers, project)

    r = client.get(f"/track/click/{token}", params={"url": "https://example.com/promo"}, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "https://example.com/promo"

    db = SessionLocal()
    try:
        msg = db.get(Message, msg_id)
        assert msg.clicked_at is not None
        assert msg.opened_at is not None  # a click implies an open
        assert msg.engagement_source == "real"
    finally:
        db.close()


def test_click_redirect_rejects_url_off_allowlist(client, admin_headers, project):
    c, msg_id, token = _sent_message(client, admin_headers, project)

    r = client.get(f"/track/click/{token}", params={"url": "https://evil.example/phish"}, follow_redirects=False)
    assert r.status_code == 400

    db = SessionLocal()
    try:
        assert db.get(Message, msg_id).clicked_at is None
    finally:
        db.close()


def test_click_redirect_unknown_token_rejected(client):
    r = client.get("/track/click/not-a-real-token", params={"url": "https://example.com/promo"},
                    follow_redirects=False)
    assert r.status_code == 404


def test_real_open_feeds_into_step_performance_rollup(client, admin_headers, project):
    """The same real pixel hit that sets opened_at must show up in the
    Follow-ups Performance rollup (P1.4) exactly like the Simulate-driven
    version already does -- both read the same Message rows, filtered only
    on engagement_source == 'simulated', which 'real' is not."""
    c = make_campaign(client, admin_headers, project["id"])
    upload_dataset(client, admin_headers, c["id"], CSV)
    client.put(f"/api/campaigns/{c['id']}/content/email", headers=admin_headers,
               json={"subject": "Hi {{Name}}", "body": "Hello {{Name}}"})
    client.put(f"/api/campaigns/{c['id']}", headers=admin_headers, json={"email_enabled": True})
    step = client.post(f"/api/campaigns/{c['id']}/followups/steps", headers=admin_headers, json={
        "trigger_type": "not_opened", "delay_value": 0, "delay_unit": "hours",
        "primary_channel": "email", "subject": "Reminder", "body_template": "Hi {{Name}}",
    }).json()

    client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    drain_queue()  # original blast -- also enqueues the (0-delay) follow-up step
    drain_queue()  # the follow-up step's own send

    db = SessionLocal()
    try:
        followup = db.query(Message).filter(Message.campaign_id == c["id"], Message.step_id == step["id"]).one()
        token = followup.tracking_token
    finally:
        db.close()

    client.get(f"/track/open/{token}.png")

    steps = client.get(f"/api/campaigns/{c['id']}/followups/steps", headers=admin_headers).json()
    stats = next(s for s in steps if s["id"] == step["id"])["stats"]
    assert stats["sent"] == 1
    assert stats["open_rate"] == 100.0

    # And Tracking & Reports (the deep-link target from the Performance
    # column) shows the exact same row/state -- both views read the same
    # Message rows, so there's nothing for them to disagree about.
    tracking_rows = client.get(f"/api/campaigns/{c['id']}/tracking/email", headers=admin_headers).json()
    tracked = next(r for r in tracking_rows if r["id"] == followup.id)
    assert tracked["opened_at"] is not None
    assert tracked["engagement_source"] == "real"
