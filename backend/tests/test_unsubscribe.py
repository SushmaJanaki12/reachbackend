"""Real unsubscribe link (P1.8, G12): every outbound email carries a
per-message unsubscribe footer (app/link_tracking.py, injected in
app/worker.py); GET /unsubscribe?token=... suppresses the contact and
future sends to them are blocked (reusing the suppression check
worker.py::process_message already runs on every send)."""
from app.database import SessionLocal
from app.models import Message, Suppression
from tests.conftest import make_campaign, drain_queue, upload_dataset

CSV = "Name,Email Address,Mobile Number\nAlice,alice@example.com,9876543210\n"


def _sent_message(client, admin_headers, project, body="Hello {{Name}}, thanks for signing up."):
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


def test_email_body_contains_unsubscribe_link():
    from app.link_tracking import to_html_with_tracking
    html = to_html_with_tracking("Hello there.", "sometoken123")
    assert "/unsubscribe?token=sometoken123" in html
    assert "Unsubscribe" in html


def test_unsubscribe_suppresses_contact(client, admin_headers, project):
    c, msg_id, token = _sent_message(client, admin_headers, project)

    r = client.get("/unsubscribe", params={"token": token})
    assert r.status_code == 200
    assert "unsubscribed" in r.text.lower()

    db = SessionLocal()
    try:
        sup = db.query(Suppression).filter_by(
            project_id=project["id"], contact="alice@example.com", channel="email").first()
        assert sup is not None
        assert sup.reason == "unsubscribed"
    finally:
        db.close()


def test_unsubscribe_is_idempotent(client, admin_headers, project):
    c, msg_id, token = _sent_message(client, admin_headers, project)

    client.get("/unsubscribe", params={"token": token})
    r2 = client.get("/unsubscribe", params={"token": token})
    assert r2.status_code == 200

    db = SessionLocal()
    try:
        count = db.query(Suppression).filter_by(
            project_id=project["id"], contact="alice@example.com", channel="email").count()
        assert count == 1  # not duplicated
    finally:
        db.close()


def test_unsubscribe_unknown_token_returns_404_page(client):
    r = client.get("/unsubscribe", params={"token": "not-a-real-token"})
    assert r.status_code == 404
    assert "not recognized" in r.text.lower() or "invalid" in r.text.lower()


def test_unsubscribed_contact_blocks_future_sends(client, admin_headers, project):
    """The whole point -- reuses the existing suppression check every send
    already runs (worker.py::process_message), same as SEC3 for manual
    suppression entries."""
    c1, msg_id, token = _sent_message(client, admin_headers, project)
    client.get("/unsubscribe", params={"token": token})

    c2 = make_campaign(client, admin_headers, project["id"], name="Second")
    upload_dataset(client, admin_headers, c2["id"], CSV)
    client.put(f"/api/campaigns/{c2['id']}/content/email", headers=admin_headers,
               json={"subject": "Hi {{Name}}", "body": "Another message"})
    client.put(f"/api/campaigns/{c2['id']}", headers=admin_headers, json={"email_enabled": True})
    client.post(f"/api/campaigns/{c2['id']}/send", headers=admin_headers)
    drain_queue()

    db = SessionLocal()
    try:
        second_msg = db.query(Message).filter_by(campaign_id=c2["id"]).one()
        assert second_msg.status == "suppressed"
    finally:
        db.close()
