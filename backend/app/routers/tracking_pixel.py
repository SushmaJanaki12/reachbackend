"""Real engagement capture (P1.1/P1.2): the open-tracking pixel and
click-redirect routes every outbound email/SMS link is rewritten to point at
(see app/link_tracking.py for the rewriting, app/worker.py for where it's
applied on the send path). Public and unauthenticated -- these are hit by
recipients' mail clients and browsers, not the Reach SPA, so there's no
Authorization header to check.
"""
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import followups
from ..campaign_utils import message_template, render_template
from ..database import get_db
from ..link_tracking import TRANSPARENT_PIXEL_PNG, extract_urls
from ..models import Message, Recipient

router = APIRouter(tags=["tracking-pixel"])

_NO_CACHE_HEADERS = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", "Pragma": "no-cache"}


def _find_message(db: Session, token: str) -> Message | None:
    return db.query(Message).filter_by(tracking_token=token).first()


@router.get("/track/open/{token}.png")
def track_open(token: str, db: Session = Depends(get_db)):
    """Always returns the pixel, token valid or not -- a broken/blocked
    tracking request must never surface as a broken image in the
    recipient's inbox."""
    msg = _find_message(db, token)
    if msg is not None:
        followups.record_engagement_event(db, msg.id, "opened", source="real")
    return Response(content=TRANSPARENT_PIXEL_PNG, media_type="image/png", headers=_NO_CACHE_HEADERS)


@router.get("/track/click/{token}")
def track_click(token: str, url: str, db: Session = Depends(get_db)):
    msg = _find_message(db, token)
    if msg is None:
        raise HTTPException(status_code=404, detail="Unknown or expired tracking link")

    # Allowlist: only a destination that was actually present in this
    # specific message's own rendered content may be redirected to -- the
    # `url` param is attacker-reachable (anyone can craft a /track/click
    # link on our own domain), so this is what stops it from becoming an
    # open redirect rather than trusting it outright.
    recipient = db.get(Recipient, msg.recipient_id)
    data = (recipient.data if recipient else {}) or {}
    subject_tpl, body_tpl = message_template(db, msg)
    allowed = extract_urls(render_template(subject_tpl, data)) | extract_urls(render_template(body_tpl, data))
    if url not in allowed:
        raise HTTPException(status_code=400, detail="Destination not recognized for this message")

    followups.record_engagement_event(db, msg.id, "clicked", source="real")
    return RedirectResponse(url, status_code=302)
