from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user, user_permissions
from ..mailer import project_smtp_ready
from ..models import Project, SmtpSettings, User

router = APIRouter(prefix="/api", tags=["channels"])


@router.get("/channels/status")
def channels_status(project_id: int | None = Query(None), db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """Which channels send for real vs. are simulated.

    `project_id`, when given, resolves the email row the same way
    app.mailer.send_campaign_email actually routes a send: the Review & Send
    channel card must always reflect the real sender for that project, not
    just the workspace-level O365 config, or the label and the send path
    drift out of sync (see project SMTP override / admin-active SMTP).
    """
    email_live = settings.email_configured
    email_provider = "Office 365 (Microsoft Graph)" if email_live else None

    admin_smtp = db.query(SmtpSettings).filter_by(is_active=True).first()
    if admin_smtp is not None:
        email_live = True
        email_provider = f"admin SMTP ({admin_smtp.smtp_host})"

    if project_id is not None:
        project = db.get(Project, project_id)
        if project:
            perms = user_permissions(user)
            see_all = "user.manage" in perms or "system.configure" in perms
            has_access = see_all or project.id in {p.id for p in user.projects}
            if has_access and project_smtp_ready(project):
                email_live = True
                email_provider = f"project SMTP ({project.smtp_host})"

    return {
        "email": {"live": email_live, "provider": email_provider},
        "sms": {
            "live": settings.sms_configured,
            "provider": "Metamorph Systems" if settings.sms_configured else None,
        },
        "whatsapp": {
            "live": False,   # no real WhatsApp provider wired yet
            "provider": None,
        },
    }