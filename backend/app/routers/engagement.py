from pydantic import BaseModel
"""AI content generation + recipient engagement / follow-up sequence APIs."""
from datetime import datetime, timedelta, timezone

import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require, user_permissions
from ..models import Campaign, CampaignContent, CampaignSequenceStep, Message, Project, Recipient, User
from ..schemas import (
    AiGenerateIn, AiGenerateOut, EngagementUpdateIn, FollowupSettingsIn,
    RecipientEngagementOut, ContentOut, SequenceStepIn, SequenceStepOut, SequenceStepsBulkIn,
)
from ..ai_content import generate_message, score_generated_content, validate_goal_with_ai, ensure_score_90, improve_message

router = APIRouter(prefix="/api", tags=["engagement"])


def _parse_send_time(send_time: str) -> tuple[int, int]:
    raw = (send_time or "10:00").strip()
    try:
        parts = raw.split(":")
        h = max(0, min(23, int(parts[0])))
        m = max(0, min(59, int(parts[1]))) if len(parts) > 1 else 0
        return h, m
    except Exception:
        return 10, 0



IST = timezone(timedelta(hours=5, minutes=30))


def _as_utc(dt: datetime) -> datetime:
    if dt is None:
        return dt
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _delay_days(step_delay, campaign_interval, default: int = 3) -> int:
    if step_delay is not None:
        return max(0, int(step_delay))
    if campaign_interval is not None:
        return max(0, int(campaign_interval))
    return default


def compute_next_send_at(from_dt: datetime, delay_days: int, send_time: str) -> datetime:
    """HH:MM is India time (IST). Returns naive UTC for DB."""
    from_dt = _as_utc(from_dt)
    h, mnt = _parse_send_time(send_time)
    from_ist = from_dt.astimezone(IST)
    days = max(0, int(delay_days if delay_days is not None else 0))
    target_date = (from_ist + timedelta(days=days)).date()
    target_ist = datetime(target_date.year, target_date.month, target_date.day, h, mnt, 0, tzinfo=IST)
    target_utc = target_ist.astimezone(timezone.utc)
    if target_utc <= from_dt:
        target_ist = target_ist + timedelta(days=1)
        target_utc = target_ist.astimezone(timezone.utc)
    return target_utc.replace(tzinfo=None)



def _step_channels(step: CampaignSequenceStep) -> list[tuple[str, str, str]]:
    """Return list of (channel, subject, body) enabled on this step."""
    out = []
    email_on = getattr(step, "email_enabled", None)
    wa_on = getattr(step, "whatsapp_enabled", None)
    sms_on = getattr(step, "sms_enabled", None)
    if email_on is None and wa_on is None and sms_on is None:
        ch = (step.channel or "email").lower()
        subj = step.subject or ""
        body = step.body or ""
        if ch == "email":
            out.append(("email", subj, body))
        elif ch == "whatsapp":
            out.append(("whatsapp", "", body))
        elif ch == "sms":
            out.append(("sms", "", body))
        return out
    if email_on and (step.email_subject or step.email_body or step.subject or step.body):
        out.append(("email", step.email_subject or step.subject or "", step.email_body or step.body or ""))
    elif email_on:
        out.append(("email", step.email_subject or "", step.email_body or ""))
    if wa_on and (step.whatsapp_body or "").strip():
        out.append(("whatsapp", "", step.whatsapp_body))
    if sms_on and (step.sms_body or "").strip():
        out.append(("sms", "", step.sms_body))
    return out


def _campaign_or_404(db: Session, campaign_id: int, user: User) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    perms = user_permissions(user)
    see_all = "user.manage" in perms or "system.configure" in perms
    if not see_all and campaign.project_id not in {p.id for p in user.projects}:
        raise HTTPException(status_code=403, detail="No access to this project")
    return campaign


