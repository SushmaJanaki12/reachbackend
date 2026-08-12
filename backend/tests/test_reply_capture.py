"""Real inbound-reply capture (P1.3): app/reply_capture.py's IMAP polling
logic, app/routers/reply_capture.py's admin config/control endpoints, and
worker.py's Reply-To alias wiring on real email sends.
"""
import imaplib
from email.message import EmailMessage as PyEmailMessage

import pytest

import app.reply_capture as reply_capture_mod
import app.worker as worker_mod
from app.crypto import decrypt_secret
from app.database import SessionLocal
from app.models import Message, ReplyCaptureSettings
from tests.conftest import make_campaign, drain_queue, upload_dataset

CSV = "Name,Email Address,Mobile Number\nAlice,alice@example.com,9876543210\n"


@pytest.fixture(autouse=True)
def _cleanup_reply_capture_settings():
    """Singleton, workspace-wide row (like SmtpSettings) -- every other test
    module's send-path tests implicitly assume this table is empty (no
    Reply-To override). Always start and end each test in this file clean."""
    db = SessionLocal()
    try:
        db.query(ReplyCaptureSettings).delete()
        db.commit()
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        db.query(ReplyCaptureSettings).delete()
        db.commit()
    finally:
        db.close()


def _payload(**overrides):
    payload = {
        "enabled": True, "mailbox_address": "replies@reach-tracking.com",
        "imap_host": "imap.example.com", "imap_port": 993, "imap_use_ssl": True,
        "imap_username": "replies@reach-tracking.com", "imap_password": "s3cret",
        "poll_folder": "INBOX", "poll_interval_seconds": 120,
    }
    payload.update(overrides)
    return payload


def _configure(client, admin_headers, **overrides):
    r = client.put("/api/admin/reply-capture", headers=admin_headers, json=_payload(**overrides))
    assert r.status_code == 200, r.text
    return r.json()


