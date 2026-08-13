import smtplib

import pytest

from app.smtp_mailer import send_email_smtp, SmtpMailError


class _FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port
        self.ehlo_calls = 0
        self.starttls_called = False
        self.login_args = None
        self.sent = None
        _FakeSMTP.instances.append(self)

    def ehlo(self):
        self.ehlo_calls += 1

    def starttls(self, context=None):
        self.starttls_called = True

    def login(self, username, password):
        self.login_args = (username, password)

    def sendmail(self, from_addr, to_addrs, msg):
        self.sent = (from_addr, to_addrs, msg)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def _reset():
    _FakeSMTP.instances = []
    yield
    _FakeSMTP.instances = []


def test_send_email_smtp_starttls_logs_in_and_sends(monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    mid = send_email_smtp(
        "alice@example.com", "Subject", "Hello <b>Alice</b>",
        host="smtp.example.com", port=587, username="u", password="p",
        from_email="noreply@acme.com", from_name="Acme", encryption="starttls",
    )
    assert mid.startswith("smtp-")
    server = _FakeSMTP.instances[0]
    assert server.starttls_called is True
    assert server.login_args == ("u", "p")
    from_addr, to_addrs, msg = server.sent
    assert from_addr == "noreply@acme.com"
    assert to_addrs == ["alice@example.com"]
    assert "&lt;b&gt;Alice&lt;/b&gt;" in msg  # plain text escaped, not raw HTML


def test_send_email_smtp_is_html_true_passes_body_through_unescaped(monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    send_email_smtp(
        "alice@example.com", "Subject", "<p>Hi <b>Alice</b></p>",
        host="smtp.example.com", port=587, from_email="noreply@acme.com",
        encryption="none", is_html=True,
    )
    _, _, msg = _FakeSMTP.instances[0].sent
    assert "<p>Hi <b>Alice</b></p>" in msg


def test_send_email_smtp_none_encryption_skips_starttls(monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    send_email_smtp(
        "alice@example.com", "Subject", "Hi",
        host="smtp.example.com", port=25, from_email="noreply@acme.com", encryption="none",
    )
    assert _FakeSMTP.instances[0].starttls_called is False


def test_send_email_smtp_ssl_uses_smtp_ssl(monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTP)
    send_email_smtp(
        "alice@example.com", "Subject", "Hi",
        host="smtp.example.com", port=465, from_email="noreply@acme.com", encryption="ssl",
    )
    assert len(_FakeSMTP.instances) == 1


def test_send_email_smtp_missing_host_raises_without_connecting(monkeypatch):
    with pytest.raises(SmtpMailError):
        send_email_smtp("a@b.com", "S", "B", host="", port=587, from_email="noreply@acme.com")


def test_send_email_smtp_with_attachment_includes_mime_part(monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    send_email_smtp(
        "alice@example.com", "Subject", "Hi",
        host="smtp.example.com", port=587, from_email="noreply@acme.com", encryption="none",
        attachments=[("report.csv", b"a,b\n1,2\n", "text/csv")],
    )
    _, _, msg = _FakeSMTP.instances[0].sent
    assert "Content-Disposition: attachment; filename=\"report.csv\"" in msg
    assert "multipart/mixed" in msg
    # content is base64-encoded by MIMEApplication, not sent as raw bytes
    import base64
    assert base64.b64encode(b"a,b\n1,2\n").decode() in msg


def test_send_email_smtp_no_attachments_stays_single_part(monkeypatch):
    """Regression guard: campaigns with no attachments must produce the exact
    same alternative-only message as before this feature was added."""
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    send_email_smtp(
        "alice@example.com", "Subject", "Hi",
        host="smtp.example.com", port=587, from_email="noreply@acme.com", encryption="none",
    )
    _, _, msg = _FakeSMTP.instances[0].sent
    assert "multipart/mixed" not in msg
    assert "multipart/alternative" in msg


def test_send_email_smtp_auth_failure_raises_smtp_mail_error(monkeypatch):
    class _AuthFailSMTP(_FakeSMTP):
        def login(self, username, password):
            raise smtplib.SMTPAuthenticationError(535, b"bad creds")

    monkeypatch.setattr(smtplib, "SMTP", _AuthFailSMTP)
    with pytest.raises(SmtpMailError):
        send_email_smtp(
            "alice@example.com", "Subject", "Hi",
            host="smtp.example.com", port=587, username="u", password="wrong",
            from_email="noreply@acme.com", encryption="starttls",
        )