@router.post("/campaigns/{campaign_id}/ai/generate", response_model=AiGenerateOut)
def ai_generate(campaign_id: int, payload: AiGenerateIn, db: Session = Depends(get_db),
                user: User = Depends(require("content.edit"))):
    """Generate inbox-friendly email / WhatsApp / SMS copy for the campaign."""
    campaign = _campaign_or_404(db, campaign_id, user)
    project = db.get(Project, campaign.project_id)

    goal = payload.goal or campaign.ai_goal or campaign.description or campaign.name
    tone = payload.tone or campaign.ai_tone or "professional"
    company = payload.company or (project.name if project else "")
    sender = payload.sender_name or (project.sender_name if project else "")
    product = payload.product or campaign.name

    # AI validates goal meaning (not length) before generate or score
    ok, reason = validate_goal_with_ai(
        goal,
        campaign_name=campaign.name or "",
        product=product or company or "",
    )
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    draft = generate_message(
        channel=payload.channel,
        goal=goal,
        tone=tone,
        product=product,
        sender_name=sender,
        company=company,
        followup_number=payload.followup_number,
        extra_context=payload.extra_context,
    )

    draft, score = ensure_score_90(
        channel=payload.channel,
        subject=draft.get("subject") or "",
        body=draft.get("body") or "",
        goal=goal,
        tone=tone,
        max_passes=2,
    )
    draft.setdefault("tone", tone)
    draft.setdefault("goal", goal)
    draft.setdefault("followup_number", payload.followup_number)

    if payload.save_to_campaign:
        ch = payload.channel
        content = db.query(CampaignContent).filter_by(campaign_id=campaign.id, channel=ch).first()
        if not content:
            content = CampaignContent(campaign_id=campaign.id, channel=ch)
            db.add(content)
        content.subject = draft.get("subject") or ""
        content.body = draft.get("body") or ""
        content.content_mode = "plain"
        content.template_fields = {}
        campaign.ai_goal = goal
        campaign.ai_tone = tone

        step_n = int(payload.followup_number or 0)
        step = (
            db.query(CampaignSequenceStep)
            .filter_by(campaign_id=campaign.id, step_number=step_n)
            .first()
        )
        if not step:
            default_delay = 0 if step_n == 0 else _delay_days(None, campaign.followup_interval_days, 3)
            labels = {0: "First touch", 1: "Follow-up 1", 2: "Follow-up 2", 3: "Follow-up 3"}
            step = CampaignSequenceStep(
                campaign_id=campaign.id,
                step_number=step_n,
                label=labels.get(step_n, f"Step {step_n}"),
                delay_days=default_delay,
                send_time="10:00",
                channel=ch,
            )
            db.add(step)
        step.enabled = True
        step.channel = ch
        body = draft.get("body") or ""
        subj = draft.get("subject") or ""
        if ch == "email":
            step.email_enabled = True
            step.email_subject = subj
            step.email_body = body
            step.subject = subj
            step.body = body
        elif ch == "whatsapp":
            step.whatsapp_enabled = True
            step.whatsapp_body = body
        elif ch == "sms":
            step.sms_enabled = True
            step.sms_body = body
        db.commit()

    return AiGenerateOut(
        channel=draft["channel"],
        subject=draft.get("subject") or "",
        body=draft.get("body") or "",
        tone=tone,
        goal=goal,
        followup_number=payload.followup_number,
        source=draft.get("source") or "template",
        inbox_tips=draft.get("inbox_tips") or [],
        score=score,
    )



@router.post("/campaigns/{campaign_id}/ai/improve", response_model=AiGenerateOut)
def ai_improve(campaign_id: int, payload: AiGenerateIn, db: Session = Depends(get_db),
               user: User = Depends(require("content.edit"))):
    """Rewrite current subject/body toward a 90-100 non-spammy score."""
    from ..ai_content import improve_message, score_generated_content

    campaign = _campaign_or_404(db, campaign_id, user)
    goal = payload.goal or campaign.ai_goal or campaign.description or campaign.name
    tone = payload.tone or campaign.ai_tone or "professional"
    ch = (payload.channel or "email").lower()

    cur_subject, cur_body = "", ""
    try:
        blob = json.loads(payload.extra_context or "")
        if isinstance(blob, dict):
            cur_subject = blob.get("subject") or ""
            cur_body = blob.get("body") or ""
    except Exception:
        content = db.query(CampaignContent).filter_by(campaign_id=campaign.id, channel=ch).first()
        if content:
            cur_subject = content.subject or ""
            cur_body = content.body or ""

    prev_score = None
    prev_issues = []
    prev_recs = []
    try:
        blob2 = json.loads(payload.extra_context or "")
        if isinstance(blob2, dict):
            prev_score = blob2.get("score")
            prev_issues = blob2.get("issues") or []
            prev_recs = blob2.get("recommendations") or blob2.get("improvement_suggestions") or []
    except Exception:
        pass

    improved = improve_message(
        channel=ch,
        subject=cur_subject,
        body=cur_body,
        goal=goal,
        tone=tone,
        current_score=prev_score if isinstance(prev_score, int) else None,
        issues=prev_issues,
        recommendations=prev_recs,
    )
    score = score_generated_content(
        channel=ch,
        subject=improved.get("subject") or "",
        body=improved.get("body") or "",
        email_enabled=ch == "email",
        whatsapp_enabled=ch == "whatsapp",
        sms_enabled=ch == "sms",
        goal=goal,
    )
    if payload.save_to_campaign:
        row = db.query(CampaignContent).filter_by(campaign_id=campaign.id, channel=ch).first()
        if not row:
            row = CampaignContent(campaign_id=campaign.id, channel=ch)
            db.add(row)
        row.subject = improved.get("subject") or ""
        row.body = improved.get("body") or ""
        row.content_mode = "plain"
        row.template_fields = {}
        db.commit()

    return AiGenerateOut(
        channel=ch,
        subject=improved.get("subject") or "",
        body=improved.get("body") or "",
        tone=tone,
        goal=goal or "",
        followup_number=int(payload.followup_number or 0),
        source=improved.get("source") or "openai_improve",
        inbox_tips=list(improved.get("changes_made") or []),
        score=score,
    )




