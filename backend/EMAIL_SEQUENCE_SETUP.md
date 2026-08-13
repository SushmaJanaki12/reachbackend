# REACH — Automatic email sequences (Saleshandy-style)

## Goal (this package)

Email-only multi-step sequences:

```
Step 0 (day 0)  → first email on Send
Step 1 (+N days) → auto if not replied
Step 2 (+N days) → auto if not replied
Stop on reply / not interested
```

Warmup is deferred — focus on sequence first.

## Backend setup

```powershell
cd backend
.\venv\Scripts\activate
alembic upgrade head
uvicorn app.main:app --reload --port 8000
# Worker (required for real sends)
# python -m app.worker
```

Migration: `f1a2b3c4d5e6_add_sequence_steps_warmup.py` (includes sequence_steps table).

## How automatic works

1. **On Send** — step 0 email queues; contacts are **auto-armed** for step 1 using that step's delay.
2. **Due runner** — when `next_followup_at` is past, step content is queued as email.
3. **Scheduler (required for hands-off auto)** — call hourly:

```
POST /api/followups/run-due-all
Authorization: Bearer <token with campaign.send>
```

Windows Task Scheduler or cron can hit this so you do not click "Run due emails now".

Per-campaign: `POST /api/campaigns/{id}/followups/run`

## APIs

| Method | Path | Purpose |
|--------|------|---------|
| GET/PUT | `/api/campaigns/{id}/sequence-steps` | Read/replace email steps |
| PUT | `/api/campaigns/{id}/followup-settings` | Enable sequence, max steps |
| POST | `/api/campaigns/{id}/followups/run` | Run due for one campaign |
| POST | `/api/followups/run-due-all` | Run due for all campaigns |

## Frontend

Follow-up tab → **Automatic email sequence** editor → Save sequence → Send campaign.

Mark replies on the engagement board so later steps stop.
