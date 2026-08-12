"""Real unsubscribe capture (P1.8): every outbound email gets a per-message
unsubscribe link (see app/link_tracking.py::unsubscribe_url, injected in
app/worker.py) built from the same tracking_token as the open-pixel/
click-redirect routes. Public and unauthenticated -- hit directly by
whatever browser the recipient's mail client opens the link in.
"""
import html as _html

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Message, Suppression
from .suppressions import normalize_contact

router = APIRouter(tags=["unsubscribe"])

_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; background: #f5f6f8;
         display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
  .card {{ background: #fff; border-radius: 12px; padding: 32px 40px; max-width: 420px;
          box-shadow: 0 1px 3px rgba(0,0,0,0.1); text-align: center; }}
  h1 {{ font-size: 18px; margin: 0 0 8px; }}
  p {{ color: #555; font-size: 14px; line-height: 1.5; }}
</style></head>
<body><div class="card"><h1>{title}</h1><p>{message}</p></div></body></html>"""


@router.get("/unsubscribe")
def unsubscribe(token: str, db: Session = Depends(get_db)):
    msg = db.query(Message).filter_by(tracking_token=token).first()
    if msg is None or not msg.to_address:
        return HTMLResponse(
            _PAGE.format(title="Link not recognized", message="This unsubscribe link is invalid or has expired."),
            status_code=404,
        )

    contact = normalize_contact(msg.to_address)
    existing = db.query(Suppression).filter_by(
        project_id=msg.campaign.project_id, contact=contact, channel="email").first()
    if existing is None:
        db.add(Suppression(project_id=msg.campaign.project_id, contact=contact,
                            channel="email", reason="unsubscribed"))
        db.commit()

    return HTMLResponse(_PAGE.format(
        title="You're unsubscribed",
        message=f"{_html.escape(msg.to_address)} will no longer receive emails from this sender.",
    ))