@router.post("/campaigns/{campaign_id}/ai/score", response_model=AiGenerateOut)
def ai_score_content(campaign_id: int, payload: AiGenerateIn, db: Session = Depends(get_db),
                     user: User = Depends(require("content.edit"))):
    """Score user-written or editor content + return improvement suggestions."""
    campaign = _campaign_or_404(db, campaign_id, user)
    goal = payload.goal or campaign.ai_goal or campaign.description or campaign.name
    tone = payload.tone or campaign.ai_tone or "professional"
    ch = (payload.channel or "email").lower()

    cur_subject, cur_body = "", ""
    try:
        blob = json.loads(payload.extra_context or "")
        if isinstance(blob, dict):
            cur_subject = blob.get("subject") or ""
            cur_body = blob.get("body") or ""
    except Exception:
        content = db.query(CampaignContent).filter_by(campaign_id=campaign.id, channel=ch).first()
        if content:
            cur_subject = content.subject or ""
            cur_body = content.body or ""

    score = score_generated_content(
        channel=ch,
        subject=cur_subject,
        body=cur_body,
        email_enabled=ch == "email",
        whatsapp_enabled=ch == "whatsapp",
        sms_enabled=ch == "sms",
        goal=goal,
    )
    return AiGenerateOut(
        channel=ch,
        subject=cur_subject,
        body=cur_body,
        tone=tone,
        goal=goal or "",
        followup_number=int(payload.followup_number or 0),
        source="user_content",
        inbox_tips=list(score.get("inbox_tips") or []),
        score=score,
    )


class SaveTemplateIn(BaseModel):
    name: str = ""
    channel: str = "email"
    subject: str = ""
    body: str = ""
    description: str = ""
    publish: bool = True


