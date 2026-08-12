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
from datetime import datetime, timedelta, timezone

from rq import get_current_job

from . import followups
from .campaign_utils import (
    QUEUE_NAME, _maybe_complete_campaign, enqueue_message, message_template, redis_conn, render_template, send_queue,
)
from .config import settings
from .database import SessionLocal
from .link_tracking import rewrite_links_plain, to_html_with_tracking
from .mailer import send_campaign_email, project_smtp_ready, email_channel_configured, MailError
from .models import Message, Recipient, ReplyCaptureSettings, SmsTemplate, Suppression
from .reply_capture import poll_once, reply_to_alias
from .routers.suppressions import normalize_contact
from .sms import send_sms, matches_template, SmsError
from .storage import read_campaign_attachment

logger = logging.getLogger(__name__)

# Terminal states a redelivered job must not reprocess.
_TERMINAL_STATUSES = {"sent", "delivered", "read", "failed", "suppressed"}


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

        subject_tpl, body_tpl = message_template(db, msg)
        now = datetime.now(timezone.utc)
        try:
            project_smtp = project_smtp_ready(campaign.project)
            if msg.channel == "email" and email_channel_configured(campaign.project):
                missing: list[str] = []
                subject = render_template(subject_tpl, data, missing)
                body = render_template(body_tpl, data, missing)
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
                html_body = to_html_with_tracking(body, msg.tracking_token)
                reply_capture_cfg = db.query(ReplyCaptureSettings).first()
                reply_to = (
                    reply_to_alias(reply_capture_cfg.mailbox_address, msg.tracking_token)
                    if reply_capture_cfg and reply_capture_cfg.enabled and reply_capture_cfg.mailbox_address
                    else None
                )
                pid = send_campaign_email(campaign.project, msg.to_address, subject, html_body,
                                           is_html=True, attachments=attachments, reply_to=reply_to)
                msg.status, msg.sent_at, msg.provider_id = "sent", now, pid
            elif msg.channel == "sms" and settings.sms_configured:
                body = render_template(body_tpl, data)
                sms_template = db.get(SmsTemplate, campaign.sms_template_ref) if campaign.sms_template_ref else None
                if sms_template and not matches_template(sms_template.body, body):
                    msg.status = "failed"
                    msg.error = "Content does not match the selected DLT template"
                else:
                    if not sms_template:
                        # DLT-registered content must be sent byte-for-byte as
                        # approved -- rewriting a URL in it would both fail the
                        # matches_template check above and risk the carrier
                        # rejecting/blocking the message. Only rewrite links
                        # for free-form (non-DLT) SMS.
                        body = rewrite_links_plain(body, msg.tracking_token)
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
        if msg.step_id is None and msg.channel == "email" and msg.status == "sent":
            # Original blast email went out -- kick off this recipient's
            # follow-up sequence, if the campaign has any steps configured.
            followups.maybe_start_run(db, msg)
        _maybe_complete_campaign(db, campaign.id)
    finally:
        db.close()


_REPLY_CAPTURE_JOB_ID = "reply-capture-poll"


def poll_reply_capture_and_reschedule() -> None:
    """RQ job: run one reply-capture poll cycle (app/reply_capture.py --
    a no-op if it isn't enabled/configured), then schedule the next one
    poll_interval_seconds later. Self-rescheduling rather than a fixed
    interval baked in at first enqueue, so changing the interval -- or
    enabling capture for the first time -- takes effect on the next cycle
    without restarting the worker."""
    db = SessionLocal()
    try:
        cfg = db.query(ReplyCaptureSettings).first()
        interval = cfg.poll_interval_seconds if cfg and cfg.poll_interval_seconds else 120
    finally:
        db.close()
    poll_once()
    send_queue.enqueue_at(
        datetime.now(timezone.utc) + timedelta(seconds=interval),
        # Referenced by import path, not the live function object -- see
        # campaign_utils.py::enqueue_message. Running this file directly
        # (`python -m app.worker`, how the worker process actually starts)
        # makes this module __main__, and RQ refuses to enqueue a function
        # whose __module__ is "__main__" since a separate worker process
        # couldn't import it back. The string form resolves against
        # "app.worker" instead, which is always importable regardless of
        # how this process itself was launched.
        "app.worker.poll_reply_capture_and_reschedule", job_timeout=60, job_id=_REPLY_CAPTURE_JOB_ID,
    )


def schedule_reply_capture_polling() -> None:
    """Kicks off the self-rescheduling poll loop above, unless one is
    already scheduled -- reusing a stable job id makes this idempotent
    across worker restarts instead of piling up parallel poll chains."""
    from rq.job import Job
    try:
        Job.fetch(_REPLY_CAPTURE_JOB_ID, connection=redis_conn)
        return  # already scheduled by a still-live chain
    except Exception:
        pass
    send_queue.enqueue_at(
        datetime.now(timezone.utc) + timedelta(seconds=5),
        "app.worker.poll_reply_capture_and_reschedule", job_timeout=60, job_id=_REPLY_CAPTURE_JOB_ID,
    )


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
    schedule_reply_capture_polling()
    # with_scheduler=True is required for Retry(...) backoff intervals (and
    # the reply-capture poll loop above) to actually fire -- otherwise
    # scheduled jobs sit in the ScheduledJobRegistry forever since nothing
    # moves them back into the queue.
    Worker([send_queue], connection=redis_conn).work(with_scheduler=True)
