"""Admin-level (workspace-default) SMTP configuration -- Part 2 of the SMTP
fix/spec: app/routers/admin_smtp.py, app/models.py::SmtpSettings, and the
tier-3 slot it occupies in app/mailer.py::send_campaign_email, between a
project's own override (tier 2) and the hardcoded O365/Graph fallback
(tier 4, unchanged).
"""
import smtplib

import pytest

from app.crypto import decrypt_secret
from app.database import SessionLocal
from app.models import Message, SmtpSettings
from tests.conftest import make_campaign, drain_queue

CSV = "Name,Email Address,Mobile Number\nAlice,alice@example.com,9876543210\n"


@pytest.fixture(autouse=True)
def _cleanup_smtp_settings():
    """This table holds at most one *globally* active row, which every other
    test module's campaign-send tests implicitly assume is empty (they
    expect either the workspace O365 sender or simulated dispatch). Leaving
    a row behind here would silently change their behavior. Always start
    and end each test in this file with the table empty."""
    db = SessionLocal()
    try:
        db.query(SmtpSettings).delete()
        db.commit()
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        db.query(SmtpSettings).delete()
        db.commit()
    finally:
        db.close()


def _payload(**overrides):
    payload = {
        "provider": "custom", "smtp_host": "smtp.workspace.com", "smtp_port": 587,
        "encryption": "starttls", "username": "wsuser", "password": "wspass",
        "from_email": "noreply@workspace.com", "from_name": "Workspace",
        "reply_to": "support@workspace.com", "max_per_minute": 0,
    }
    payload.update(overrides)
    return payload


def _create(client, admin_headers, **overrides):
    r = client.post("/api/admin/smtp-settings", headers=admin_headers, json=_payload(**overrides))
    assert r.status_code == 200, r.text
    return r.json()


class _FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.login_args = host, port, None
        _FakeSMTP.instances.append(self)

    def ehlo(self):
        pass

    def starttls(self, context=None):
        pass

    def login(self, username, password):
        self.login_args = (username, password)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _reset_fake_smtp(monkeypatch):
    _FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    return _FakeSMTP.instances


# ---------- CRUD + security ----------

def test_create_hides_password_but_reports_has_password(client, admin_headers):
    row = _create(client, admin_headers)
    assert "password" not in row
    assert row["has_password"] is True
    assert row["from_email"] == "noreply@workspace.com"
    assert row["is_active"] is False

    db = SessionLocal()
    try:
        stored = db.get(SmtpSettings, row["id"]).password
        assert stored != "wspass"
        assert decrypt_secret(stored) == "wspass"
    finally:
        db.close()


def test_list_never_includes_password_field(client, admin_headers):
    _create(client, admin_headers)
    r = client.get("/api/admin/smtp-settings", headers=admin_headers)
    assert r.status_code == 200
    assert len(r.json()) >= 1
    for row in r.json():
        assert "password" not in row


def test_update_with_blank_password_preserves_existing(client, admin_headers):
    row = _create(client, admin_headers)
    r = client.put(f"/api/admin/smtp-settings/{row['id']}", headers=admin_headers,
                   json={"smtp_host": "smtp2.workspace.com", "password": ""})
    assert r.status_code == 200, r.text
    assert r.json()["smtp_host"] == "smtp2.workspace.com"

    db = SessionLocal()
    try:
        assert decrypt_secret(db.get(SmtpSettings, row["id"]).password) == "wspass"
    finally:
        db.close()


def test_update_with_nonblank_password_overwrites(client, admin_headers):
    row = _create(client, admin_headers)
    client.put(f"/api/admin/smtp-settings/{row['id']}", headers=admin_headers, json={"password": "newpass"})

    db = SessionLocal()
    try:
        assert decrypt_secret(db.get(SmtpSettings, row["id"]).password) == "newpass"
    finally:
        db.close()


def test_non_admin_cannot_access_admin_smtp_routes(client, user_headers):
    r = client.get("/api/admin/smtp-settings", headers=user_headers)
    assert r.status_code == 403

    r = client.post("/api/admin/smtp-settings", headers=user_headers, json=_payload())
    assert r.status_code == 403


# ---------- activation ----------