@router.post("/campaigns/{campaign_id}/ai/save-template")
def save_ai_as_template(campaign_id: int, payload: SaveTemplateIn, db: Session = Depends(get_db),
                        user: User = Depends(require("template.edit"))):
    """Save AI / editor copy into the Templates library for future campaigns."""
    from ..models import Template, EmailTemplateContent, WhatsappTemplateContent

    campaign = _campaign_or_404(db, campaign_id, user)
    ch = (payload.channel or "email").lower()
    if ch not in ("email", "whatsapp"):
        raise HTTPException(status_code=400, detail="Only email and WhatsApp can be saved to Templates")

    name = (payload.name or "").strip() or f"{campaign.name or 'Campaign'} — {ch}"
    subject = (payload.subject or "").strip()
    body = (payload.body or "").strip()
    if ch == "whatsapp" and not body:
        raise HTTPException(status_code=400, detail="Body is required")
    if ch == "email" and not subject and not body:
        raise HTTPException(status_code=400, detail="Subject or body is required")

    tpl = Template(
        name=name[:200],
        description=(payload.description or f"Saved from campaign AI draft #{campaign_id}")[:500],
        channel=ch,
        created_by=user.id,
        status="published" if payload.publish else "draft",
    )
    db.add(tpl)
    db.flush()

    if ch == "email":
        # Production-ready branded layout from plain campaign copy
        subj = subject or name[:120]
        # Headline = subject (clean, no ALL CAPS spam)
        headline = subj[:80]
        # Opening = full body (what the recipient reads)
        opening = body[:4000] if body else ""
        fields = {
            "headline": headline,
            "opening_line": opening,
            "show_bullets": False,
            "campaign_name": campaign.name or "",
            "bullets": [],
            "show_callout": False,
            "callout_label": "",
            "callout_text": "",
            "show_cta": True,
            "action_url": "",
            "action_label": "Reply",
            "show_badges": False,
            "show_secondary": False,
            "secondary_action_url": "",
            "secondary_action_label": "",
        }
        db.add(EmailTemplateContent(
            template_id=tpl.id,
            subject=subj,
            fields=fields,
            # Remember plain body so "Use template" can load as editable plain text
            branding_override={
                "source": "campaign_plain",
                "plain_subject": subj,
                "plain_body": opening,
            },
        ))
    else:
        db.add(WhatsappTemplateContent(
            template_id=tpl.id,
            meta_template_name=(name[:100] or "reach_ai_draft"),
            meta_template_id="",
            language_code="en",
            header_type="none",
            header_content="",
            body_text=body[:4000],
            footer_text="",
            buttons=[],
        ))

    db.commit()
    db.refresh(tpl)
    return {"ok": True, "template_id": tpl.id, "name": tpl.name, "status": tpl.status, "channel": tpl.channel}


@router.put("/campaigns/{campaign_id}/followup-settings")
def update_followup_settings(campaign_id: int, payload: FollowupSettingsIn,
                             db: Session = Depends(get_db),
                             user: User = Depends(require("content.edit"))):
    campaign = _campaign_or_404(db, campaign_id, user)
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(campaign, k, v)
    if data.get("warmup_enabled") is True and not campaign.warmup_started_at:
        campaign.warmup_started_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "followup_enabled": campaign.followup_enabled,
        "followup_interval_days": campaign.followup_interval_days,
        "max_followups": campaign.max_followups,
        "ai_goal": campaign.ai_goal,
        "ai_tone": campaign.ai_tone,
        "warmup_enabled": campaign.warmup_enabled,
        "warmup_daily_cap": campaign.warmup_daily_cap,
        "warmup_started_at": campaign.warmup_started_at.isoformat() if campaign.warmup_started_at else None,
    }


