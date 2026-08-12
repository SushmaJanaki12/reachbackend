"""Campaign resend (P0.5, revised 2026-08-11): an earlier revision of this
same fix blocked resend outright once a campaign had any Message rows,
forcing Duplicate instead. Resend is now allowed repeatedly -- the prior
send's Message/FollowUpRun rows are archived into MessageHistory/
FollowUpRunHistory (see app/campaign_resend.py::archive_campaign_history)
before the live tables are cleared for a fresh run, and the archived runs
stay independently viewable via the run-scoped Tracking & Reports API this
enables (?run= on /tracking/{channel}, /summary, /report.csv, and the new
/send-runs listing)."""
import pytest

from app.campaign_resend import archive_campaign_history
from app.database import SessionLocal
from app.models import Campaign, Message, MessageHistory
from tests.conftest import make_campaign, drain_queue, upload_dataset

CSV = "Name,Email Address,Mobile Number\nAlice,alice@example.com,9876543210\nBob,bob@example.com,9123456789\n"


def _sent_campaign(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    upload_dataset(client, admin_headers, c["id"], CSV)
    client.put(f"/api/campaigns/{c['id']}/content/email", headers=admin_headers, json={"body": "Hello {{Name}}"})
    client.put(f"/api/campaigns/{c['id']}", headers=admin_headers, json={"email_enabled": True})
    r = client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    assert r.status_code == 200, r.text
    drain_queue()
    return c


def test_repeated_resend_creates_a_new_run_each_time(client, admin_headers, project):
    c = _sent_campaign(client, admin_headers, project)
    for _ in range(2):
        r = client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
        assert r.status_code == 200, r.text
        drain_queue()

    runs = client.get(f"/api/campaigns/{c['id']}/send-runs", headers=admin_headers).json()
    assert [r["run_number"] for r in runs] == [1, 2, 3]
    assert [r["message_count"] for r in runs] == [2, 2, 2]
    assert [r["is_current"] for r in runs] == [False, False, True]

    db = SessionLocal()
    try:
        assert db.get(Campaign, c["id"]).current_send_run == 3
        assert db.query(Message).filter_by(campaign_id=c["id"]).count() == 2
        # 2 archived runs (1 and 2) x 2 messages each
        assert db.query(MessageHistory).filter_by(campaign_id=c["id"]).count() == 4
    finally:
        db.close()


def test_archive_failure_leaves_live_rows_completely_untouched(client, admin_headers, project, monkeypatch):
    """Forces a DB error at the point archive_campaign_history commits --
    the whole archive+clear must roll back to nothing changed, never a
    half-archived campaign (acceptance criterion in the spec's P0.5 item)."""
    c = _sent_campaign(client, admin_headers, project)

    db = SessionLocal()
    try:
        campaign = db.get(Campaign, c["id"])
        live_before = {m.id: (m.status, m.to_address) for m in db.query(Message).filter_by(campaign_id=c["id"]).all()}
        assert len(live_before) == 2

        def _boom(*a, **k):
            raise RuntimeError("simulated DB failure")
        monkeypatch.setattr(db, "commit", _boom)

        with pytest.raises(RuntimeError):
            archive_campaign_history(db, campaign)
        db.rollback()
    finally:
        db.close()

    db2 = SessionLocal()
    try:
        live_after = {m.id: (m.status, m.to_address) for m in db2.query(Message).filter_by(campaign_id=c["id"]).all()}
        assert live_after == live_before
        assert db2.query(MessageHistory).filter_by(campaign_id=c["id"]).count() == 0
        assert db2.get(Campaign, c["id"]).current_send_run == 1
    finally:
        db2.close()

    # And a real resend (unpatched) now succeeds normally -- confirms the
    # forced failure above didn't leave the campaign in some broken state.
    resend = client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    assert resend.status_code == 200, resend.text


def test_summary_and_tracking_scoped_by_run(client, admin_headers, project):
    c = _sent_campaign(client, admin_headers, project)
    resend = client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    assert resend.status_code == 200, resend.text
    drain_queue()

    # Default (omitted "run") and explicit "current run number" both mean
    # the live table -- the most recent send, per the spec's stated default.
    current_summary = client.get(f"/api/campaigns/{c['id']}/summary", headers=admin_headers).json()
    assert current_summary["total_messages"] == 2
    run1_summary = client.get(f"/api/campaigns/{c['id']}/summary",
                               headers=admin_headers, params={"run": 1}).json()
    assert run1_summary["total_messages"] == 2
    all_summary = client.get(f"/api/campaigns/{c['id']}/summary",
                              headers=admin_headers, params={"run": "all"}).json()
    assert all_summary["total_messages"] == 4

    current_rows = client.get(f"/api/campaigns/{c['id']}/tracking/email", headers=admin_headers).json()
    run1_rows = client.get(f"/api/campaigns/{c['id']}/tracking/email",
                            headers=admin_headers, params={"run": 1}).json()
    all_rows = client.get(f"/api/campaigns/{c['id']}/tracking/email",
                           headers=admin_headers, params={"run": "all"}).json()
    assert len(current_rows) == 2 and len(run1_rows) == 2 and len(all_rows) == 4
    # No id collisions between historical and live rows in the combined view.
    assert len({r["id"] for r in all_rows}) == 4
    assert {r["id"] for r in current_rows}.isdisjoint({r["id"] for r in run1_rows})


def test_invalid_run_param_rejected(client, admin_headers, project):
    c = _sent_campaign(client, admin_headers, project)
    r = client.get(f"/api/campaigns/{c['id']}/tracking/email",
                    headers=admin_headers, params={"run": "not-a-number"})
    assert r.status_code == 400


def test_report_csv_scoped_by_run(client, admin_headers, project):
    c = _sent_campaign(client, admin_headers, project)
    resend = client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    assert resend.status_code == 200, resend.text
    drain_queue()

    resp = client.get(f"/api/campaigns/{c['id']}/report.csv", headers=admin_headers, params={"run": 1})
    assert resp.status_code == 200
    data_rows = [ln for ln in resp.text.strip().splitlines()][1:]  # drop header
    assert len(data_rows) == 2
