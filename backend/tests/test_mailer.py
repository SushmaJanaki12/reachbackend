import base64
import inspect
import json
from types import SimpleNamespace

import pytest

from app import mailer
from app.mailer import _to_html, send_email, send_campaign_email, project_smtp_ready
from app.smtp_mailer import SmtpMailError


def test_to_html_escapes_markup_and_keeps_linebreaks():
    """The plain-text path (escaped, newlines -> <br>) used by every content
    mode except the branded template."""
    raw = "Hi Alice,\n<b>bold</b> <script>evil()</script>"
    out = _to_html(raw)
    assert "<script>" not in out
    assert "<b>" not in out
    assert "&lt;script&gt;evil()&lt;/script&gt;" in out
    assert "<br>" in out


def test_send_email_is_html_defaults_to_false():
    """Regression guard: is_html must default to False so every existing
    caller (plain-text campaigns) keeps escaping content exactly as before --
    only the branded-template content mode (app/email_template.py) opts in
    explicitly. See tests/test_email_template.py for that path."""
    assert inspect.signature(send_email).parameters["is_html"].default is False


class _FakeResponse:
    status = 202
    headers = {"request-id": "req-1"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b""


def _mock_graph(monkeypatch):
    monkeypatch.setattr(mailer.settings, "azure_tenant_id", "tenant")
    monkeypatch.setattr(mailer.settings, "o365_client_id", "client")
    monkeypatch.setattr(mailer.settings, "o365_client_secret", "secret")
    monkeypatch.setattr(mailer.settings, "o365_from_email", "from@acme.com")
    monkeypatch.setattr(mailer, "_get_token", lambda: "token")
    sent = {}

    def fake_urlopen(req, timeout=None):
        sent["payload"] = json.loads(req.data.decode())
        return _FakeResponse()

    monkeypatch.setattr(mailer.urllib.request, "urlopen", fake_urlopen)
    return sent


def test_send_email_is_html_true_passes_body_through_unescaped(monkeypatch):
    """is_html=True is used only by the branded-template render path, whose
    body is already-escaped HTML from app/email_template.py -- send_email
    must send it as-is, not re-escape or otherwise mangle it."""
    sent = _mock_graph(monkeypatch)
    html_body = "<p>Hi <b>Alice</b></p>"
    send_email("alice@example.com", "Subject", html_body, is_html=True)
    assert sent["payload"]["message"]["body"]["content"] == html_body


def test_send_email_default_still_escapes(monkeypatch):
    sent = _mock_graph(monkeypatch)
    send_email("alice@example.com", "Subject", "Hi <b>Alice</b>")
    assert sent["payload"]["message"]["body"]["content"] == "Hi &lt;b&gt;Alice&lt;/b&gt;"


class TestGraphAttachments:
    """Graph fileAttachment payload building -- see
    https://learn.microsoft.com/en-us/graph/api/resources/fileattachment."""

    def test_no_attachments_key_when_none_given(self, monkeypatch):
        sent = _mock_graph(monkeypatch)
        send_email("alice@example.com", "Subject", "Hi")
        assert "attachments" not in sent["payload"]["message"]

    def test_attachment_encoded_as_base64_file_attachment(self, monkeypatch):
        sent = _mock_graph(monkeypatch)
        send_email("alice@example.com", "Subject", "Hi", attachments=[
            ("hello.txt", b"hello world", "text/plain"),
        ])
        atts = sent["payload"]["message"]["attachments"]
        assert len(atts) == 1
        assert atts[0]["@odata.type"] == "#microsoft.graph.fileAttachment"
        assert atts[0]["name"] == "hello.txt"
        assert atts[0]["contentType"] == "text/plain"
        assert base64.b64decode(atts[0]["contentBytes"]) == b"hello world"

    def test_oversized_single_attachment_rejected_before_send(self, monkeypatch):
        sent = _mock_graph(monkeypatch)
        big = b"x" * (mailer.GRAPH_MAX_ATTACHMENT_BYTES + 1)
        with pytest.raises(mailer.MailError):
            send_email("alice@example.com", "Subject", "Hi", attachments=[("big.bin", big, "application/octet-stream")])
        assert "payload" not in sent  # never reached urlopen

    def test_oversized_total_attachments_rejected_before_send(self, monkeypatch):
        sent = _mock_graph(monkeypatch)
        chunk = b"x" * (mailer.GRAPH_MAX_ATTACHMENT_BYTES - 1)
        with pytest.raises(mailer.MailError):
            send_email("alice@example.com", "Subject", "Hi", attachments=[
                ("a.bin", chunk, "application/octet-stream"),
                ("b.bin", chunk, "application/octet-stream"),
            ])
        assert "payload" not in sent

    def test_attachments_never_appear_via_logging_path(self, monkeypatch):
        """Regression guard for the "never log attachment content" requirement:
        a Graph HTTP failure must not echo the outbound request body (which
        would include the base64 blob) back into the raised MailError."""
        monkeypatch.setattr(mailer.settings, "azure_tenant_id", "tenant")
        monkeypatch.setattr(mailer.settings, "o365_client_id", "client")
        monkeypatch.setattr(mailer.settings, "o365_client_secret", "secret")
        monkeypatch.setattr(mailer.settings, "o365_from_email", "from@acme.com")
        monkeypatch.setattr(mailer, "_get_token", lambda: "token")

        import urllib.error

        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, None)

        monkeypatch.setattr(mailer.urllib.request, "urlopen", fake_urlopen)
        secret_content = b"super-secret-file-bytes"
        with pytest.raises(mailer.MailError) as exc:
            send_email("alice@example.com", "Subject", "Hi",
                      attachments=[("f.bin", secret_content, "application/octet-stream")])
        assert base64.b64encode(secret_content).decode() not in str(exc.value)


