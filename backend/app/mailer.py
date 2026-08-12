"""Office 365 email sending via Microsoft Graph (client-credentials flow),
plus send_campaign_email() -- the resolver every campaign send should call,
which additionally routes through a project's own SMTP settings (tier 2)
and, below that, the admin-configured workspace-default SMTP settings
(tier 3, app/routers/admin_smtp.py) when either is set up (see
app/smtp_mailer.py). Full tier order: campaign override (not yet
supported) -> project SMTP -> admin-active SMTP -> this module's O365/Graph
sender as the last resort.

Requires an Azure AD app registration with the *application* permission
`Mail.Send` (admin-consented). Sends as O365_FROM_EMAIL.
"""
import base64
import json
import time
import html as _html
import urllib.request
import urllib.parse
import urllib.error

from sqlalchemy.orm import object_session
from sqlalchemy.orm.exc import UnmappedInstanceError

from .config import settings

_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
_GRAPH_SENDMAIL = "https://graph.microsoft.com/v1.0/users/{sender}/sendMail"

# Graph's direct sendMail call (no upload session) rejects messages above
# these limits -- see https://learn.microsoft.com/en-us/graph/api/resources/fileattachment.
# Enforced here as a last line of defense; the campaign composer's upload-time
# cap (app/storage.py) is meant to catch this earlier for the common case.
GRAPH_MAX_ATTACHMENT_BYTES = 3 * 1024 * 1024
GRAPH_MAX_TOTAL_ATTACHMENT_BYTES = 4 * 1024 * 1024

# (filename, content_bytes, content_type) -- the shape every sender/resolver
# in this module and app/smtp_mailer.py accepts for its `attachments` param.
Attachment = tuple[str, bytes, str]

_token_cache = {"token": None, "exp": 0.0}


class MailError(Exception):
    pass


