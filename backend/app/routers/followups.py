from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import followups as followup_engine
from ..database import get_db
from ..models import Campaign, CampaignFollowUpSettings, FollowUpStep, Message, Project, User
from ..schemas import (
    CampaignFollowUpSettingsIn, CampaignFollowUpSettingsOut,
    FollowUpStepIn, FollowUpStepMoveIn, FollowUpStepOut, FollowUpStepStats, MessageOut, SimulateEventIn,
)
from ..deps import require, get_current_user, user_permissions

router = APIRouter(prefix="/api", tags=["followups"])


def _get_campaign(db: Session, campaign_id: int, user: User) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    project: Project = campaign.project
    perms = user_permissions(user)
    see_all = "user.manage" in perms or "system.configure" in perms
    if not see_all and project.id not in {p.id for p in user.projects}:
        raise HTTPException(status_code=403, detail="No access to this campaign")
    return campaign


def _step_stats(db: Session, step_id: int) -> FollowUpStepStats:
    """A read-only, filtered rollup of the same Message rows Tracking &
    Reports reads from -- never an independently maintained counter, so the
    two views can't drift apart. Rows tainted by Simulate (engagement_source
    == 'simulated') are dropped from the whole rollup, numerator and
    denominator alike, so QA/demo activity on a test campaign never leaks
    into these numbers. `.is_distinct_from` (rather than `!=`) is required
    here because plain `!=` against NULL is NULL in SQL, which would
    silently exclude every real (non-simulated, NULL) row too."""
    base = db.query(Message).filter(
        Message.step_id == step_id, Message.engagement_source.is_distinct_from("simulated"))
    sent = base.filter(Message.sent_at.isnot(None)).count()
    if sent == 0:
        return FollowUpStepStats(sent=0)
    opened = base.filter(Message.opened_at.isnot(None)).count()
    clicked = base.filter(Message.clicked_at.isnot(None)).count()
    replied = base.filter(Message.replied_at.isnot(None)).count()
    return FollowUpStepStats(
        sent=sent, open_rate=round(100 * opened / sent, 1),
        click_rate=round(100 * clicked / sent, 1), reply_rate=round(100 * replied / sent, 1),
    )


def _step_out(db: Session, step: FollowUpStep) -> FollowUpStepOut:
    out = FollowUpStepOut.model_validate(step)
    out.stats = _step_stats(db, step.id)
    return out


