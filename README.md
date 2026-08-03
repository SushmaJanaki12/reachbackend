# Reach — Campaign Management Platform

One campaign. Every channel. A single click.

## Project Structure

```
reach/
├── backend/          # FastAPI + PostgreSQL API
│   ├── app/          # Application code
│   │   ├── routers/  # API route handlers
│   │   ├── main.py   # App entrypoint
│   │   ├── models.py # SQLAlchemy models
│   │   ├── schemas.py # Pydantic schemas
│   │   └── ...
│   ├── tests/        # Pytest test suite
│   ├── .env          # Environment variables (create from .env.example)
│   ├── .env.example  # Environment template
│   └── requirements.txt
├── frontend/         # React + Vite SPA
│   ├── src/          # Source code
│   │   ├── pages/    # Page components
│   │   ├── components/
│   │   ├── api.js    # Axios API client
│   │   └── auth.jsx  # Auth context
│   ├── index.html
│   └── package.json
└── README.md
```

## Prerequisites

- Python 3.12+
- Node.js 20+
- PostgreSQL 15+
- Redis 6+ (job queue for campaign sending)

## Setup

### 1. Create the database

```bash
createdb -U postgres reach
```

### 2. Backend

```bash
cd backend
cp .env.example .env   # Edit .env if needed
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The backend starts on **http://localhost:8000**.  
Tables and seed data are created automatically on first startup.

### 3. Worker

Campaign sends are processed asynchronously off a Redis queue, so a worker
process must run alongside the API for messages to actually go out (email/SMS
sending itself doesn't change, only how it's triggered):

```bash
redis-server                       # if not already running
cd backend
python -m app.worker
```

Run one worker per environment; scale by running more worker processes against
the same Redis instance. `POST /campaigns/{id}/send` returns immediately once
`Message` rows are queued -- the campaign moves to `completed` once the worker
has processed all of them (poll `GET /campaigns/{id}/summary`).

**The worker has to keep running.** If it's not up (crashed, forgot to start
it, machine restarted), sends stay at `queued` forever with no error visible
anywhere -- there's nothing else watching the queue. For anything beyond a
quick manual test, run the API and worker under a supervisor instead of two
raw terminal commands, so a crash gets restarted automatically:

```bash
cd backend
pip install -r requirements-dev.txt   # adds `supervisor`
supervisord -c supervisord.conf       # starts + daemonizes both api and worker
supervisorctl -c supervisord.conf status
supervisorctl -c supervisord.conf tail -f worker   # follow worker logs
supervisorctl -c supervisord.conf shutdown         # stop everything
```

Logs land in `backend/logs/`. `supervisord.conf` runs whatever `python`/
`uvicorn` resolve to on `PATH` -- activate your venv/conda env before running
`supervisord`, same as for the manual commands above.

### 4. Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend starts on **http://localhost:5173** and proxies `/api` to the backend.

## Demo Accounts

| Role  | Email             | Password   |
|-------|-------------------|------------|
| Admin | admin@reach.io    | Admin@123  |
| User  | user@reach.io     | User@123   |

## API Documentation

Visit **http://localhost:8000/docs** for the interactive Swagger UI.
