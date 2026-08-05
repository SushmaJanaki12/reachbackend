"""Queue-based campaign sending (C2).

Run the worker alongside the API as a separate process:

    python -m app.worker

Jobs are one per (campaign_id, recipient_id, channel) -- i.e. one per Message
row. Each job re-checks the suppression list, sends via the existing
mailer/sms helpers, and commits its own row so a crashed worker only ever
loses at most one in-flight message.
"""
import os
import sys

if sys.platform == "darwin" and __name__ == "__main__" \
        and not os.environ.get("OBJC_DISABLE_INITIALIZE_FORK_SAFETY"):
    # RQ forks a work-horse subprocess (raw os.fork()) per job. On macOS, if
    # any library loaded into this process has touched Objective-C/Foundation
    # classes on a background thread -- e.g. libpq's Kerberos/GSSAPI path,
    # exercised on essentially every DB connection -- that fork() aborts the
    # child with "may have been in progress in another thread when fork() was
    # called. Crashing instead." RQ's own crash handling then hits a second
    # bug turning that into a *fatal top-level worker exit*, silently
    # orphaning every other job left in the queue -- explains messages stuck
    # at "queued" forever with no error anywhere.
    #
    # OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES is the standard opt-out, but
    # libobjc reads/caches it at library-load time, not at fork time -- by
    # the time our own top-level imports below (redis, rq, sqlalchemy,
    # psycopg2, ...) have run, it's too late to set it from within this
    # process. Re-exec ourselves from scratch with it already present in the
    # initial environment block instead. This must stay the very first thing
    # the module does, before any other import.
    os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
    os.execve(sys.executable, [sys.executable, "-m", "app.worker", *sys.argv[1:]], os.environ)

import logging
import time
from datetime import datetime, timezone

from redis import Redis
from rq import Queue, Retry
from rq import get_current_job

from .campaign_utils import render_template
from .config import settings
from .database import SessionLocal
from .mailer import send_campaign_email, project_smtp_ready, email_channel_configured, MailError
from .models import Campaign, Message, Recipient, SmsTemplate, Suppression
from .routers.suppressions import normalize_contact
from .sms import send_sms, matches_template, SmsError
from .storage import read_campaign_attachment

QUEUE_NAME = "sends"

redis_conn = Redis.from_url(settings.redis_url)
send_queue = Queue(QUEUE_NAME, connection=redis_conn)
logger = logging.getLogger(__name__)

# Terminal states a redelivered job must not reprocess.
_TERMINAL_STATUSES = {"sent", "delivered", "read", "failed", "suppressed"}


def enqueue_message(message_id: int) -> None:
    job = send_queue.enqueue(
        process_message, message_id,
        retry=Retry(max=settings.send_max_retries, interval=[10, 30, 60]),
        job_timeout=60,
    )
    logger.info("message %s: enqueued as job %s", message_id, job.id)


def _throttle(channel: str, project_id: int | None = None, per_minute_override: float | None = None) -> None:
    """Simple fixed-window rate limiter, shared across workers via Redis.

    `per_minute_override` is used for project-level SMTP throttling
    (Project.smtp_max_per_minute): many SMTP providers (Office365 SMTP AUTH,
    Gmail, shared business email) throttle or lock accounts under bulk
    sending, so a project's own cap is tracked under its own Redis key
    rather than sharing the workspace-wide email rate limit.
    """
    if per_minute_override is not None:
        limit = per_minute_override / 60.0
        key = f"ratelimit:{channel}:project:{project_id}"
    else:
        limit = {"email": settings.email_rate_per_second, "sms": settings.sms_rate_per_second}.get(channel)
        key = f"ratelimit:{channel}"
    if not limit or limit <= 0:
        return
    while True:
        count = redis_conn.incr(key)
        if count == 1:
            redis_conn.expire(key, 1)
        if count <= limit:
            return
        time.sleep(1.0 / limit)


def _maybe_complete_campaign(db, campaign_id: int) -> None:
    remaining = db.query(Message).filter(
        Message.campaign_id == campaign_id, Message.status.in_(("queued", "processing"))
    ).count()
    if remaining == 0:
        campaign = db.get(Campaign, campaign_id)
        if campaign and campaign.status == "sending":
            campaign.status = "completed"
            db.commit()
            logger.info("campaign %s: all messages resolved, marked completed", campaign_id)