def test_activate_deactivates_other_rows(client, admin_headers):
    a = _create(client, admin_headers, smtp_host="a.smtp.com")
    b = _create(client, admin_headers, smtp_host="b.smtp.com")

    r = client.post(f"/api/admin/smtp-settings/{a['id']}/activate", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["is_active"] is True

    r = client.post(f"/api/admin/smtp-settings/{b['id']}/activate", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["is_active"] is True

    listed = {row["id"]: row["is_active"] for row in client.get("/api/admin/smtp-settings", headers=admin_headers).json()}
    assert listed[a["id"]] is False
    assert listed[b["id"]] is True


# ---------- test-connection / send-test-email ----------

def test_test_connection_success_records_status(client, admin_headers, monkeypatch):
    _reset_fake_smtp(monkeypatch)
    row = _create(client, admin_headers)
    r = client.post(f"/api/admin/smtp-settings/{row['id']}/test-connection", headers=admin_headers)
    assert r.status_code == 200, r.text

    updated = client.get("/api/admin/smtp-settings", headers=admin_headers).json()[0]
    assert updated["last_test_status"] == "ok"
    assert updated["last_tested_at"] is not None


def test_test_connection_failure_records_status_and_returns_400(client, admin_headers, monkeypatch):
    class _AuthFailSMTP(_FakeSMTP):
        def login(self, username, password):
            raise smtplib.SMTPAuthenticationError(535, b"bad creds")
    monkeypatch.setattr(smtplib, "SMTP", _AuthFailSMTP)

    row = _create(client, admin_headers)
    r = client.post(f"/api/admin/smtp-settings/{row['id']}/test-connection", headers=admin_headers)
    assert r.status_code == 400
    assert "Authentication failed" in r.json()["detail"]

    updated = client.get("/api/admin/smtp-settings", headers=admin_headers).json()[0]
    assert updated["last_test_status"] == "failed"


def test_send_test_email_uses_smtp_mailer_with_decrypted_password(client, admin_headers, monkeypatch):
    calls = []

    def fake_send_email_smtp(to_email, subject, body, **kw):
        calls.append((to_email, kw))
        return "wsmtp-id"

    import app.smtp_mailer as smtp_mailer_mod
    import app.routers.admin_smtp as admin_smtp_mod
    monkeypatch.setattr(smtp_mailer_mod, "send_email_smtp", fake_send_email_smtp)
    monkeypatch.setattr(admin_smtp_mod, "send_email_smtp", fake_send_email_smtp)

    row = _create(client, admin_headers)
    r = client.post(f"/api/admin/smtp-settings/{row['id']}/send-test-email", headers=admin_headers,
                    json={"to": "someone@example.com"})
    assert r.status_code == 200, r.text
    assert len(calls) == 1
    to_email, kw = calls[0]
    assert to_email == "someone@example.com"
    assert kw["password"] == "wspass"
    assert kw["host"] == "smtp.workspace.com"


# ---------- resolver tier 3: admin-active SMTP used by campaign sends ----------

def _ready_campaign(client, admin_headers, project_id):
    c = make_campaign(client, admin_headers, project_id)
    client.post(f"/api/campaigns/{c['id']}/dataset", headers=admin_headers,
               files={"file": ("data.csv", CSV, "text/csv")})
    client.put(f"/api/campaigns/{c['id']}/content/email", headers=admin_headers,
              json={"subject": "Hi {{Name}}", "body": "Hello {{Name}}"})
    client.put(f"/api/campaigns/{c['id']}", headers=admin_headers, json={"email_enabled": True})
    return c


def test_campaign_send_uses_active_admin_smtp_when_no_project_override(client, admin_headers, project, monkeypatch):
    row = _create(client, admin_headers)
    client.post(f"/api/admin/smtp-settings/{row['id']}/activate", headers=admin_headers)

    calls = []

    def fake_send_email_smtp(to_email, subject, body, **kw):
        calls.append((to_email, kw))
        return "admin-smtp-id"

    import app.smtp_mailer as smtp_mailer_mod
    monkeypatch.setattr(smtp_mailer_mod, "send_email_smtp", fake_send_email_smtp)

    from app.config import settings
    assert not settings.email_configured

    c = _ready_campaign(client, admin_headers, project["id"])
    client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    drain_queue()

    assert len(calls) == 1
    to_email, kw = calls[0]
    assert to_email == "alice@example.com"
    assert kw["host"] == "smtp.workspace.com"
    assert kw["password"] == "wspass"  # decrypted before dispatch

    db = SessionLocal()
    try:
        msg = db.query(Message).filter_by(campaign_id=c["id"]).first()
        assert msg.status == "sent"
        assert msg.provider_id == "admin-smtp-id"
    finally:
        db.close()


def test_project_smtp_takes_precedence_over_active_admin_smtp(client, admin_headers, project, monkeypatch):
    admin_row = _create(client, admin_headers, smtp_host="admin.smtp.com")
    client.post(f"/api/admin/smtp-settings/{admin_row['id']}/activate", headers=admin_headers)

    client.put(f"/api/projects/{project['id']}", headers=admin_headers, json={
        "smtp_enabled": True, "smtp_host": "project.smtp.com", "smtp_port": 587,
        "smtp_encryption": "starttls", "smtp_username": "u", "smtp_password": "s3cret",
        "smtp_from_name": "Acme", "smtp_from_email": "noreply@acme.com",
    })

    calls = []

    def fake_send_email_smtp(to_email, subject, body, **kw):
        calls.append(kw)
        return "some-id"

    import app.smtp_mailer as smtp_mailer_mod
    monkeypatch.setattr(smtp_mailer_mod, "send_email_smtp", fake_send_email_smtp)

    c = _ready_campaign(client, admin_headers, project["id"])
    client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    drain_queue()

    assert len(calls) == 1
    assert calls[0]["host"] == "project.smtp.com"  # project override wins over admin-active


def test_project_smtp_failure_with_fallback_falls_through_to_admin_smtp(client, admin_headers, project, monkeypatch):
    admin_row = _create(client, admin_headers, smtp_host="admin.smtp.com")
    client.post(f"/api/admin/smtp-settings/{admin_row['id']}/activate", headers=admin_headers)

    client.put(f"/api/projects/{project['id']}", headers=admin_headers, json={
        "smtp_enabled": True, "smtp_host": "project.smtp.com", "smtp_port": 587,
        "smtp_encryption": "starttls", "smtp_username": "u", "smtp_password": "s3cret",
        "smtp_from_name": "Acme", "smtp_from_email": "noreply@acme.com",
        "smtp_fallback_on_failure": True,
    })

    import app.smtp_mailer as smtp_mailer_mod
    from app.smtp_mailer import SmtpMailError

    calls = []

    def fake_send_email_smtp(to_email, subject, body, **kw):
        if kw["host"] == "project.smtp.com":
            raise SmtpMailError("project smtp down")
        calls.append(kw)
        return "admin-fallback-id"

    monkeypatch.setattr(smtp_mailer_mod, "send_email_smtp", fake_send_email_smtp)

    c = _ready_campaign(client, admin_headers, project["id"])
    client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    drain_queue()

    assert len(calls) == 1
    assert calls[0]["host"] == "admin.smtp.com"

    db = SessionLocal()
    try:
        msg = db.query(Message).filter_by(campaign_id=c["id"]).first()
        assert msg.status == "sent"
        assert msg.provider_id == "admin-fallback-id"
    finally:
        db.close()


# ---------- Review & Send label (channels status) ----------

def test_channels_status_label_reflects_active_admin_smtp(client, admin_headers, project):
    row = _create(client, admin_headers, smtp_host="labeltest.smtp.com")
    client.post(f"/api/admin/smtp-settings/{row['id']}/activate", headers=admin_headers)

    r = client.get(f"/api/channels/status?project_id={project['id']}", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["email"]["live"] is True
    assert body["email"]["provider"] == "admin SMTP (labeltest.smtp.com)"


def test_channels_status_label_prefers_project_smtp_over_admin_smtp(client, admin_headers, project):
    row = _create(client, admin_headers, smtp_host="labeltest.smtp.com")
    client.post(f"/api/admin/smtp-settings/{row['id']}/activate", headers=admin_headers)

    client.put(f"/api/projects/{project['id']}", headers=admin_headers, json={
        "smtp_enabled": True, "smtp_host": "project-label.smtp.com", "smtp_port": 587,
        "smtp_encryption": "starttls", "smtp_username": "u", "smtp_password": "s3cret",
        "smtp_from_name": "Acme", "smtp_from_email": "noreply@acme.com",
    })

    r = client.get(f"/api/channels/status?project_id={project['id']}", headers=admin_headers)
    body = r.json()
    assert body["email"]["provider"] == "project SMTP (project-label.smtp.com)"
