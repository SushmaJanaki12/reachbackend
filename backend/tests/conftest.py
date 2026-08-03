"""Test config: isolated DB + providers forced OFF (simulated sending, no real emails/SMS).

Env vars are set BEFORE importing the app so pydantic Settings picks them up.
"""
import os

os.environ["DATABASE_URL"] = "postgresql+psycopg2://postgres:postgres123@localhost:5432/reach_test"
# Redis has no notion of "databases" the way Postgres does per-URL, but it does
# support numbered logical DBs on the same instance -- use a dedicated one so
# the test suite's queue never collides with a dev/prod worker's "sends" queue.
# Without this, `_isolated_queue` below (autouse, empties the queue around
# every test) would silently wipe out real in-flight campaign jobs any time
# pytest runs against the same Redis instance -- messages stay "queued"
# forever in Postgres with no corresponding job left to process them, and no
# error anywhere to explain why.
os.environ["REDIS_URL"] = "redis://localhost:6379/15"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["SEED_DEFAULT_ADMIN"] = "true"  # tests log in as admin@reach.io / Admin@123
# Force simulated sending so tests never hit Office 365 / Metamorph.
for _k in ["AZURE_TENANT_ID", "O365_CLIENT_ID", "O365_CLIENT_SECRET", "O365_FROM_EMAIL",
           "SMS_USERNAME", "SMS_PASSWORD", "SMS_TEMPLATE_ID", "SMS_FROM", "SMS_API_URL", "SMS_SUCCESS_TOKEN"]:
    os.environ[_k] = ""

import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:          # triggers startup -> create_all + seed
        yield c


@pytest.fixture(autouse=True)
def _isolated_queue():
    """Redis is a single shared instance across the whole test session (unlike
    Postgres, there's no per-test rollback for it), so tests that intentionally
    leave jobs unprocessed (crash/idempotency tests) would otherwise leak them
    into later tests' drain_queue() calls. Reset before and after every test."""
    from app.config import settings
    from app.worker import send_queue, redis_conn
    assert settings.redis_url != "redis://localhost:6379/0", (
        "tests must not run against the default (dev/prod) Redis DB -- "
        "this fixture empties the queue and would destroy real campaign jobs"
    )
    send_queue.empty()
    for key in redis_conn.scan_iter("ratelimit:*"):
        redis_conn.delete(key)
    yield
    send_queue.empty()


def _token(client, email, pw):
    r = client.post("/api/auth/login", data={"username": email, "password": pw})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def admin_headers(client):
    return {"Authorization": f"Bearer {_token(client, 'admin@reach.io', 'Admin@123')}"}


@pytest.fixture(scope="session")
def user_headers(client):
    return {"Authorization": f"Bearer {_token(client, 'user@reach.io', 'User@123')}"}


@pytest.fixture()
def project(client, admin_headers):
    """A fresh project with all channels enabled (sms/whatsapp active)."""
    r = client.post("/api/projects", headers=admin_headers, json={
        "name": "Test Project", "email": "test@acme.com",
        "sms_active": True, "sms_provider": "Metamorph",
        "whatsapp_active": True, "whatsapp_provider": "Meta",
    })
    assert r.status_code == 200, r.text
    return r.json()


def make_campaign(client, headers, project_id, name="Camp"):
    r = client.post("/api/campaigns", headers=headers, json={"project_id": project_id, "name": name})
    assert r.status_code == 200, r.text
    return r.json()


def drain_queue():
    """Run the RQ worker in-process, burst mode, until the send queue is empty.

    Sending itself only enqueues jobs (see app/worker.py); tests that need to
    observe the *result* of a send (final message/campaign status) must call
    this afterward to actually process them, standing in for the separate
    `python -m app.worker` process used in real deployments.
    """
    from rq import SimpleWorker
    from app.worker import send_queue, redis_conn
    # SimpleWorker executes jobs in-process (no fork), so test-time monkeypatches
    # on app.worker (settings, send_email/send_sms) are visible to the job.
    SimpleWorker([send_queue], connection=redis_conn).work(burst=True)
