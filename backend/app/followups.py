"""Automated email follow-up sequences (Campaigns -> Follow-ups tab).

A campaign with FollowUpStep rows gets a FollowUpRun per recipient once the
original campaign email sends. `advance_followup_run` is the single piece of
logic that decides what happens next for a run -- it's called both from the
RQ timer job (`evaluate_followup_trigger`, scheduled via RQ's built-in
delayed-job support) and immediately whenever an engagement event lands
(`record_engagement_event`), so a trigger that's already satisfied doesn't
have to wait out a stale timer -- see the spec's "cancelled ... moves to
evaluating the next step's trigger" behavior.

There's no live tracking-pixel/click-redirect/inbound-reply capture yet --
`record_engagement_event` is fed by the "simulate event" endpoint
(routers/followups.py) as a stand-in until that infrastructure exists.
"""
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from .campaign_utils import _maybe_complete_campaign, enqueue_message, redis_conn, send_queue
from .models import Campaign, CampaignFollowUpSettings, FollowUpRun, FollowUpStep, Message, Recipient, Suppression
from .reply_classifier import classify_reply

logger = logging.getLogger(__name__)


def resolve_send_at(earliest: datetime, send_time: str | None, tz_name: str, skip_weekends: bool) -> datetime:
    """Given the earliest UTC instant a step's delay has elapsed, compute the
    actual send timestamp: rolled forward to `send_time` ("HH:MM", local to
    `tz_name`) if given, then pushed off Sat/Sun onto the next Monday at the
    same local time if `skip_weekends`. Returns a UTC datetime.

    There's no per-recipient timezone anywhere in the data model, so
    `tz_name` is the project's single configured timezone (Project.timezone)
    -- a known simplification vs. true per-recipient local time.
    """
    try:
        tz = ZoneInfo(tz_name or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    if earliest.tzinfo is None:
        earliest = earliest.replace(tzinfo=timezone.utc)
    local = earliest.astimezone(tz)

    if send_time:
        try:
            hh, mm = (int(p) for p in send_time.split(":", 1))
        except (ValueError, TypeError):
            hh = mm = None
        if hh is not None:
            candidate = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if candidate < local:
                candidate += timedelta(days=1)
            local = candidate

    if skip_weekends:
        while local.weekday() >= 5:  # 5=Saturday, 6=Sunday
            local += timedelta(days=1)

    return local.astimezone(timezone.utc)


def _settings_for(db: Session, campaign: Campaign) -> CampaignFollowUpSettings:
    settings = db.get(CampaignFollowUpSettings, campaign.id)
    if settings is None:
        settings = CampaignFollowUpSettings(campaign_id=campaign.id)
        db.add(settings)
        db.flush()
    return settings


def _channel_enabled(campaign: Campaign, channel: str) -> bool:
    return {
        "email": campaign.email_enabled,
        "whatsapp": campaign.whatsapp_enabled,
        "sms": campaign.sms_enabled,
    }.get(channel, False)


def _next_order(steps: dict[int, FollowUpStep], current: int) -> int | None:
    remaining = sorted(o for o in steps if o > current)
    return remaining[0] if remaining else None


def _touches_in_last_7_days(db: Session, campaign_id: int, recipient_id: int) -> int:
    since = datetime.now(timezone.utc) - timedelta(days=7)
    return db.query(Message).filter(
        Message.campaign_id == campaign_id, Message.recipient_id == recipient_id,
        Message.sent_at.isnot(None), Message.sent_at >= since,
    ).count()


def _tag_not_interested(db: Session, campaign: Campaign, recipient_id: int) -> None:
    from .routers.suppressions import normalize_contact
    recipient = db.get(Recipient, recipient_id)
    if recipient is None:
        return
    for contact, channel in ((recipient.email, "email"), (recipient.mobile, "whatsapp"), (recipient.mobile, "sms")):
        if not contact:
            continue
        normalized = normalize_contact(contact)
        exists = db.query(Suppression).filter_by(
            project_id=campaign.project_id, contact=normalized, channel=channel).first()
        if not exists:
            db.add(Suppression(project_id=campaign.project_id, contact=normalized, channel=channel,
                                reason="not_interested"))


def cancel_pending_job(run: FollowUpRun) -> None:
    """Cancels `run`'s pending timer job, if any. `evaluate_followup_trigger`
    already no-ops if the run is gone by the time a stale job fires, but
    callers that are about to delete a run (e.g. clearing prior runs on
    campaign resend) call this first to avoid leaving orphaned Redis jobs."""
    if not run.scheduled_job_id:
        return
    try:
        from rq.job import Job
        Job.fetch(run.scheduled_job_id, connection=redis_conn).cancel()
    except Exception:
        pass  # already gone/finished -- nothing to cancel


def _schedule(run: FollowUpRun, when: datetime) -> None:
    cancel_pending_job(run)
    job = send_queue.enqueue_at(when, evaluate_followup_trigger, run.id, job_timeout=60)
    run.scheduled_job_id = job.id


def maybe_start_run(db: Session, msg: Message) -> None:
    """Called after the *original* campaign email (msg.step_id is None) is
    sent -- kicks off this recipient's follow-up sequence if the campaign
    has any steps configured and one hasn't already been started.

    On a resend (msg.sent_run_number > 1), the prior run's FollowUpRun row
    for this recipient was archived and removed by
    app/campaign_resend.py::archive_campaign_history, so `existing` below
    would otherwise be None and a fresh run would auto-start every time --
    gated on CampaignFollowUpSettings.restart_on_resend (default False, see
    P0.5) so a resend doesn't silently re-run follow-ups unless that's been
    explicitly turned on for this campaign.
    """
    campaign = msg.campaign
    steps = campaign.followup_steps
    if not steps:
        return
    existing = db.query(FollowUpRun).filter_by(campaign_id=campaign.id, recipient_id=msg.recipient_id).first()
    if existing:
        return
    if msg.sent_run_number > 1 and not _settings_for(db, campaign).restart_on_resend:
        return
    run = FollowUpRun(campaign_id=campaign.id, recipient_id=msg.recipient_id,
                       next_step_order=steps[0].step_order, last_message_id=msg.id)
    db.add(run)
    db.flush()
    advance_followup_run(db, run)


def _trigger_condition_holds(step: FollowUpStep, last_message: Message) -> bool:
    """True if the step's reason for existing (nudging an unengaged
    recipient) still applies -- i.e. the recipient has NOT done the thing
    that would make this step redundant."""
    if step.trigger_type == "not_opened":
        return last_message.opened_at is None
    if step.trigger_type == "not_clicked":
        return last_message.clicked_at is None
    return last_message.replied_at is None  # no_reply


def _finish(db: Session, campaign_id: int) -> None:
    """Commits a run's terminal status and re-checks whether the campaign as
    a whole is now done. process_message's own calls to this same check
    (worker.py) only fire on the message-send path -- a run that terminates
    via a reply (routers/followups.py::simulate_event, ahead of the
    worker ever touching another message) needs this too, or the campaign
    stays stuck showing "sending" forever with nothing left pending."""
    db.commit()
    _maybe_complete_campaign(db, campaign_id)


def advance_followup_run(db: Session, run: FollowUpRun) -> None:
    locked = db.query(FollowUpRun).filter_by(id=run.id).with_for_update().first()
    if locked is None or locked.status != "active":
        return
    run = locked
    campaign = db.get(Campaign, run.campaign_id)
    if campaign is None:
        return
    settings = _settings_for(db, campaign)
    steps = {s.step_order: s for s in campaign.followup_steps}

    while True:
        last_message = db.get(Message, run.last_message_id) if run.last_message_id else None
        if last_message is None:
            run.status = "completed"
            _finish(db, campaign.id)
            return

        if last_message.reply_sentiment == "interested":
            run.status = "stopped_interested"
            _finish(db, campaign.id)
            return
        if last_message.reply_sentiment == "not_interested":
            run.status = "stopped_not_interested"
            if settings.negative_reply_handling == "tag_and_stop":
                _tag_not_interested(db, campaign, run.recipient_id)
            _finish(db, campaign.id)
            return

        step = steps.get(run.next_step_order) if run.next_step_order is not None else None
        if step is None:
            run.status = "completed"
            _finish(db, campaign.id)
            return

        if not _trigger_condition_holds(step, last_message):
            # Recipient already engaged the way this step exists to nudge --
            # cancel it and evaluate the next step against current state,
            # regardless of whether this step's own delay has elapsed yet
            # (spec: an early-satisfied condition cancels the step outright,
            # it doesn't just get re-checked once the timer catches up).
            run.next_step_order = _next_order(steps, step.step_order)
            continue

        earliest = last_message.sent_at or datetime.now(timezone.utc)
        if earliest.tzinfo is None:
            earliest = earliest.replace(tzinfo=timezone.utc)
        delay = timedelta(**{step.delay_unit: step.delay_value})
        target = resolve_send_at(earliest + delay, step.send_time or settings.default_send_time,
                                  campaign.project.timezone, settings.skip_weekends)
        now = datetime.now(timezone.utc)
        if now < target:
            _schedule(run, target)
            db.commit()
            return

        if _touches_in_last_7_days(db, campaign.id, run.recipient_id) >= settings.max_touches_per_week:
            _schedule(run, now + timedelta(days=1))
            db.commit()
            return

        recipient = db.get(Recipient, run.recipient_id)
        channel = (step.fallback_channel if step.fallback_channel and _channel_enabled(campaign, step.fallback_channel)
                   else step.primary_channel)
        new_msg = Message(
            campaign_id=campaign.id, recipient_id=recipient.id, channel=channel, step_id=step.id,
            to_address=recipient.email if channel == "email" else recipient.mobile,
            recipient_name=recipient.name, status="queued", sent_run_number=campaign.current_send_run,
        )
        db.add(new_msg)
        db.flush()

        enqueue_message(new_msg.id)

        run.last_message_id = new_msg.id
        run.next_step_order = _next_order(steps, step.step_order)
        run.scheduled_job_id = None
        db.commit()
        # loop again to schedule/evaluate the next step off the new send


def evaluate_followup_trigger(run_id: int) -> None:
    """RQ job: fires when a step's delay window has elapsed (see
    `_schedule` above). Re-checks the trigger condition and either sends,
    skips ahead, or reschedules -- see `advance_followup_run`."""
    from .database import SessionLocal
    logger.info("followup run %s: timer fired", run_id)
    db = SessionLocal()
    try:
        run = db.get(FollowUpRun, run_id)
        if run is None:
            logger.info("followup run %s: no longer exists, skipping", run_id)
            return
        advance_followup_run(db, run)
    finally:
        db.close()


def record_engagement_event(db: Session, message_id: int, event: str, reply_text: str | None = None,
                             source: str = "simulated") -> Message:
    """Records opened/clicked/replied on a Message. The single code path
    behind both fabricated QA/demo activity (routers/followups.py::
    simulate_event, source="simulated") and real capture (the tracking-pixel
    and click-redirect routes in routers/tracking_pixel.py, source="real";
    the inbound-reply webhook once it exists) -- trigger evaluation, reply
    classification and the stop/tag logic below must behave identically
    regardless of where the event came from.

    Immediately re-evaluates the owning FollowUpRun so an early-satisfied
    trigger doesn't wait on a stale timer.
    """
    msg = db.get(Message, message_id)
    if msg is None:
        raise ValueError(f"message {message_id} not found")

    now = datetime.now(timezone.utc)
    changed = False
    if event == "opened":
        if msg.opened_at is None:
            msg.opened_at = now
            changed = True
    elif event == "clicked":
        if msg.clicked_at is None:
            msg.clicked_at = now
            changed = True
        if msg.opened_at is None:
            msg.opened_at = now  # a click implies an open
            changed = True
    elif event == "replied":
        msg.replied_at = msg.replied_at or now
        msg.reply_text = (reply_text or "")[:2000]
        msg.reply_sentiment = classify_reply(reply_text or "")
        changed = True
    else:
        raise ValueError(f"unknown event type: {event}")

    if not changed:
        # Nothing new -- e.g. a mail client re-fetching the open pixel on a
        # message already marked opened. Skip the write and the follow-up
        # re-evaluation below; there's no new state for it to react to.
        return msg

    if msg.engagement_source != "simulated":
        # Sticky once fabricated: a real event landing on a message Simulate
        # already touched must not un-taint it for the real-metrics rollups
        # that filter on this field (routers/followups.py::_step_stats).
        msg.engagement_source = source
    db.commit()

    run = db.query(FollowUpRun).filter_by(campaign_id=msg.campaign_id, recipient_id=msg.recipient_id).first()
    if run and run.last_message_id == msg.id and run.status == "active":
        advance_followup_run(db, run)
    return msg
