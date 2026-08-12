import logging
import re

from redis import Redis
from rq import Queue, Retry
from sqlalchemy import update

from .config import settings
from .models import Campaign, FollowUpRun, FollowUpStep, Message

logger = logging.getLogger(__name__)

PLACEHOLDER = re.compile(r"\{\{\s*([\w ]+?)\s*\}\}")

# Queue setup and the handful of helpers below are shared between worker.py
# (the RQ worker process) and followups.py (the follow-up engine). Both need
# each other -- worker.py runs the initial blast and kicks off a recipient's
# follow-up sequence once it sends; followups.py schedules/enqueues its own
# step sends and needs to re-check campaign completion after a run finishes
# via a reply, not just a message send. Since worker.py imports followups.py
# at module level, anything followups.py needed back from worker.py used to
# require a deferred (function-body) import to dodge the cycle. Living here
# instead -- a module neither of them needs to import the other for -- lets
# both sides use plain top-level imports.
QUEUE_NAME = "sends"

redis_conn = Redis.from_url(settings.redis_url)
send_queue = Queue(QUEUE_NAME, connection=redis_conn)


def enqueue_message(message_id: int) -> None:
    # Referenced by import path rather than the live `process_message`
    # function object -- RQ stores jobs this way regardless (it resolves the
    # path fresh in whatever process runs the job), and passing the string
    # directly avoids importing worker.py here, which would recreate the
    # cycle this module exists to break.
    job = send_queue.enqueue(
        "app.worker.process_message", message_id,
        retry=Retry(max=settings.send_max_retries, interval=[10, 30, 60]),
        job_timeout=60,
    )
    logger.info("message %s: enqueued as job %s", message_id, job.id)


def _maybe_complete_campaign(db, campaign_id: int) -> bool:
    """Marks `campaign_id` completed once every Message row has resolved and
    no follow-up run is still active. Returns True only if this call is the
    one that actually performed the transition.

    Uses a conditional `UPDATE ... WHERE status='sending'` rather than
    read-then-write: two workers finishing the campaign's last two messages
    concurrently can both observe remaining==0 and both reach this point, but
    the UPDATE's WHERE clause only matches (and its row lock only grants) for
    whichever one commits first -- the second finds the row already flipped
    and affects zero rows. Any future post-completion side effect (e.g. a
    notification) must gate on the return value, not just call this and
    proceed, or it would double-fire under the same race.
    """
    remaining = db.query(Message).filter(
        Message.campaign_id == campaign_id, Message.status.in_(("queued", "processing"))
    ).count()
    # A campaign with a still-running follow-up sequence isn't "done" just
    # because the initial blast finished -- future steps haven't been
    # enqueued as Message rows yet (they're created lazily as each step
    # fires), so they wouldn't show up in the `remaining` count above.
    active_followups = db.query(FollowUpRun).filter_by(campaign_id=campaign_id, status="active").count()
    if remaining != 0 or active_followups != 0:
        return False
    result = db.execute(
        update(Campaign).where(Campaign.id == campaign_id, Campaign.status == "sending")
        .values(status="completed")
    )
    db.commit()
    completed = result.rowcount == 1
    if completed:
        logger.info("campaign %s: all messages resolved, marked completed", campaign_id)
    return completed


def message_template(db, msg: Message) -> tuple[str, str]:
    """(subject_template, body_template) for `msg` -- the campaign's
    per-channel content for the original blast, or the FollowUpStep's
    content for a follow-up send. Shared between the send path (worker.py,
    which renders and sends it) and the click-redirect route
    (routers/tracking_pixel.py, which re-renders it to recompute the same
    set of URLs as an allowlist) so both resolve the exact same content a
    message actually carries.
    """
    if msg.step_id:
        step = db.get(FollowUpStep, msg.step_id)
        return (step.subject, step.body_template) if step else ("", "")
    content = next((c for c in msg.campaign.contents if c.channel == msg.channel), None)
    return (content.subject, content.body) if content else ("", "")


def render_template(template: str, data: dict, missing: list | None = None) -> str:
    """Substitute {{Key}} placeholders (case-insensitive) from data.

    If `missing` is passed, unresolved placeholders are blanked out (rather than
    left as literal `{{Key}}` text) and their names are appended to `missing` --
    used on the send path so a stray/unknown placeholder never reaches the
    recipient. Without `missing`, unresolved placeholders are left untouched,
    which is friendlier while an admin is still drafting content.
    """
    def repl(m):
        key = m.group(1).strip()
        for k, v in data.items():
            if k.lower() == key.lower():
                return str(v)
        if missing is not None:
            missing.append(key)
            return ""
        return m.group(0)
    return PLACEHOLDER.sub(repl, template or "")


def valid_email(e: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", e or ""))


def valid_mobile(m: str) -> bool:
    digits = re.sub(r"\D", "", m or "")
    return len(digits) >= 8
