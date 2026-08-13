"""Sync inbound email replies from the Office 365 mailbox via Microsoft Graph.

Requires Azure app permission: Mail.Read (application, admin consented)
in addition to Mail.Send. Reads the shared sender mailbox (O365_FROM_EMAIL).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..config import settings
from ..mailer import MailError, _get_token
from ..models import Campaign, Message, Recipient


def _graph_get(url: str) -> dict:
    token = _get_token()
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:400]
        raise MailError(f"Graph read failed ({e.code}): {body}")


def fetch_recent_inbox(top: int = 50) -> list[dict]:
    """List recent messages in the configured sender's Inbox."""
    sender = (settings.o365_from_email or "").strip()
    if not sender:
        raise MailError("O365_FROM_EMAIL is not configured")
    # Prefer Inbox; fall back to all messages in mailbox
    base = f"https://graph.microsoft.com/v1.0/users/{urllib.parse.quote(sender)}"
    select = "id,subject,bodyPreview,body,from,receivedDateTime,conversationId,internetMessageId"
    url = (
        f"{base}/mailFolders/Inbox/messages"
        f"?$top={top}&$orderby=receivedDateTime%20desc&$select={select}"
    )
    try:
        data = _graph_get(url)
    except MailError:
        url = f"{base}/messages?$top={top}&$orderby=receivedDateTime%20desc&$select={select}"
        data = _graph_get(url)
    return data.get("value") or []


def _body_text(msg: dict) -> str:
    body = msg.get("body") or {}
    content = body.get("content") or msg.get("bodyPreview") or ""
    if (body.get("contentType") or "").lower() == "html":
        # crude strip tags
        import re
        content = re.sub(r"<[^>]+>", " ", content)
        content = re.sub(r"\s+", " ", content).strip()
    return (content or "")[:2000]


def sync_replies_for_campaign(db: Session, campaign_id: int) -> dict:
    """Match Graph inbox messages to campaign recipients and log them in chat_log."""
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        return {"ok": False, "error": "Campaign not found", "matched": 0}

    try:
        inbox = fetch_recent_inbox(80)
    except MailError as e:
        return {
            "ok": False,
            "error": str(e),
            "matched": 0,
            "hint": "Azure app needs application permission Mail.Read (admin consent) on the sender mailbox.",
        }

    # Map recipient email -> recipient
    by_email: dict[str, Recipient] = {}
    for r in campaign.recipients or []:
        if r.email:
            by_email[r.email.strip().lower()] = r

    matched = 0
    skipped = 0
    for msg in inbox:
        frm = ((msg.get("from") or {}).get("emailAddress") or {})
        addr = (frm.get("address") or "").strip().lower()
        if not addr or addr not in by_email:
            continue
        rec = by_email[addr]
        text = _body_text(msg)
        subject = msg.get("subject") or ""
        received = msg.get("receivedDateTime") or ""
        # normalize graph ISO
        at = received.replace("Z", "").split(".")[0] if received else datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
        graph_id = msg.get("id") or ""

        data = dict(rec.data or {})
        log = list(data.get("chat_log") or [])
        # de-dupe by graph id
        if graph_id and any(n.get("graph_id") == graph_id for n in log):
            skipped += 1
            continue
        # de-dupe similar text+time
        if any(n.get("text") == text and n.get("at", "")[:16] == at[:16] for n in log):
            skipped += 1
            continue

        log.append({
            "direction": "in",
            "channel": "email",
            "text": text or subject or "(empty reply)",
            "subject": subject,
            "at": at,
            "graph_id": graph_id,
            "source": "graph_sync",
        })
        data["chat_log"] = log
        rec.data = data
        rec.reply_status = "replied"
        rec.next_followup_at = None
        matched += 1

    if matched:
        db.commit()
    return {"ok": True, "matched": matched, "skipped": skipped, "scanned": len(inbox)}


def sync_replies_all(db: Session) -> dict:
    total = 0
    errors = []
    for camp in db.query(Campaign).all():
        res = sync_replies_for_campaign(db, camp.id)
        if res.get("ok"):
            total += res.get("matched") or 0
        else:
            errors.append(res.get("error") or "error")
            break  # credential issue — stop
    return {"ok": not errors, "matched": total, "errors": errors}