def _smtp_project(**overrides):
    base = dict(
        smtp_enabled=True, smtp_host="smtp.acme.com", smtp_port=587,
        smtp_encryption="starttls", smtp_username="u", smtp_password="",
        smtp_from_name="Acme", smtp_from_email="noreply@acme.com",
        smtp_reply_to="", smtp_fallback_on_failure=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestProjectSmtpReady:
    def test_true_when_enabled_and_fully_configured(self):
        assert project_smtp_ready(_smtp_project()) is True

    def test_false_when_disabled(self):
        assert project_smtp_ready(_smtp_project(smtp_enabled=False)) is False

    def test_false_when_missing_from_email(self):
        assert project_smtp_ready(_smtp_project(smtp_from_email="")) is False

    def test_false_when_missing_host(self):
        assert project_smtp_ready(_smtp_project(smtp_host="")) is False

    def test_false_for_none_project(self):
        assert project_smtp_ready(None) is False


class TestSendCampaignEmail:
    """The resolver every campaign send goes through -- app/worker.py calls
    this instead of send_email directly so a project's own SMTP settings are
    actually honored (the bug this module fixes)."""

    def test_no_project_falls_back_to_o365(self, monkeypatch):
        sent = _mock_graph(monkeypatch)
        pid = send_campaign_email(None, "alice@example.com", "Subject", "Hi")
        assert pid == "req-1"
        assert sent["payload"]["message"]["body"]["content"] == "Hi"

    def test_disabled_project_falls_back_to_o365(self, monkeypatch):
        sent = _mock_graph(monkeypatch)
        project = _smtp_project(smtp_enabled=False)
        send_campaign_email(project, "alice@example.com", "Subject", "Hi")
        assert sent["payload"]["message"]["body"]["content"] == "Hi"

    def test_ready_project_uses_project_smtp_not_o365(self, monkeypatch):
        graph_calls = []
        monkeypatch.setattr(mailer, "send_email", lambda *a, **k: (graph_calls.append(1), "graph")[1])

        smtp_calls = []

        def fake_send_email_smtp(to_email, subject, body, **kw):
            smtp_calls.append((to_email, subject, body, kw))
            return "smtp-provider-id"

        import app.smtp_mailer as smtp_mailer_mod
        monkeypatch.setattr(smtp_mailer_mod, "send_email_smtp", fake_send_email_smtp)

        project = _smtp_project()
        pid = send_campaign_email(project, "alice@example.com", "Subject", "Hi")

        assert pid == "smtp-provider-id"
        assert graph_calls == []
        assert len(smtp_calls) == 1
        to_email, subject, body, kw = smtp_calls[0]
        assert (to_email, subject, body) == ("alice@example.com", "Subject", "Hi")
        assert kw["host"] == "smtp.acme.com"
        assert kw["from_email"] == "noreply@acme.com"

    def test_decrypts_password_before_dispatch(self, monkeypatch):
        from app.crypto import encrypt_secret

        captured = {}

        def fake_send_email_smtp(to_email, subject, body, **kw):
            captured.update(kw)
            return "smtp-provider-id"

        import app.smtp_mailer as smtp_mailer_mod
        monkeypatch.setattr(smtp_mailer_mod, "send_email_smtp", fake_send_email_smtp)

        project = _smtp_project(smtp_password=encrypt_secret("hunter2"))
        send_campaign_email(project, "alice@example.com", "Subject", "Hi")
        assert captured["password"] == "hunter2"

    def test_smtp_failure_without_fallback_raises(self, monkeypatch):
        import app.smtp_mailer as smtp_mailer_mod

        def failing(*a, **k):
            raise SmtpMailError("boom")
        monkeypatch.setattr(smtp_mailer_mod, "send_email_smtp", failing)

        project = _smtp_project(smtp_fallback_on_failure=False)
        with pytest.raises(SmtpMailError):
            send_campaign_email(project, "alice@example.com", "Subject", "Hi")

    def test_smtp_failure_with_fallback_retries_via_o365(self, monkeypatch):
        sent = _mock_graph(monkeypatch)

        import app.smtp_mailer as smtp_mailer_mod

        def failing(*a, **k):
            raise SmtpMailError("boom")
        monkeypatch.setattr(smtp_mailer_mod, "send_email_smtp", failing)

        project = _smtp_project(smtp_fallback_on_failure=True)
        pid = send_campaign_email(project, "alice@example.com", "Subject", "Hi")
        assert sent["payload"]["message"]["body"]["content"] == "Hi"
        assert pid is not None

    def test_attachments_passed_through_to_project_smtp(self, monkeypatch):
        smtp_calls = []

        def fake_send_email_smtp(to_email, subject, body, **kw):
            smtp_calls.append(kw)
            return "smtp-provider-id"

        import app.smtp_mailer as smtp_mailer_mod
        monkeypatch.setattr(smtp_mailer_mod, "send_email_smtp", fake_send_email_smtp)

        project = _smtp_project()
        atts = [("f.txt", b"data", "text/plain")]
        send_campaign_email(project, "alice@example.com", "Subject", "Hi", attachments=atts)
        assert smtp_calls[0]["attachments"] == atts

    def test_attachments_passed_through_to_o365_fallback(self, monkeypatch):
        sent = _mock_graph(monkeypatch)
        atts = [("f.txt", b"data", "text/plain")]
        send_campaign_email(None, "alice@example.com", "Subject", "Hi", attachments=atts)
        graph_atts = sent["payload"]["message"]["attachments"]
        assert graph_atts[0]["name"] == "f.txt"

    def test_smtp_failure_with_fallback_but_o365_not_configured_raises(self, monkeypatch):
        """fallback_on_failure only helps if the workspace O365 sender is
        actually configured -- otherwise there's nothing to fall back to."""
        import app.smtp_mailer as smtp_mailer_mod

        def failing(*a, **k):
            raise SmtpMailError("boom")
        monkeypatch.setattr(smtp_mailer_mod, "send_email_smtp", failing)

        project = _smtp_project(smtp_fallback_on_failure=True)
        with pytest.raises(SmtpMailError):
            send_campaign_email(project, "alice@example.com", "Subject", "Hi")
