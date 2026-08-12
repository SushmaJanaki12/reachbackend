"""Archives a campaign's live Message/FollowUpRun rows before a resend
clears the live tables for a fresh run (P0.5, revised 2026-08-11: resend is
now allowed repeatedly rather than blocked outright after the first send,
provided nothing already recorded is lost in the process).

Called from routers/campaigns.py::send_campaign whenever /send is hit on a
campaign that already has Message rows.
"""
from sqlalchemy.orm import Session

from .followups import cancel_pending_job
from .models import Campaign, FollowUpRun, FollowUpRunHistory, Message, MessageHistory


def archive_campaign_history(db: Session, campaign: Campaign) -> int:
    """Copies every live Message/FollowUpRun row belonging to `campaign` into
    its -History counterpart, tagged with the send-run number they belonged
    to, then clears the live tables and bumps the campaign onto the next run
    number. Returns the new `current_send_run`.

    Everything here happens inside the caller's still-open transaction and
    only commits once, at the end -- a failure partway through (anything
    raised before that commit) leaves the live rows completely untouched
    once the caller rolls back; nothing is half-archived.
    """
    run_number = campaign.current_send_run

    messages = db.query(Message).filter_by(campaign_id=campaign.id).all()
    for m in messages:
        db.add(MessageHistory(
            campaign_id=campaign.id, sent_run_number=run_number, recipient_id=m.recipient_id,
            channel=m.channel, to_address=m.to_address, recipient_name=m.recipient_name,
            status=m.status, provider_id=m.provider_id, error=m.error, warnings=m.warnings,
            sent_at=m.sent_at, delivered_at=m.delivered_at, read_at=m.read_at,
            tracking_token=m.tracking_token, step_id=m.step_id,
            opened_at=m.opened_at, clicked_at=m.clicked_at, replied_at=m.replied_at,
            reply_text=m.reply_text, reply_sentiment=m.reply_sentiment,
            engagement_source=m.engagement_source,
        ))

    runs = db.query(FollowUpRun).filter_by(campaign_id=campaign.id).all()
    for r in runs:
        # Cancel any pending RQ timer before the row disappears -- otherwise
        # evaluate_followup_trigger fires later against a run id that no
        # longer exists (harmless no-op, see followups.py, but a leaked job
        # left sitting in Redis for no reason).
        cancel_pending_job(r)
        db.add(FollowUpRunHistory(
            campaign_id=campaign.id, sent_run_number=run_number, recipient_id=r.recipient_id,
            status=r.status, next_step_order=r.next_step_order,
        ))

    db.query(FollowUpRun).filter_by(campaign_id=campaign.id).delete()
    db.query(Message).filter_by(campaign_id=campaign.id).delete()

    campaign.current_send_run = run_number + 1
    db.commit()
    return campaign.current_send_run
