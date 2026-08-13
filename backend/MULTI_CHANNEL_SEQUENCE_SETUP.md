# Multi-channel automatic sequences (email + WhatsApp + SMS)

## Behaviour

1. Author **Content** (first touch) and/or **Sequence step 0**.
2. Add follow-up steps with:
   - **After (days)** — delay after previous step
   - **Time (UTC)** — clock time to send that day
   - **Email / WhatsApp / SMS** toggles + copy per channel
3. **Send** campaign → step 0 goes out; step 1 is **auto-armed** at its day+time.
4. Scheduler calls `POST /api/followups/run-due-all` hourly → due steps queue automatically.
5. Reply / not interested → sequence stops for that contact.

## Migrate

```powershell
alembic upgrade head
# applies f1a2b3c4d5e6 then f2b3c4d5e6f7
```

## Automatic runner

```http
POST /api/followups/run-due-all
Authorization: Bearer <token>
```

Schedule every 15–60 minutes (Windows Task Scheduler / cron).

Times are stored as **UTC** `HH:MM`. Convert from your local timezone when setting them.