@router.get("/campaigns/{campaign_id}/followups/settings", response_model=CampaignFollowUpSettingsOut)
def get_settings(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = _get_campaign(db, campaign_id, user)
    settings = db.get(CampaignFollowUpSettings, campaign.id)
    if settings is None:
        settings = CampaignFollowUpSettings(campaign_id=campaign.id)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


@router.put("/campaigns/{campaign_id}/followups/settings", response_model=CampaignFollowUpSettingsOut)
def update_settings(campaign_id: int, body: CampaignFollowUpSettingsIn, db: Session = Depends(get_db),
                     user: User = Depends(require("content.edit"))):
    campaign = _get_campaign(db, campaign_id, user)
    settings = db.get(CampaignFollowUpSettings, campaign.id)
    if settings is None:
        settings = CampaignFollowUpSettings(campaign_id=campaign.id)
        db.add(settings)
    for k, v in body.model_dump().items():
        setattr(settings, k, v)
    db.commit()
    db.refresh(settings)
    return settings


@router.get("/campaigns/{campaign_id}/followups/steps", response_model=list[FollowUpStepOut])
def list_steps(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    campaign = _get_campaign(db, campaign_id, user)
    return [_step_out(db, s) for s in campaign.followup_steps]


@router.post("/campaigns/{campaign_id}/followups/steps", response_model=FollowUpStepOut)
def create_step(campaign_id: int, body: FollowUpStepIn, db: Session = Depends(get_db),
                 user: User = Depends(require("content.edit"))):
    campaign = _get_campaign(db, campaign_id, user)
    next_order = max((s.step_order for s in campaign.followup_steps), default=0) + 1
    step = FollowUpStep(campaign_id=campaign.id, step_order=next_order, **body.model_dump())
    db.add(step)
    db.commit()
    db.refresh(step)
    return _step_out(db, step)


@router.put("/campaigns/{campaign_id}/followups/steps/{step_id}", response_model=FollowUpStepOut)
def update_step(campaign_id: int, step_id: int, body: FollowUpStepIn, db: Session = Depends(get_db),
                 user: User = Depends(require("content.edit"))):
    campaign = _get_campaign(db, campaign_id, user)
    step = db.get(FollowUpStep, step_id)
    if not step or step.campaign_id != campaign.id:
        raise HTTPException(status_code=404, detail="Follow-up step not found")
    for k, v in body.model_dump().items():
        setattr(step, k, v)
    db.commit()
    db.refresh(step)
    return _step_out(db, step)


@router.delete("/campaigns/{campaign_id}/followups/steps/{step_id}")
def delete_step(campaign_id: int, step_id: int, db: Session = Depends(get_db),
                 user: User = Depends(require("content.edit"))):
    campaign = _get_campaign(db, campaign_id, user)
    step = db.get(FollowUpStep, step_id)
    if not step or step.campaign_id != campaign.id:
        raise HTTPException(status_code=404, detail="Follow-up step not found")
    db.delete(step)
    db.commit()
    # Compact step_order so the sequence stays contiguous (1..N) after a
    # mid-sequence delete -- the frontend's up/down reordering assumes that.
    remaining = sorted(campaign.followup_steps, key=lambda s: s.step_order)
    for i, s in enumerate(remaining, start=1):
        s.step_order = i
    db.commit()
    return {"ok": True}


@router.post("/campaigns/{campaign_id}/followups/steps/{step_id}/move", response_model=list[FollowUpStepOut])
def move_step(campaign_id: int, step_id: int, body: FollowUpStepMoveIn, db: Session = Depends(get_db),
               user: User = Depends(require("content.edit"))):
    campaign = _get_campaign(db, campaign_id, user)
    step = db.get(FollowUpStep, step_id)
    if not step or step.campaign_id != campaign.id:
        raise HTTPException(status_code=404, detail="Follow-up step not found")
    ordered = sorted(campaign.followup_steps, key=lambda s: s.step_order)
    idx = next(i for i, s in enumerate(ordered) if s.id == step.id)
    swap_idx = idx - 1 if body.direction == "up" else idx + 1
    if swap_idx < 0 or swap_idx >= len(ordered):
        raise HTTPException(status_code=400, detail="Step is already at that end of the sequence")
    other = ordered[swap_idx]

    # Swap step_order via a temporary value -- the unique (campaign_id,
    # step_order) index isn't deferrable, so writing both new values in one
    # naive pass would collide mid-transaction.
    a, b = step.step_order, other.step_order
    step.step_order = -1
    db.flush()
    other.step_order = a
    db.flush()
    step.step_order = b
    db.commit()

    fresh = db.query(FollowUpStep).filter_by(campaign_id=campaign.id).order_by(FollowUpStep.step_order).all()
    return [_step_out(db, s) for s in fresh]


@router.post("/campaigns/{campaign_id}/followups/messages/{message_id}/simulate", response_model=MessageOut)
def simulate_event(campaign_id: int, message_id: int, body: SimulateEventIn, db: Session = Depends(get_db),
                    user: User = Depends(require("content.edit"))):
    """Stands in for real engagement capture (no tracking pixel, click
    redirect, or inbound reply webhook exists yet) -- records an open/click/
    reply on a message and immediately re-evaluates its follow-up sequence,
    so this is how the follow-up engine gets tested/demoed end to end today.
    Meant to be replaced by real tracking infrastructure later."""
    campaign = _get_campaign(db, campaign_id, user)
    if not campaign.is_test_campaign:
        # Engagement fields also drive live trigger logic (see
        # app/followups.py) -- letting Simulate write to a real campaign's
        # Message rows would corrupt both reporting and follow-up behavior
        # for actual recipients, with no way to tell a fabricated event from
        # a genuine one afterward. Only test/sandbox campaigns may use it.
        raise HTTPException(status_code=403,
                             detail="Simulate is only available on test campaigns")
    msg = db.get(Message, message_id)
    if not msg or msg.campaign_id != campaign.id:
        raise HTTPException(status_code=404, detail="Message not found")
    return followup_engine.record_engagement_event(db, message_id, body.event, body.reply_text)