def _sent_message(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    upload_dataset(client, admin_headers, c["id"], CSV)
    client.put(f"/api/campaigns/{c['id']}/content/email", headers=admin_headers,
               json={"subject": "Hi {{Name}}", "body": "Hello {{Name}}"})
    client.put(f"/api/campaigns/{c['id']}", headers=admin_headers, json={"email_enabled": True})
    client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    drain_queue()
    db = SessionLocal()
    try:
        msg = db.query(Message).filter_by(campaign_id=c["id"]).one()
        return c, msg.id, msg.tracking_token
    finally:
        db.close()


# ---------- pure helpers ----------

def test_reply_to_alias_builds_plus_addressed_local_part():
    assert reply_capture_mod.reply_to_alias("replies@reach-tracking.com", "abc123") == "replies+abc123@reach-tracking.com"


def test_extract_token_from_header_with_display_name():
    header = 'Alice Reply <replies+abc123@reach-tracking.com>'
    assert reply_capture_mod._extract_token(header) == "abc123"


def test_extract_token_returns_none_without_plus_alias():
    assert reply_capture_mod._extract_token("someone@example.com") is None


# ---------- admin config CRUD ----------

def test_get_creates_default_row_and_hides_password(client, admin_headers):
    r = client.get("/api/admin/reply-capture", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert "imap_password" not in body
    assert body["has_password"] is False


def test_update_stores_encrypted_password_and_reports_has_password(client, admin_headers):
    row = _configure(client, admin_headers)
    assert "imap_password" not in row
    assert row["has_password"] is True
    assert row["enabled"] is True
    assert row["mailbox_address"] == "replies@reach-tracking.com"

    db = SessionLocal()
    try:
        stored = db.query(ReplyCaptureSettings).first()
        assert stored.imap_password != "s3cret"
        assert decrypt_secret(stored.imap_password) == "s3cret"
    finally:
        db.close()


def test_update_with_blank_password_preserves_existing(client, admin_headers):
    _configure(client, admin_headers)
    r = client.put("/api/admin/reply-capture", headers=admin_headers,
                    json={"imap_host": "imap2.example.com", "imap_password": ""})
    assert r.status_code == 200, r.text
    assert r.json()["imap_host"] == "imap2.example.com"

    db = SessionLocal()
    try:
        assert decrypt_secret(db.query(ReplyCaptureSettings).first().imap_password) == "s3cret"
    finally:
        db.close()


def test_non_admin_cannot_access_reply_capture_routes(client, user_headers):
    r = client.get("/api/admin/reply-capture", headers=user_headers)
    assert r.status_code == 403


# ---------- IMAP connection test / poll-now (mocked transport) ----------

class _FakeImapOK:
    def __init__(self, host, port):
        pass

    def login(self, user, password):
        return "OK", []

    def select(self, folder):
        return "OK", []

    def logout(self):
        return "OK", []


def test_test_connection_ok(client, admin_headers, monkeypatch):
    _configure(client, admin_headers)
    monkeypatch.setattr(imaplib, "IMAP4_SSL", _FakeImapOK)
    r = client.post("/api/admin/reply-capture/test-connection", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_test_connection_failure_reported(client, admin_headers, monkeypatch):
    _configure(client, admin_headers)

    class _FailingImap:
        def __init__(self, host, port):
            raise ConnectionRefusedError("nope")

    monkeypatch.setattr(imaplib, "IMAP4_SSL", _FailingImap)
    r = client.post("/api/admin/reply-capture/test-connection", headers=admin_headers)
    assert r.status_code == 400


def test_poll_now_rejected_when_not_configured(client, admin_headers):
    r = client.post("/api/admin/reply-capture/poll-now", headers=admin_headers)
    assert r.status_code == 400


# ---------- poll_inbox matching + follow-up integration (mocked transport) ----------

def _raw_email(to_alias: str, body: str) -> bytes:
    msg = PyEmailMessage()
    msg["From"] = "alice@example.com"
    msg["To"] = to_alias
    msg["Subject"] = "Re: Hi Alice"
    msg.set_content(body)
    return msg.as_bytes()


class _FakeImapWithMail:
    """Serves one fixed message (id b'1') on every SEARCH, regardless of
    host/port -- good enough to exercise poll_inbox's matching + \\Seen
    marking without a real mail server."""

    def __init__(self, host, port):
        pass

    def login(self, user, password):
        return "OK", []

    def select(self, folder):
        return "OK", []

    def search(self, charset, criteria):
        return "OK", [_FakeImapWithMail.pending]

    def fetch(self, num, spec):
        return "OK", [(b"1 (RFC822 {n})", _FakeImapWithMail.raw)]

    def store(self, num, flag, value):
        _FakeImapWithMail.seen_calls.append((num, flag, value))
        return "OK", []

    def logout(self):
        return "OK", []


def test_poll_inbox_matches_reply_and_records_engagement(client, admin_headers, project, monkeypatch):
    c, msg_id, token = _sent_message(client, admin_headers, project)
    _configure(client, admin_headers)

    _FakeImapWithMail.pending = b"1"
    _FakeImapWithMail.raw = _raw_email(f"replies+{token}@reach-tracking.com", "Yes, very interested!")
    _FakeImapWithMail.seen_calls = []
    monkeypatch.setattr(imaplib, "IMAP4_SSL", _FakeImapWithMail)

    r = client.post("/api/admin/reply-capture/poll-now", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"checked": 1, "matched": 1}
    assert _FakeImapWithMail.seen_calls == [(b"1", "+FLAGS", "\\Seen")]

    db = SessionLocal()
    try:
        msg = db.get(Message, msg_id)
        assert msg.replied_at is not None
        assert msg.reply_sentiment == "interested"
        assert "very interested" in msg.reply_text
        assert msg.engagement_source == "real"
    finally:
        db.close()

    settings_row = client.get("/api/admin/reply-capture", headers=admin_headers).json()
    assert settings_row["last_poll_status"] == "ok"


def test_poll_inbox_unmatched_token_is_a_harmless_no_op(client, admin_headers, project, monkeypatch):
    c, msg_id, token = _sent_message(client, admin_headers, project)
    _configure(client, admin_headers)

    _FakeImapWithMail.pending = b"1"
    _FakeImapWithMail.raw = _raw_email("replies+not-a-real-token@reach-tracking.com", "Hello")
    _FakeImapWithMail.seen_calls = []
    monkeypatch.setattr(imaplib, "IMAP4_SSL", _FakeImapWithMail)

    r = client.post("/api/admin/reply-capture/poll-now", headers=admin_headers)
    assert r.status_code == 200
    assert r.json() == {"checked": 1, "matched": 0}

    db = SessionLocal()
    try:
        assert db.get(Message, msg_id).replied_at is None
    finally:
        db.close()


def test_poll_failure_recorded_on_settings_row(client, admin_headers, monkeypatch):
    _configure(client, admin_headers)

    class _FailingImap:
        def __init__(self, host, port):
            raise TimeoutError("no route to host")

    monkeypatch.setattr(imaplib, "IMAP4_SSL", _FailingImap)
    r = client.post("/api/admin/reply-capture/poll-now", headers=admin_headers)
    assert r.status_code == 400

    settings_row = client.get("/api/admin/reply-capture", headers=admin_headers).json()
    assert settings_row["last_poll_status"] == "failed"
    assert "no route to host" in settings_row["last_poll_error"]


# ---------- worker.py wiring ----------

def test_real_send_sets_reply_to_alias_when_capture_enabled(client, admin_headers, project, monkeypatch):
    s = worker_mod.settings
    monkeypatch.setattr(s, "azure_tenant_id", "tenant")
    monkeypatch.setattr(s, "o365_client_id", "client")
    monkeypatch.setattr(s, "o365_client_secret", "secret")
    monkeypatch.setattr(s, "o365_from_email", "from@acme.com")

    calls = []
    monkeypatch.setattr(worker_mod, "send_campaign_email",
                        lambda project, to, subject, body, is_html=False, attachments=None, reply_to=None:
                            (calls.append(reply_to), "provider-id")[1])

    _configure(client, admin_headers)
    c, msg_id, token = _sent_message(client, admin_headers, project)

    assert calls == [f"replies+{token}@reach-tracking.com"]


def test_real_send_leaves_reply_to_unset_when_capture_disabled(client, admin_headers, project, monkeypatch):
    s = worker_mod.settings
    monkeypatch.setattr(s, "azure_tenant_id", "tenant")
    monkeypatch.setattr(s, "o365_client_id", "client")
    monkeypatch.setattr(s, "o365_client_secret", "secret")
    monkeypatch.setattr(s, "o365_from_email", "from@acme.com")

    calls = []
    monkeypatch.setattr(worker_mod, "send_campaign_email",
                        lambda project, to, subject, body, is_html=False, attachments=None, reply_to=None:
                            (calls.append(reply_to), "provider-id")[1])

    # reply capture left at its default (disabled, no row) -- unlike the
    # test above, no explicit _configure() call.
    c, msg_id, token = _sent_message(client, admin_headers, project)

    assert calls == [None]