def _get_token() -> str:
    now = time.time()
    if _token_cache["token"] and _token_cache["exp"] - 60 > now:
        return _token_cache["token"]
    url = _TOKEN_URL.format(tenant=settings.azure_tenant_id)
    data = urllib.parse.urlencode({
        "client_id": settings.o365_client_id,
        "client_secret": settings.o365_client_secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise MailError(f"Token request failed ({e.code}): {e.read().decode(errors='replace')[:300]}")
    except Exception as e:
        raise MailError(f"Token request failed: {e}")
    if "access_token" not in payload:
        raise MailError(f"No access_token in response: {str(payload)[:200]}")
    _token_cache["token"] = payload["access_token"]
    _token_cache["exp"] = now + int(payload.get("expires_in", 3600))
    return _token_cache["token"]


def _to_html(body: str) -> str:
    # plain-text body -> simple HTML (escape, keep line breaks)
    return _html.escape(body or "").replace("\n", "<br>")


def _graph_attachments(attachments: list[Attachment]) -> list[dict]:
    """Build the Graph `message.attachments` array, rejecting anything the
    direct sendMail call (no large-attachment upload session) would reject."""
    total = sum(len(content) for _, content, _ in attachments)
    if total > GRAPH_MAX_TOTAL_ATTACHMENT_BYTES:
        raise MailError(
            f"Attachments total {total} bytes, over the "
            f"{GRAPH_MAX_TOTAL_ATTACHMENT_BYTES} byte limit for a direct Graph send"
        )
    oversized = [filename for filename, content, _ in attachments if len(content) > GRAPH_MAX_ATTACHMENT_BYTES]
    if oversized:
        raise MailError(
            f"Attachment(s) over the {GRAPH_MAX_ATTACHMENT_BYTES} byte per-file "
            f"limit for a direct Graph send: {', '.join(oversized)}"
        )
    return [
        {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": filename,
            "contentType": content_type or "application/octet-stream",
            "contentBytes": base64.b64encode(content).decode(),
        }
        for filename, content, content_type in attachments
    ]


def send_email(to_email: str, subject: str, body: str, from_email: str | None = None, is_html: bool = False,
                attachments: list[Attachment] | None = None, reply_to: str | None = None) -> str:
    """Send a single email. Returns the Graph provider request id. Raises MailError on failure.

    `is_html`, if set, means `body` is already-rendered, pre-escaped HTML;
    every other caller sends plain text, which is still escaped and wrapped
    into HTML here as before.

    `attachments`, if given, is a list of (filename, content_bytes, content_type)
    -- see GRAPH_MAX_ATTACHMENT_BYTES/GRAPH_MAX_TOTAL_ATTACHMENT_BYTES for the
    size limits enforced before attempting the send.

    `reply_to`, if given, overrides where a reply lands -- used for real
    inbound-reply capture (P1.3, app/reply_capture.py) to route replies to
    the polled mailbox instead of wherever this campaign's From address
    would otherwise land them.
    """
    if not settings.email_configured:
        raise MailError("Office 365 email is not configured")
    token = _get_token()
    sender = from_email or settings.o365_from_email
    url = _GRAPH_SENDMAIL.format(sender=urllib.parse.quote(sender))
    content = body if is_html else _to_html(body)
    message = {
        "message": {
            "subject": subject or "",
            "body": {"contentType": "HTML", "content": content},
            "toRecipients": [{"emailAddress": {"address": to_email}}],
        },
        "saveToSentItems": True,
    }
    if reply_to:
        message["message"]["replyTo"] = [{"emailAddress": {"address": reply_to}}]
    if attachments:
        message["message"]["attachments"] = _graph_attachments(attachments)
    req = urllib.request.Request(
        url, data=json.dumps(message).encode(), method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            # Graph returns 202 Accepted with an empty body; use the request id header if present
            return resp.headers.get("request-id", f"graph-{resp.status}")
    except urllib.error.HTTPError as e:
        raise MailError(f"Graph sendMail failed ({e.code}): {e.read().decode(errors='replace')[:300]}")
    except Exception as e:
        raise MailError(f"Graph sendMail failed: {e}")


def verify_connection() -> dict:
    """Acquire a token to confirm credentials work (no email sent)."""
    _get_token()
    return {"ok": True, "sender": settings.o365_from_email}


def project_smtp_ready(project) -> bool:
    """Whether `project` has a usable SMTP override -- enabled, with the
    fields required to actually attempt a send. A saved-but-disabled or
    partially-filled-in config falls back to O365 exactly as if it were
    never set."""
    return bool(
        project and project.smtp_enabled
        and project.smtp_host and project.smtp_port and project.smtp_from_email
    )


def _session_of(project):
    """The SQLAlchemy session `project` is attached to, so the admin-SMTP
    tier can be queried without every caller having to pass a `db` session
    through the resolver. Unit tests exercise this resolver against plain
    stand-in objects (not real ORM instances) -- those aren't mapped, so
    treat "not a real attached ORM instance" the same as "no session
    available" (falls straight through to the O365 default) rather than
    raising."""
    if project is None:
        return None
    try:
        return object_session(project)
    except UnmappedInstanceError:
        return None


def _active_admin_smtp(db):
    """The workspace-default SMTP config (tier 3, app/routers/admin_smtp.py),
    if one has been activated. `db` may be None (e.g. a detached `project`)
    -- treated the same as "none configured"."""
    if db is None:
        return None
    from .models import SmtpSettings
    return db.query(SmtpSettings).filter_by(is_active=True).first()


def email_channel_configured(project) -> bool:
    """Whether a real send is possible for `project` -- true if any resolver
    tier is usable (project SMTP, admin-active SMTP, or workspace O365).
    Callers (the send worker) use this to decide whether to attempt a real
    send or fall back to simulated dispatch; it must check every tier
    send_campaign_email itself would try, or the two can disagree -- e.g.
    an admin-active SMTP config with no O365 and no project override would
    otherwise get silently simulated instead of actually sent."""
    if project_smtp_ready(project):
        return True
    if _active_admin_smtp(_session_of(project)) is not None:
        return True
    return settings.email_configured


def _send_via_admin_or_graph(db, to_email: str, subject: str, body: str, is_html: bool,
                              attachments: list[Attachment] | None = None, reply_to: str | None = None) -> str:
    admin_cfg = _active_admin_smtp(db)
    if admin_cfg is not None:
        from .crypto import decrypt_secret
        from .smtp_mailer import send_email_smtp
        return send_email_smtp(
            to_email, subject, body,
            host=admin_cfg.smtp_host, port=admin_cfg.smtp_port,
            username=admin_cfg.username, password=decrypt_secret(admin_cfg.password),
            from_email=admin_cfg.from_email, from_name=admin_cfg.from_name,
            reply_to=reply_to or admin_cfg.reply_to, encryption=admin_cfg.encryption,
            is_html=is_html, attachments=attachments,
        )
    return send_email(to_email, subject, body, is_html=is_html, attachments=attachments, reply_to=reply_to)


def send_system_email(db, to_email: str, subject: str, body: str, is_html: bool = False) -> str:
    """Workspace-level (non-campaign) email -- password reset links (P1.7),
    etc. There's no project to resolve a per-project SMTP override from
    here, so this goes straight to the same admin-SMTP-then-Graph fallback
    send_campaign_email uses below its project tier. Raises MailError if
    neither is configured."""
    return _send_via_admin_or_graph(db, to_email, subject, body, is_html)


def send_campaign_email(project, to_email: str, subject: str, body: str, is_html: bool = False,
                         attachments: list[Attachment] | None = None, reply_to: str | None = None) -> str:
    """Single entry point for campaign sends. Every campaign-sending call
    site must go through this instead of importing send_email directly, so
    the resolver tiers are actually honored, in order:

    1. Project-level SMTP, if `smtp_enabled` and fully configured.
    2. The admin-active SMTP config (app/routers/admin_smtp.py), if one has
       been activated -- either as the default (no project override) or as
       an explicit retry when the project opted into
       `smtp_fallback_on_failure` and the project SMTP send raised.
    3. Workspace O365/Graph, as the last resort.

    `attachments`, if given, is passed through unchanged to whichever tier
    handles the send -- see app.mailer.Attachment for the expected shape and
    app.storage for the upload-time size/type validation every attachment
    here should already have passed.

    `reply_to`, if given, overrides whichever tier's own configured
    reply-to address -- used for real inbound-reply capture (P1.3,
    app/reply_capture.py) so a reply lands in the mailbox this app actually
    polls instead of wherever the project/admin config would otherwise
    route it.
    """
    db = _session_of(project)
    if project_smtp_ready(project):
        from .crypto import decrypt_secret
        from .smtp_mailer import send_email_smtp, SmtpMailError
        try:
            return send_email_smtp(
                to_email, subject, body,
                host=project.smtp_host, port=project.smtp_port,
                username=project.smtp_username, password=decrypt_secret(project.smtp_password),
                from_email=project.smtp_from_email, from_name=project.smtp_from_name,
                reply_to=reply_to or project.smtp_reply_to, encryption=project.smtp_encryption,
                is_html=is_html, attachments=attachments,
            )
        except SmtpMailError:
            if project.smtp_fallback_on_failure and (_active_admin_smtp(db) is not None or settings.email_configured):
                return _send_via_admin_or_graph(db, to_email, subject, body, is_html, attachments, reply_to)
            raise
    return _send_via_admin_or_graph(db, to_email, subject, body, is_html, attachments, reply_to)
