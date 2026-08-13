"""Diagnose + force-arm sequence for a campaign.

Usage (from backend folder, venv on):
  python diagnose_sequence.py 4
  python diagnose_sequence.py 4 --arm-now
  python diagnose_sequence.py 4 --run-due
"""
from __future__ import annotations
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.database import SessionLocal
from app.models import Campaign, CampaignSequenceStep, Message, Recipient
from app.routers.engagement import compute_next_send_at, _delay_days, _as_utc, IST


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    flags = set(sys.argv[1:])
    cid = int(args[0]) if args else 4
    db = SessionLocal()
    try:
        c = db.get(Campaign, cid)
        if not c:
            print("Campaign not found", cid)
            return
        now = datetime.now(timezone.utc)
        now_ist = now.astimezone(IST)
        print("=== NOW ===")
        print("  UTC:", now.isoformat())
        print("  IST:", now_ist.strftime("%Y-%m-%d %H:%M:%S IST"))
        print("=== CAMPAIGN", c.id, c.name, "===")
        print("  status:", c.status)
        print("  followup_enabled:", c.followup_enabled)
        print("  followup_interval_days:", c.followup_interval_days)
        print("  max_followups:", c.max_followups)
        print("  email_enabled:", c.email_enabled)
        steps = (
            db.query(CampaignSequenceStep)
            .filter_by(campaign_id=c.id)
            .order_by(CampaignSequenceStep.step_number)
            .all()
        )
        print("=== STEPS ===")
        for s in steps:
            print(
                f"  step {s.step_number}: delay={s.delay_days} time={s.send_time} "
                f"email={s.email_enabled} body_len={len(s.email_body or '')} enabled={s.enabled}"
            )
        print("=== RECIPIENTS ===")
        for r in c.recipients:
            nxt = r.next_followup_at
            nxt_s = None
            due = False
            if nxt:
                nu = _as_utc(nxt)
                nxt_s = nu.astimezone(IST).strftime("%Y-%m-%d %H:%M IST")
                due = nu <= now
            print(
                f"  {r.name}: reply={r.reply_status} stopped={r.campaign_stopped} "
                f"followup_count={r.followup_count} next={nxt_s} due_now={due}"
            )
        msgs = db.query(Message).filter_by(campaign_id=c.id).order_by(Message.id).all()
        print("=== MESSAGES ===")
        for m in msgs:
            print(
                f"  id={m.id} ch={m.channel} status={m.status} "
                f"followup={getattr(m, 'is_followup', None)} n={getattr(m, 'followup_number', None)} "
                f"to={m.to_address}"
            )

        if "--arm-now" in flags:
            step1 = next((s for s in steps if s.step_number == 1), None)
            days = _delay_days(step1.delay_days if step1 else None, c.followup_interval_days, 3)
            send_time = (step1.send_time if step1 else None) or "10:00"
            # Force due in ~1 minute for testing if --soon
            if "--soon" in flags:
                soon = (now + timedelta(minutes=1)).astimezone(IST)
                send_time = f"{soon.hour:02d}:{soon.minute:02d}"
                days = 0
                print(f"  TEST MODE: arming for {send_time} IST (about 1 min)")
            n = 0
            for r in c.recipients:
                if r.active and not r.campaign_stopped and r.reply_status == "not_replied":
                    r.next_followup_at = compute_next_send_at(now, days, send_time)
                    r.followup_count = 0
                    n += 1
                    print(f"  armed {r.name} -> {_as_utc(r.next_followup_at).astimezone(IST)}")
            db.commit()
            print(f"Armed {n} contacts (days={days}, time={send_time} IST)")

        if "--run-due" in flags:
            from app.worker import enqueue_message
            from app.routers.engagement import _step_channels, _ensure_default_steps
            steps_map = {s.step_number: s for s in _ensure_default_steps(db, c)}
            max_fu = c.max_followups or 3
            enq = 0
            for r in c.recipients:
                if (
                    r.campaign_stopped or not r.active or r.reply_status != "not_replied"
                    or (r.followup_count or 0) >= max_fu
                    or r.next_followup_at is None
                    or _as_utc(r.next_followup_at) > now
                ):
                    continue
                step_n = (r.followup_count or 0) + 1
                step = steps_map.get(step_n)
                channels = _step_channels(step) if step else []
                if not channels and c.email_enabled and r.email:
                    channels = [("email", "", "")]
                for ch, _s, _b in channels:
                    to = r.email if ch == "email" else r.mobile
                    if not to:
                        continue
                    msg = Message(
                        campaign_id=c.id,
                        recipient_id=r.id,
                        channel=ch,
                        to_address=to,
                        recipient_name=r.name,
                        status="queued",
                        is_followup=True,
                        followup_number=step_n,
                        sequence_step=f"step_{step_n}",
                    )
                    db.add(msg)
                    db.flush()
                    enqueue_message(msg.id)
                    enq += 1
                    print(f"  enqueued follow-up #{step_n} {ch} -> {to}")
                r.followup_count = step_n
                r.last_followup_at = now.replace(tzinfo=None)
                next_step = steps_map.get(step_n + 1)
                if step_n < max_fu and (next_step is None or next_step.enabled):
                    delay = _delay_days(
                        next_step.delay_days if next_step else None,
                        c.followup_interval_days,
                        3,
                    )
                    st = (next_step.send_time if next_step else None) or "10:00"
                    r.next_followup_at = compute_next_send_at(now, delay, st)
                else:
                    r.next_followup_at = None
            db.commit()
            print(f"Enqueued {enq} messages — keep worker running")
    finally:
        db.close()


if __name__ == "__main__":
    main()
