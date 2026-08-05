"""Project-level SMTP: saving/persisting settings, the smtp-test endpoint,
and the actual campaign send path -- this is the feature area covered by the
"project SMTP settings are ignored" bug fix (app/mailer.py::send_campaign_email,
app/smtp_mailer.py, app/routers/projects.py).
"""
import smtplib

from app.crypto import decrypt_secret
from app.database import SessionLocal
from app.models import Message, Project
from tests.conftest import make_campaign, drain_queue, upload_dataset

CSV = "Name,Email Address,Mobile Number\nAlice,alice@example.com,9876543210\n"


def _smtp_payload(**overrides):
    payload = {
        "smtp_enabled": True, "smtp_host": "smtp.acme.com", "smtp_port": 587,
        "smtp_encryption": "starttls", "smtp_username": "u", "smtp_password": "s3cret",
        "smtp_from_name": "Acme", "smtp_from_email": "noreply@acme.com",
        "smtp_reply_to": "support@acme.com", "smtp_fallback_on_failure": False,
        "smtp_max_per_minute": 0,
    }
    payload.update(overrides)
    return payload


def _project_smtp_password(project_id):
    db = SessionLocal()
    try:
        return db.get(Project, project_id).smtp_password
    finally:
        db.close()


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


def test_save_smtp_settings_encrypts_password_and_hides_it_from_api(client, admin_headers, project):
    r = client.put(f"/api/projects/{project['id']}", headers=admin_headers, json=_smtp_payload())
    assert r.status_code == 200, r.text
    body = r.json()
    assert "smtp_password" not in body
    assert body["smtp_enabled"] is True
    assert body["smtp_from_email"] == "noreply@acme.com"

    stored = _project_smtp_password(project["id"])
    assert stored != "s3cret"  # not plaintext at rest
    assert decrypt_secret(stored) == "s3cret"


def test_blank_password_on_update_preserves_existing(client, admin_headers, project):
    client.put(f"/api/projects/{project['id']}", headers=admin_headers, json=_smtp_payload())
    assert decrypt_secret(_project_smtp_password(project["id"])) == "s3cret"

    r = client.put(f"/api/projects/{project['id']}", headers=admin_headers,
                   json=_smtp_payload(smtp_password="", smtp_host="smtp2.acme.com"))
    assert r.status_code == 200, r.text
    assert r.json()["smtp_host"] == "smtp2.acme.com"
    assert decrypt_secret(_project_smtp_password(project["id"])) == "s3cret"


def test_nonblank_password_on_update_overwrites(client, admin_headers, project):
    client.put(f"/api/projects/{project['id']}", headers=admin_headers, json=_smtp_payload())
    client.put(f"/api/projects/{project['id']}", headers=admin_headers,
               json=_smtp_payload(smtp_password="newpass"))
    assert decrypt_secret(_project_smtp_password(project["id"])) == "newpass"


def test_smtp_test_endpoint_success_records_status(client, admin_headers, project, monkeypatch):
    _reset_fake_smtp(monkeypatch)
    r = client.post(f"/api/projects/{project['id']}/smtp-test", headers=admin_headers, json={
        "smtp_host": "smtp.acme.com", "smtp_port": 587, "smtp_encryption": "starttls",
        "smtp_username": "u", "smtp_password": "s3cret",
    })
    assert r.status_code == 200, r.text
    got = client.get(f"/api/projects/{project['id']}", headers=admin_headers).json()
    assert got["smtp_last_test_status"] == "ok"
    assert got["smtp_last_tested_at"] is not None


def test_smtp_test_endpoint_failure_records_status_and_returns_400(client, admin_headers, project, monkeypatch):
    class _AuthFailSMTP(_FakeSMTP):
        def login(self, username, password):
            raise smtplib.SMTPAuthenticationError(535, b"bad creds")
    monkeypatch.setattr(smtplib, "SMTP", _AuthFailSMTP)

    r = client.post(f"/api/projects/{project['id']}/smtp-test", headers=admin_headers, json={
        "smtp_host": "smtp.acme.com", "smtp_port": 587, "smtp_encryption": "starttls",
        "smtp_username": "u", "smtp_password": "wrong",
    })
    assert r.status_code == 400
    assert "Authentication failed" in r.json()["detail"]

    got = client.get(f"/api/projects/{project['id']}", headers=admin_headers).json()
    assert got["smtp_last_test_status"] == "failed"


def test_smtp_test_reuses_saved_password_when_payload_blank(client, admin_headers, project, monkeypatch):
    client.put(f"/api/projects/{project['id']}", headers=admin_headers, json=_smtp_payload())
    instances = _reset_fake_smtp(monkeypatch)

    r = client.post(f"/api/projects/{project['id']}/smtp-test", headers=admin_headers, json={
        "smtp_host": "smtp.acme.com", "smtp_port": 587, "smtp_encryption": "starttls",
        "smtp_username": "u", "smtp_password": "",
    })
    assert r.status_code == 200, r.text
    assert instances[0].login_args == ("u", "s3cret")


def _ready_campaign(client, admin_headers, project_id):
    c = make_campaign(client, admin_headers, project_id)
    upload_dataset(client, admin_headers, c['id'], CSV)
    client.put(f"/api/campaigns/{c['id']}/content/email", headers=admin_headers,
              json={"subject": "Hi {{Name}}", "body": "Hello {{Name}}"})
    client.put(f"/api/campaigns/{c['id']}", headers=admin_headers, json={"email_enabled": True})
    return c


def test_campaign_send_uses_project_smtp_even_without_o365_configured(client, admin_headers, project, monkeypatch):
    """Root cause of the ticket: with no workspace O365 configured, campaign
    email used to just simulate a "sent" status instead of trying the
    project's own SMTP settings. It must now actually attempt (and here,
    succeed) the SMTP send."""
    client.put(f"/api/projects/{project['id']}", headers=admin_headers, json=_smtp_payload())

    calls = []

    def fake_send_email_smtp(to_email, subject, body, **kw):
        calls.append((to_email, subject, body, kw))
        return "smtp-provider-id"

    import app.smtp_mailer as smtp_mailer_mod
    monkeypatch.setattr(smtp_mailer_mod, "send_email_smtp", fake_send_email_smtp)

    from app.config import settings
    assert not settings.email_configured  # sanity: O365 genuinely unconfigured in tests

    c = _ready_campaign(client, admin_headers, project["id"])
    client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    drain_queue()

    assert len(calls) == 1
    to_email, subject, body, kw = calls[0]
    assert to_email == "alice@example.com"
    assert kw["host"] == "smtp.acme.com"
    assert kw["password"] == "s3cret"  # resolver must decrypt before dispatch

    db = SessionLocal()
    try:
        msg = db.query(Message).filter_by(campaign_id=c["id"]).first()
        assert msg.status == "sent"
        assert msg.provider_id == "smtp-provider-id"
    finally:
        db.close()


def test_campaign_send_falls_back_to_simulated_dispatch_when_smtp_disabled(client, admin_headers, project):
    """Unchanged existing behavior: no project SMTP and no O365 configured ->
    simulated ("sent") dispatch, same as before this fix."""
    c = _ready_campaign(client, admin_headers, project["id"])
    client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    drain_queue()

    db = SessionLocal()
    try:
        msg = db.query(Message).filter_by(campaign_id=c["id"]).first()
        assert msg.status == "sent"
        assert msg.provider_id.startswith("EM-")
    finally:
        db.close()
