"""Generic SMTP email sending for project-level overrides.

Sibling to app/mailer.py (the workspace-level O365/Graph sender): mirrors its
send_email signature/behavior (HTML-wraps plain-text bodies, raises a
MailError subclass on failure, returns a message id string on success) but
talks to an arbitrary SMTP server via smtplib instead of Microsoft Graph.
"""
import smtplib
import ssl
import uuid
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from .mailer import Attachment, MailError, _to_html


class SmtpMailError(MailError):
    pass


def send_email_smtp(
    to_email: str, subject: str, body: str, *,
    host: str, port: int, from_email: str,
    username: str = "", password: str = "", from_name: str = "", reply_to: str = "",
    encryption: str = "starttls", is_html: bool = False, timeout: int = 25,
    attachments: list[Attachment] | None = None,
) -> str:
    """Send a single email via SMTP. Returns a locally-generated message id.
    Raises SmtpMailError on any connection/auth/send failure.

    `is_html` follows the same contract as app.mailer.send_email: only set
    for already-rendered, pre-escaped HTML (the branded-template content
    mode) -- every other caller sends plain text, escaped and wrapped into
    HTML here.

    `attachments`, if given, is a list of (filename, content_bytes,
    content_type) -- see app.mailer.Attachment. SMTP has no hard attachment
    size limit of its own here (unlike the Graph sender); the campaign
    composer's upload-time cap is what actually bounds this.
    """
    if not host or not from_email:
        raise SmtpMailError("SMTP host and from address are required")

    content = body if is_html else _to_html(body)
    body_part = MIMEMultipart("alternative")
    body_part.attach(MIMEText(content, "html"))

    # Only wrap in an outer "mixed" envelope when there's actually something
    # to mix in -- keeps the no-attachment message byte-identical to before.
    msg = MIMEMultipart("mixed") if attachments else body_part
    if attachments:
        msg.attach(body_part)

    msg["Subject"] = subject or ""
    msg["From"] = formataddr((from_name, from_email)) if from_name else from_email
    msg["To"] = to_email
    if reply_to:
        msg["Reply-To"] = reply_to
    message_id = f"smtp-{uuid.uuid4()}"
    msg["Message-ID"] = f"<{message_id}@{host}>"

    for filename, file_content, content_type in attachments or []:
        _, _, subtype = (content_type or "application/octet-stream").partition("/")
        part = MIMEApplication(file_content, _subtype=subtype or "octet-stream")
        part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(part)

    try:
        if encryption == "ssl":
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=context, timeout=timeout) as server:
                if username and password:
                    server.login(username, password)
                server.sendmail(from_email, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as server:
                server.ehlo()
                if encryption == "starttls":
                    server.starttls(context=ssl.create_default_context())
                    server.ehlo()
                if username and password:
                    server.login(username, password)
                server.sendmail(from_email, [to_email], msg.as_string())
    except smtplib.SMTPAuthenticationError as e:
        raise SmtpMailError(f"SMTP authentication failed: {e}")
    except (smtplib.SMTPException, OSError) as e:
        raise SmtpMailError(f"SMTP send failed: {e}")

    return message_id


def test_smtp_connection(host: str, port: int, encryption: str = "starttls",
                          username: str = "", password: str = "", timeout: int = 10) -> str:
    """Open a real connection (and, for starttls/ssl, complete the TLS
    handshake) and log in if credentials are given. No email is sent.
    Returns a human-readable success message; raises SmtpMailError on any
    failure. Shared by both the project-level and admin-level "Test
    connection" actions so they can't drift into different behaviors."""
    if not host:
        raise SmtpMailError("SMTP host is required")
    try:
        context = ssl.create_default_context()
        if encryption == "ssl":
            with smtplib.SMTP_SSL(host, port, context=context, timeout=timeout) as server:
                if username and password:
                    server.login(username, password)
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as server:
                server.ehlo()
                if encryption == "starttls":
                    server.starttls(context=context)
                    server.ehlo()
                if username and password:
                    server.login(username, password)
        return f"Connected to {host}:{port} successfully"
    except smtplib.SMTPAuthenticationError:
        raise SmtpMailError("Authentication failed — check username and password")
    except smtplib.SMTPConnectError as e:
        raise SmtpMailError(f"Could not connect to {host}:{port} — {e}")
    except (smtplib.SMTPException, OSError) as e:
        raise SmtpMailError(f"SMTP test failed: {e}")