def process_message(message_id: int) -> None:
    logger.info("message %s: job started", message_id)
    db = SessionLocal()
    try:
        msg = db.get(Message, message_id)
        if msg is None or msg.status in _TERMINAL_STATUSES:
            logger.info("message %s: skipped (missing or already terminal)", message_id)
            return  # already handled -- redelivered job, skip

        campaign = msg.campaign
        recipient = db.get(Recipient, msg.recipient_id)
        data = (recipient.data if recipient else {}) or {}

        msg.status = "processing"
        db.commit()

        contact_suppressed = db.query(Suppression).filter_by(
            project_id=campaign.project_id, contact=normalize_contact(msg.to_address), channel=msg.channel,
        ).first()
        if contact_suppressed:
            msg.status = "suppressed"
            msg.error = "Recipient has opted out of this channel"
            db.commit()
            _maybe_complete_campaign(db, campaign.id)
            return

        content = next((c for c in campaign.contents if c.channel == msg.channel), None)
        now = datetime.now(timezone.utc)
        try:
            project_smtp = project_smtp_ready(campaign.project)
            if msg.channel == "email" and email_channel_configured(campaign.project):
                missing: list[str] = []
                subject = render_template(content.subject, data, missing) if content else ""
                body = render_template(content.body, data, missing) if content else ""
                if missing:
                    names = ", ".join(sorted(set(missing)))
                    logger.warning(
                        "message %s: unresolved placeholder(s) %s", msg.id, names)
                    msg.warnings = names[:300]
                per_minute = campaign.project.smtp_max_per_minute if project_smtp else None
                _throttle("email", campaign.project_id, per_minute)
                attachments = [
                    (a.filename, read_campaign_attachment(a.storage_path), a.content_type)
                    for a in campaign.attachments
                ] or None
                pid = send_campaign_email(campaign.project, msg.to_address, subject, body, attachments=attachments)
                msg.status, msg.sent_at, msg.provider_id = "sent", now, pid
            elif msg.channel == "sms" and settings.sms_configured:
                body = render_template(content.body, data) if content else ""
                sms_template = db.get(SmsTemplate, campaign.sms_template_ref) if campaign.sms_template_ref else None
                if sms_template and not matches_template(sms_template.body, body):
                    msg.status = "failed"
                    msg.error = "Content does not match the selected DLT template"
                else:
                    _throttle("sms")
                    resp = send_sms(msg.to_address, body, sms_template.template_id if sms_template else None)
                    msg.status, msg.sent_at, msg.provider_id = "sent", now, resp
            else:
                # Simulated dispatch (SMS/WhatsApp, or email when O365 not configured)
                msg.status, msg.sent_at = "sent", now
                msg.provider_id = f"{msg.channel[:2].upper()}-{campaign.id}-{msg.recipient_id}"
                if msg.channel in ("whatsapp", "sms"):
                    msg.status, msg.delivered_at = "delivered", now
                    if msg.channel == "whatsapp":
                        msg.read_at = now
            db.commit()
        except (MailError, SmsError) as e:
            job = get_current_job()
            if job is not None and job.retries_left:
                db.rollback()
                raise
            msg.status = "failed"
            msg.error = str(e)[:300]
            logger.warning("message %s: send failed, retries exhausted: %s", msg.id, e)
            db.commit()
        except Exception as e:
            # Anything else (e.g. a bug in placeholder rendering) is
            # deterministic -- retrying won't help. Fail just this message and
            # keep the batch moving, rather than letting the exception escape
            # process_message: that would leave the row stuck at "processing"
            # forever and, for a forking RQ Worker, kill the work-horse too.
            logger.exception("message %s: unexpected error, marking failed", msg.id)
            msg.status = "failed"
            msg.error = str(e)[:300]
            db.commit()

        logger.info("message %s: job finished with status=%s", msg.id, msg.status)
        _maybe_complete_campaign(db, campaign.id)
    finally:
        db.close()


if __name__ == "__main__":
    from rq import Worker

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if sys.platform == "darwin":
        # RQ's scheduler subprocess can't be pickled under macOS's default
        # "spawn" start method (fails on an internal RLock) -- force "fork"
        # like Linux uses by default. (The work-horse fork-safety re-exec
        # above is a separate, unrelated macOS fork issue.)
        import multiprocessing
        multiprocessing.set_start_method("fork")

    logger.info("worker starting, queue=%s redis=%s", QUEUE_NAME, settings.redis_url)
    # with_scheduler=True is required for Retry(...) backoff intervals to
    # actually fire -- otherwise retried jobs sit in the ScheduledJobRegistry
    # forever since nothing moves them back into the queue.
    Worker([send_queue], connection=redis_conn).work(with_scheduler=True)
