# REACH — Sequence steps + Warmup (setup)

## What was added

### 1. Saleshandy-style follow-up **sequence**
- New table `campaign_sequence_steps` (step 0 = first touch, 1+ = follow-ups)
- Each step has: label, delay_days, subject, body, channel, enabled
- APIs:
  - `GET  /api/campaigns/{id}/sequence-steps`
  - `PUT  /api/campaigns/{id}/sequence-steps`  (replace full list)
- Follow-up runner uses **step content** (not only the first Content-tab body)
- Arm reminders uses **step 1 delay**
- AI “Save to campaign” / generate with `followup_number` also upserts that step
- Step 0 email is synced into `campaign_content` for the Content tab / initial send

### 2. Warmup (inbox protection)
- Campaign fields: `warmup_enabled`, `warmup_daily_cap`, `warmup_started_at`
- When warmup is on, `POST .../followups/run` respects the daily email cap
- UI: Follow-up tab → Sequence settings → Warmup on/off + daily cap

**Still required for real inbox placement (ops, not only app):**
- SPF + DKIM + DMARC on the sending domain
- Start with low volume, clean lists, stop on reply (already supported)

---

## Backend setup

```powershell
cd path\to\backend
# activate venv
.\venv\Scripts\activate   # Windows
# pip install -r requirements.txt  # if needed

# Apply migration
alembic upgrade head

# Restart API
uvicorn app.main:app --reload --port 8000

# Optional: Redis worker for real send queue
# python -m app.worker
```

Confirm migration `f1a2b3c4d5e6` is applied.

If `alembic` complains about down_revision, ensure `e7a1b2c3d4f5` is already in the DB (sequence engagement migration).

---

## Frontend setup

```powershell
cd path\to\frontend
npm install
npm run dev
```

Open a campaign → **Follow-up** tab:

1. **Email sequence steps** — edit subjects/bodies, delays, AI draft per step → **Save sequence**
2. **Sequence settings** — enable reminders, interval, max, **warmup**
3. **Arm reminders now** after first send
4. **Run due follow-ups** when steps are due (or schedule that endpoint)

---

## Recommended flow

1. Content tab — write first email (or generate step 0)
2. Follow-up tab — define steps 0..N with different copy + delays → Save sequence
3. Optional: enable warmup with a low daily cap (e.g. 20–50)
4. Review & Send — initial send
5. Arm reminders → later Run due follow-ups
6. Mark replied / interested / not interested on the engagement board

---

## Note on OpenAI

`app/ai_content.py` loads `.env` from the backend folder via `Path(__file__).parent.parent / ".env"`.
Restart uvicorn after changing keys. Badge should show `openai`, not `template`.
