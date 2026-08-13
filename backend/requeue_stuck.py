"""Re-enqueue all queued/processing messages and optionally unstick campaigns.

Usage (from backend folder, venv active):

  python requeue_stuck.py
  python requeue_stuck.py --reset-sending
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

# ensure app package imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.database import SessionLocal
from app.models import Campaign, Message
from app.worker import enqueue_message


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--reset-sending", action="store_true",
                   help="Set campaigns stuck in 'sending' back to 'failed' if no in-flight success")
    args = p.parse_args()
    db = SessionLocal()
    try:
        rows = (
            db.query(Message)
            .filter(Message.status.in_(["queued", "processing"]))
            .all()
        )
        print(f"Found {len(rows)} queued/processing message(s)")
        for m in rows:
            try:
                enqueue_message(m.id)
                print(f"  requeued message id={m.id} campaign={m.campaign_id} channel={m.channel}")
            except Exception as e:
                print(f"  FAIL message id={m.id}: {e}")

        if args.reset_sending:
            stuck = db.query(Campaign).filter(Campaign.status == "sending").all()
            for c in stuck:
                open_msgs = (
                    db.query(Message)
                    .filter(Message.campaign_id == c.id, Message.status.in_(["queued", "processing"]))
                    .count()
                )
                if open_msgs == 0:
                    c.status = "failed"
                    print(f"  campaign {c.id} ({c.name}) -> failed (no open messages)")
                else:
                    print(f"  campaign {c.id} still has {open_msgs} open message(s); left as sending")
            db.commit()
    finally:
        db.close()
    print("Done. Keep: python -m app.worker")


if __name__ == "__main__":
    main()