@router.get("/campaigns/{campaign_id}/engagement", response_model=list[RecipientEngagementOut])
def list_engagement(campaign_id: int, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    campaign = _campaign_or_404(db, campaign_id, user)
    return campaign.recipients


@router.patch("/campaigns/{campaign_id}/recipients/{recipient_id}/engagement",
              response_model=RecipientEngagementOut)
def update_engagement(campaign_id: int, recipient_id: int, payload: EngagementUpdateIn,
                      db: Session = Depends(get_db),
                      user: User = Depends(require("campaign.edit"))):
    campaign = _campaign_or_404(db, campaign_id, user)
    rec = db.get(Recipient, recipient_id)
    if not rec or rec.campaign_id != campaign.id:
        raise HTTPException(status_code=404, detail="Recipient not found")

    if payload.reply_status is not None:
        if payload.reply_status not in ("not_replied", "replied"):
            raise HTTPException(status_code=400, detail="Invalid reply_status")
        rec.reply_status = payload.reply_status

    if payload.interest_status is not None:
        if payload.interest_status not in ("none", "interested", "not_interested"):
            raise HTTPException(status_code=400, detail="Invalid interest_status")
        rec.interest_status = payload.interest_status

    if payload.call_scheduled_at is not None:
        rec.call_scheduled_at = payload.call_scheduled_at
    if payload.call_notes is not None:
        rec.call_notes = payload.call_notes

    if rec.reply_status == "replied" and rec.interest_status == "not_interested":
        rec.campaign_stopped = True
        rec.stop_reason = "not_interested"
        rec.active = False
        rec.next_followup_at = None
    elif rec.reply_status == "replied" and rec.interest_status == "interested":
        rec.campaign_stopped = False
        rec.stop_reason = ""
        rec.next_followup_at = None
    elif rec.reply_status == "not_replied" and not rec.campaign_stopped:
        if campaign.followup_enabled and rec.followup_count < campaign.max_followups:
            days = _delay_days(None, campaign.followup_interval_days, 3)
            rec.next_followup_at = datetime.now(timezone.utc) + timedelta(days=days)

    db.commit()
    db.refresh(rec)
    return rec


def _ensure_default_steps(db: Session, campaign: Campaign) -> list[CampaignSequenceStep]:
    steps = (
        db.query(CampaignSequenceStep)
        .filter_by(campaign_id=campaign.id)
        .order_by(CampaignSequenceStep.step_number)
        .all()
    )
    if steps:
        return steps
    interval = _delay_days(None, campaign.followup_interval_days, 3)
    max_fu = max(1, campaign.max_followups or 3)
    email = next((c for c in campaign.contents if c.channel == "email"), None)
    wa = next((c for c in campaign.contents if c.channel == "whatsapp"), None)
    sms = next((c for c in campaign.contents if c.channel == "sms"), None)
    defaults = [
        CampaignSequenceStep(
            campaign_id=campaign.id,
            step_number=0,
            label="First touch",
            delay_days=0,
            send_time="10:00",
            email_enabled=bool(campaign.email_enabled),
            email_subject=(email.subject if email else "") or "",
            email_body=(email.body if email else "") or "",
            whatsapp_enabled=bool(campaign.whatsapp_enabled),
            whatsapp_body=(wa.body if wa else "") or "",
            sms_enabled=bool(campaign.sms_enabled),
            sms_body=(sms.body if sms else "") or "",
            enabled=True,
            channel="email",
            subject=(email.subject if email else "") or "",
            body=(email.body if email else "") or "",
        )
    ]
    for n in range(1, max_fu + 1):
        defaults.append(
            CampaignSequenceStep(
                campaign_id=campaign.id,
                step_number=n,
                label=f"Follow-up {n}",
                delay_days=interval,
                send_time="10:00",
                email_enabled=bool(campaign.email_enabled),
                email_subject="",
                email_body="",
                whatsapp_enabled=bool(campaign.whatsapp_enabled),
                whatsapp_body="",
                sms_enabled=bool(campaign.sms_enabled),
                sms_body="",
                enabled=True,
                channel="email",
                subject="",
                body="",
            )
        )
    for s in defaults:
        db.add(s)
    db.commit()
    return (
        db.query(CampaignSequenceStep)
        .filter_by(campaign_id=campaign.id)
        .order_by(CampaignSequenceStep.step_number)
        .all()
    )


@router.get("/campaigns/{campaign_id}/sequence-steps", response_model=list[SequenceStepOut])
def list_sequence_steps(campaign_id: int, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    campaign = _campaign_or_404(db, campaign_id, user)
    return _ensure_default_steps(db, campaign)


@router.put("/campaigns/{campaign_id}/sequence-steps", response_model=list[SequenceStepOut])
def replace_sequence_steps(campaign_id: int, payload: SequenceStepsBulkIn,
                           db: Session = Depends(get_db),
                           user: User = Depends(require("content.edit"))):
    campaign = _campaign_or_404(db, campaign_id, user)
    db.query(CampaignSequenceStep).filter_by(campaign_id=campaign.id).delete()
    out = []
    for s in sorted(payload.steps, key=lambda x: x.step_number):
        st = (s.send_time or "10:00").strip()
        if len(st) == 4 and st[1] == ":":
            st = "0" + st
        row = CampaignSequenceStep(
            campaign_id=campaign.id,
            step_number=int(s.step_number),
            label=(s.label or "").strip() or (f"Follow-up {s.step_number}" if s.step_number else "First touch"),
            delay_days=max(0, int(s.delay_days or 0)),
            send_time=st[:5],
            email_enabled=bool(s.email_enabled),
            email_subject=s.email_subject or "",
            email_body=s.email_body or "",
            whatsapp_enabled=bool(s.whatsapp_enabled),
            whatsapp_body=s.whatsapp_body or "",
            sms_enabled=bool(s.sms_enabled),
            sms_body=s.sms_body or "",
            enabled=bool(s.enabled),
            channel="email",
            subject=s.email_subject or "",
            body=s.email_body or "",
        )
        db.add(row)
        out.append(row)
    max_step = max((s.step_number for s in out), default=0)
    if max_step > 0:
        campaign.max_followups = max_step
    step0 = next((s for s in out if s.step_number == 0), None)
    if step0:
        for ch, subj, body in _step_channels(step0):
            content = db.query(CampaignContent).filter_by(campaign_id=campaign.id, channel=ch).first()
            if not content:
                content = CampaignContent(campaign_id=campaign.id, channel=ch)
                db.add(content)
            content.subject = subj
            content.body = body
            content.content_mode = "plain"
        if step0.email_enabled:
            campaign.email_enabled = True
        if step0.whatsapp_enabled:
            campaign.whatsapp_enabled = True
        if step0.sms_enabled:
            campaign.sms_enabled = True
    db.commit()
    for r in out:
        db.refresh(r)
    return out


@router.post("/campaigns/{campaign_id}/followups/run")
def run_due_followups(campaign_id: int, db: Session = Depends(get_db),
                      user: User = Depends(require("campaign.send"))):
    from ..worker import enqueue_message

    campaign = _campaign_or_404(db, campaign_id, user)
    if not campaign.followup_enabled:
        return {"enqueued": 0, "recipients": 0, "detail": "Follow-ups disabled"}

    steps = {s.step_number: s for s in _ensure_default_steps(db, campaign)}
    now = datetime.now(timezone.utc)

    due = [
        r for r in campaign.recipients
        if not r.campaign_stopped
        and r.active
        and r.reply_status == "not_replied"
        and r.followup_count < campaign.max_followups
        and r.next_followup_at is not None
        and _as_utc(r.next_followup_at) <= _as_utc(now)
    ]

    enqueued = 0
    recipients_hit = 0
    for rec in due:
        step_n = rec.followup_count + 1
        step = steps.get(step_n)
        if step is not None and not step.enabled:
            continue
        channels = _step_channels(step) if step else []
        if not channels:
            if campaign.email_enabled and rec.email:
                channels = [("email", "", "")]
            if campaign.whatsapp_enabled and rec.mobile:
                channels.append(("whatsapp", "", ""))
            if campaign.sms_enabled and rec.mobile:
                channels.append(("sms", "", ""))

        created = False
        for ch, _subj, _body in channels:
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
            enqueued += 1
            created = True

        if not created:
            continue
        recipients_hit += 1
        rec.followup_count = step_n
        rec.last_followup_at = now
        next_step = steps.get(step_n + 1)
        if step_n < campaign.max_followups and (next_step is None or next_step.enabled):
            delay = _delay_days(next_step.delay_days if next_step else None, campaign.followup_interval_days, 3)
            send_time = (next_step.send_time if next_step else None) or "10:00"
            rec.next_followup_at = compute_next_send_at(now, delay, send_time)
        else:
            rec.next_followup_at = None

    db.commit()
    return {"enqueued": enqueued, "recipients": recipients_hit}


@router.post("/campaigns/{campaign_id}/send/arm-followups")
def arm_followups_after_send(campaign_id: int, db: Session = Depends(get_db),
                             user: User = Depends(require("campaign.send"))):
    campaign = _campaign_or_404(db, campaign_id, user)
    if not campaign.followup_enabled:
        return {"armed": 0}
    now = datetime.now(timezone.utc)
    steps = {s.step_number: s for s in _ensure_default_steps(db, campaign)}
    step1 = steps.get(1)
    days = _delay_days(step1.delay_days if step1 else None, campaign.followup_interval_days, 3)
    send_time = (step1.send_time if step1 else None) or "10:00"
    n = 0
    for rec in campaign.recipients:
        if rec.active and not rec.campaign_stopped and rec.reply_status == "not_replied":
            rec.next_followup_at = compute_next_send_at(now, days, send_time)
            rec.followup_count = 0
            n += 1
    db.commit()
    return {"armed": n, "next_followup_days": days, "next_send_time": send_time}


@router.post("/followups/run-due-all")
def run_due_followups_all(db: Session = Depends(get_db),
                          user: User = Depends(require("campaign.send"))):
    from ..worker import enqueue_message

    campaigns = db.query(Campaign).filter_by(followup_enabled=True).all()
    total_enqueued = 0
    total_recipients = 0
    details = []
    now = datetime.now(timezone.utc)

    for campaign in campaigns:
        steps = {s.step_number: s for s in _ensure_default_steps(db, campaign)}
        due = [
            r for r in campaign.recipients
            if not r.campaign_stopped
            and r.active
            and r.reply_status == "not_replied"
            and r.followup_count < campaign.max_followups
            and r.next_followup_at is not None
            and _as_utc(r.next_followup_at) <= _as_utc(now)
        ]
        enqueued = 0
        hit = 0
        for rec in due:
            step_n = rec.followup_count + 1
            step = steps.get(step_n)
            if step is not None and not step.enabled:
                continue
            channels = _step_channels(step) if step else []
            created = False
            for ch, _subj, _body in channels:
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
                enqueued += 1
                created = True
            if not created:
                continue
            hit += 1
            rec.followup_count = step_n
            rec.last_followup_at = now
            next_step = steps.get(step_n + 1)
            if step_n < campaign.max_followups and (next_step is None or next_step.enabled):
                delay = _delay_days(next_step.delay_days if next_step else None, campaign.followup_interval_days, 3)
                send_time = (next_step.send_time if next_step else None) or "10:00"
                rec.next_followup_at = compute_next_send_at(now, delay, send_time)
            else:
                rec.next_followup_at = None
        if enqueued:
            details.append({"campaign_id": campaign.id, "name": campaign.name, "enqueued": enqueued})
        total_enqueued += enqueued
        total_recipients += hit

    db.commit()
    return {
        "enqueued": total_enqueued,
        "recipients": total_recipients,
        "campaigns": details,
    }


@router.post("/campaigns/{campaign_id}/sequence/reset")
def reset_sequence(campaign_id: int, db: Session = Depends(get_db),
                   user: User = Depends(require("campaign.send"))):
    """Clear engagement state so sequence can start clean from the Follow-up tab."""
    campaign = _campaign_or_404(db, campaign_id, user)
    n = 0
    for r in campaign.recipients:
        r.reply_status = "not_replied"
        r.interest_status = ""
        r.campaign_stopped = False
        r.followup_count = 0
        r.next_followup_at = None
        r.last_followup_at = None
        n += 1
    # Allow re-send of campaign first touch
    if campaign.status in ("completed", "sending", "failed"):
        campaign.status = "draft"
    db.commit()
    return {"reset": n, "campaign_status": campaign.status}


@router.post("/campaigns/{campaign_id}/sequence/restart")
def restart_sequence(campaign_id: int, db: Session = Depends(get_db),
                     user: User = Depends(require("campaign.send"))):
    """Reset contacts, send First touch (step 0) now, arm Follow-up 1 at its IST time.

    Controlled entirely from the Follow-up tab — no CLI needed.
    """
    from ..worker import enqueue_message
    from ..models import Message

    campaign = _campaign_or_404(db, campaign_id, user)
    steps = {s.step_number: s for s in _ensure_default_steps(db, campaign)}
    step0 = steps.get(0)
    step1 = steps.get(1)
    now = datetime.now(timezone.utc)

    # 1) Reset engagement
    for r in campaign.recipients:
        r.reply_status = "not_replied"
        r.interest_status = ""
        r.campaign_stopped = False
        r.followup_count = 0
        r.next_followup_at = None
        r.last_followup_at = None

    # 2) Queue First touch (step 0) for each active contact
    channels0 = _step_channels(step0) if step0 else []
    if not channels0:
        if campaign.email_enabled:
            channels0 = [("email", "", "")]
        if campaign.sms_enabled:
            channels0.append(("sms", "", ""))

    enqueued = 0
    armed = 0
    for r in campaign.recipients:
        if not r.active:
            continue
        for ch, _s, _b in channels0:
            to = r.email if ch == "email" else r.mobile
            if not to:
                continue
            msg = Message(
                campaign_id=campaign.id,
                recipient_id=r.id,
                channel=ch,
                to_address=to,
                recipient_name=r.name,
                status="queued",
                is_followup=False,
                followup_number=0,
                sequence_step="step_0",
            )
            db.add(msg)
            db.flush()
            enqueue_message(msg.id)
            enqueued += 1

        # 3) Arm Follow-up 1 at step 1 IST time
        if campaign.followup_enabled and step1 and getattr(step1, "enabled", True):
            days = _delay_days(step1.delay_days, campaign.followup_interval_days, 3)
            send_time = (step1.send_time or "10:00")[:5]
            r.next_followup_at = compute_next_send_at(now, days, send_time)
            r.followup_count = 0
            armed += 1

    campaign.status = "sending"
    db.commit()
    return {
        "enqueued_first_touch": enqueued,
        "armed_followups": armed,
        "message": "First touch queued. Follow-ups will send at each step Time (IST). Keep the worker running.",
    }
