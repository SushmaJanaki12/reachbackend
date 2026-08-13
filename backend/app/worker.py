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
from .email_template import render_email_template
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
    # String path: required when worker is started as `python -m app.worker`
    if sys.platform == "win32":
        intervals, timeout = [2, 5, 10], 120
    else:
        intervals, timeout = [10, 30, 60], 60
    job = send_queue.enqueue(
        "app.worker.process_message",
        message_id,
        retry=Retry(max=settings.send_max_retries, interval=intervals),
        job_timeout=timeout,
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
        # Prefer per-step sequence content for follow-ups (and step 0 when present)
        try:
            from .models import CampaignSequenceStep
            step_n = int(msg.followup_number or 0) if msg.is_followup else 0
            if not msg.is_followup:
                step_n = 0
            step = (
                db.query(CampaignSequenceStep)
                .filter_by(campaign_id=campaign.id, step_number=step_n)
                .first()
            )
            if step:
                subj = ""
                body_text = ""
                if msg.channel == "email":
                    subj = (getattr(step, "email_subject", None) or getattr(step, "subject", None) or "") or ""
                    body_text = (getattr(step, "email_body", None) or getattr(step, "body", None) or "") or ""
                elif msg.channel == "whatsapp":
                    body_text = (getattr(step, "whatsapp_body", None) or getattr(step, "body", None) or "") or ""
                elif msg.channel == "sms":
                    body_text = (getattr(step, "sms_body", None) or getattr(step, "body", None) or "") or ""
                if subj or body_text:
                    class _StepContent:
                        pass
                    sc = _StepContent()
                    sc.subject = subj
                    sc.body = body_text
                    sc.content_mode = "plain"
                    sc.template_fields = {}
                    content = sc
                    logger.info("message %s: sequence step %s (%s chars)", msg.id, step_n, len(body_text or ""))
        except Exception as exc:
            logger.warning("sequence step lookup failed for message %s: %s", msg.id, exc)
        now = datetime.now(timezone.utc)
        try:
            project_smtp = project_smtp_ready(campaign.project)
            if msg.channel == "email" and email_channel_configured(campaign.project):
                missing: list[str] = []
                subject = render_template(content.subject, data, missing) if content else ""
                is_html = bool(content and content.content_mode == "template")
                if is_html:
                    body = render_email_template(campaign.project, content.template_fields or {}, recipient, missing)
                else:
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
                pid = send_campaign_email(campaign.project, msg.to_address, subject, body, is_html=True,
                                          attachments=attachments) if is_html \
                    else send_campaign_email(campaign.project, msg.to_address, subject, body, attachments=attachments)
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



def _run_due_followups_tick():
    try:
        from datetime import datetime, timezone
        from .models import Campaign
        from .routers.engagement import (
            compute_next_send_at, _step_channels, _ensure_default_steps, _as_utc, _delay_days,
        )
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            total = 0
            for campaign in db.query(Campaign).filter(Campaign.followup_enabled.is_(True)).all():
                try:
                    steps = {s.step_number: s for s in _ensure_default_steps(db, campaign)}
                    max_fu = getattr(campaign, "max_followups", None) or 3
                    due = [
                        r for r in (campaign.recipients or [])
                        if not getattr(r, "campaign_stopped", False)
                        and getattr(r, "active", True)
                        and getattr(r, "reply_status", "not_replied") == "not_replied"
                        and (getattr(r, "followup_count", 0) or 0) < max_fu
                        and r.next_followup_at is not None
                        and _as_utc(r.next_followup_at) <= _as_utc(now)
                    ]
                    for rec in due:
                        step_n = (rec.followup_count or 0) + 1
                        step = steps.get(step_n)
                        if step is not None and getattr(step, "enabled", True) is False:
                            continue
                        channels = _step_channels(step) if step else []
                        if not channels and getattr(campaign, "email_enabled", True) and rec.email:
                            channels = [("email", "", "")]
                        created = False
                        for ch, _s, _b in channels:
                            to = rec.email if ch == "email" else rec.mobile
                            if not to:
                                continue
                            msg = Message(
                                campaign_id=campaign.id,
                                recipient_id=rec.id,
                                channel=ch,
                                to_address=to,
                                recipient_name=rec.name,
                                status="queued",
                                is_followup=True,
                                followup_number=step_n,
                                sequence_step=f"step_{step_n}",
                            )
                            db.add(msg)
                            db.flush()
                            enqueue_message(msg.id)
                            total += 1
                            created = True
                        if not created:
                            continue
                        rec.followup_count = step_n
                        rec.last_followup_at = now.replace(tzinfo=None)
                        next_step = steps.get(step_n + 1)
                        if step_n < max_fu and (next_step is None or getattr(next_step, "enabled", True)):
                            delay = _delay_days(
                                next_step.delay_days if next_step else None,
                                getattr(campaign, "followup_interval_days", None),
                                3,
                            )
                            send_time = (next_step.send_time if next_step else None) or "10:00"
                            rec.next_followup_at = compute_next_send_at(now, delay, send_time)
                        else:
                            rec.next_followup_at = None
                    db.commit()
                except Exception:
                    db.rollback()
                    logger.exception("due followup tick failed campaign=%s", getattr(campaign, "id", "?"))
            if total:
                logger.info("followup tick: enqueued %s message(s)", total)
        finally:
            db.close()
    except Exception:
        logger.exception("followup tick error")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if sys.platform == "darwin":
        import multiprocessing
        multiprocessing.set_start_method("fork")
    logger.info("worker starting, queue=%s redis=%s platform=%s", QUEUE_NAME, settings.redis_url, sys.platform)
    import threading
    def _followup_loop():
        logger.info("sequence follow-up ticker started (every 30s)")
        while True:
            try:
                _run_due_followups_tick()
            except Exception:
                logger.exception("followup loop error")
            time.sleep(30)
    threading.Thread(target=_followup_loop, name="followup-tick", daemon=True).start()
    if sys.platform == "win32":
        from datetime import datetime, timezone as _tz
        from rq import SimpleWorker
        try:
            from rq.timeouts import TimerDeathPenalty
        except ImportError:
            class TimerDeathPenalty:
                def __init__(self, *a, **k): pass
                def __enter__(self): return self
                def __exit__(self, *a): return False
        class WindowsWorker(SimpleWorker):
            death_penalty_class = TimerDeathPenalty
        logger.info("using WindowsWorker (no fork) + follow-up ticker")
        w = WindowsWorker([send_queue], connection=redis_conn)
        w.death_penalty_class = TimerDeathPenalty
        w.work(with_scheduler=False)
    else:
        from rq import Worker
        Worker([send_queue], connection=redis_conn).work(with_scheduler=True)
