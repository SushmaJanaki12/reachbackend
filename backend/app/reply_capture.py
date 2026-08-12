"""Real inbound-reply capture (P1.3): polls one workspace-wide IMAP mailbox
(app/models.py::ReplyCaptureSettings) for replies to real campaign sends,
matches each one back to the Message it replied to, and feeds it through the
exact same app/followups.py::record_engagement_event path Simulate already
uses -- classification and stop/tag logic must behave identically regardless
of where the reply came from.

Matching is via a "+token" subaddress rather than Message-ID/In-Reply-To
threading headers: this app sends through either Microsoft Graph or an
arbitrary per-project/admin SMTP config (see app/mailer.py), so there's no
single provider whose inbound-parse webhook would cover every campaign, and
some corporate mail gateways strip threading headers in transit. A reply-to
alias survives both of those -- see reply_to_alias() and app/worker.py,
which sets it as the Reply-To on every real send once capture is enabled.
"""
import email as email_lib
import imaplib
import logging
import re
from datetime import datetime, timezone
from email.header import decode_header
from email.message import Message as EmailMessage

from sqlalchemy.orm import Session

from . import followups
from .crypto import decrypt_secret
from .database import SessionLocal
from .models import Message, ReplyCaptureSettings

logger = logging.getLogger(__name__)

# Matches "local+token@domain", optionally wrapped in a display name / angle
# brackets / other addresses in the same header value.
_ALIAS_RE = re.compile(r"[\w.+-]+\+([A-Za-z0-9_-]+)@[\w.-]+")


def reply_to_alias(mailbox_address: str, token: str) -> str:
    """local+token@domain -- the Reply-To this app sets on outbound sends
    once reply capture is enabled, so a genuine reply both routes to the
    mailbox this module polls and carries the token needed to match it back
    to its Message row."""
    local, _, domain = (mailbox_address or "").partition("@")
    return f"{local}+{token}@{domain}"


def _extract_token(header_value: str) -> str | None:
    m = _ALIAS_RE.search(header_value or "")
    return m.group(1) if m else None


def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    out = []
    for text, enc in decode_header(value):
        out.append(text.decode(enc or "utf-8", errors="replace") if isinstance(text, bytes) else text)
    return "".join(out)


def _decode_payload(part: EmailMessage) -> str:
    payload = part.get_payload(decode=True) or b""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _plain_text_body(msg: EmailMessage) -> str:
    """First text/plain part; falls back to a crude tag-strip of text/html
    if that's all a reply client sent."""
    if not msg.is_multipart():
        body = _decode_payload(msg)
        return re.sub(r"<[^>]+>", " ", body) if msg.get_content_type() == "text/html" else body
    html_fallback = None
    for part in msg.walk():
        if part.get_content_disposition() == "attachment":
            continue
        ctype = part.get_content_type()
        if ctype == "text/plain":
            return _decode_payload(part)
        if ctype == "text/html" and html_fallback is None:
            html_fallback = part
    return re.sub(r"<[^>]+>", " ", _decode_payload(html_fallback)) if html_fallback is not None else ""


def poll_inbox(db: Session, cfg: ReplyCaptureSettings) -> dict:
    """One poll cycle against a live IMAP server: connects, reads unseen
    mail, matches + records replies, marks each handled message \\Seen.
    Raises on a connection/auth/search failure -- callers decide how to
    record that (see poll_once)."""
    imap_cls = imaplib.IMAP4_SSL if cfg.imap_use_ssl else imaplib.IMAP4
    conn = imap_cls(cfg.imap_host, cfg.imap_port)
    try:
        conn.login(cfg.imap_username, decrypt_secret(cfg.imap_password))
        conn.select(cfg.poll_folder or "INBOX")
        status, data = conn.search(None, "UNSEEN")
        if status != "OK":
            raise RuntimeError(f"IMAP search failed: {status}")
        ids = data[0].split() if data and data[0] else []
        checked = matched = 0
        for num in ids:
            checked += 1
            status, msg_data = conn.fetch(num, "(RFC822)")
            if status != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            raw = msg_data[0][1]
            parsed = email_lib.message_from_bytes(raw)
            to_header = " ".join(_decode_header_value(parsed.get(h)) for h in ("To", "Delivered-To"))
            token = _extract_token(to_header)
            if token:
                target = db.query(Message).filter_by(tracking_token=token).first()
                if target is not None:
                    body = _plain_text_body(parsed).strip()
                    followups.record_engagement_event(db, target.id, "replied", reply_text=body, source="real")
                    matched += 1
            conn.store(num, "+FLAGS", "\\Seen")
        return {"checked": checked, "matched": matched}
    finally:
        try:
            conn.logout()
        except Exception:
            pass  # best-effort -- a failed logout shouldn't mask the poll's real outcome


def poll_once() -> dict | None:
    """Entry point for both the manual "poll now" admin action and the
    self-rescheduling periodic job (app/worker.py). Returns None if capture
    isn't enabled/configured, or a poll failed (recorded on the settings row
    either way); otherwise the poll_inbox() stats."""
    db = SessionLocal()
    try:
        cfg = db.query(ReplyCaptureSettings).first()
        if cfg is None or not cfg.enabled or not cfg.imap_host:
            return None
        now = datetime.now(timezone.utc)
        try:
            stats = poll_inbox(db, cfg)
        except Exception as e:
            cfg.last_polled_at = now
            cfg.last_poll_status = "failed"
            cfg.last_poll_error = str(e)[:300]
            db.commit()
            logger.warning("reply capture: poll failed: %s", e)
            return None
        cfg.last_polled_at = now
        cfg.last_poll_status = "ok"
        cfg.last_poll_error = ""
        db.commit()
        logger.info("reply capture: poll ok, checked=%s matched=%s", stats["checked"], stats["matched"])
        return stats
    finally:
        db.close()
