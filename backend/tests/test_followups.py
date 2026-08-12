from app.database import SessionLocal
from app.models import FollowUpRun, FollowUpRunHistory, Message, MessageHistory, Suppression
from tests.conftest import make_campaign, drain_queue, run_scheduled, upload_dataset

CSV = "Name,Email Address,Mobile Number\nAlice,alice@example.com,9876543210\n"


def _ready_campaign(client, headers, project, whatsapp=False):
    # is_test_campaign=True -- these tests drive engagement via the Simulate
    # endpoint, which is gated to test campaigns only (see
    # routers/followups.py::simulate_event and test_simulate_blocked_on_non_test_campaign).
    c = make_campaign(client, headers, project["id"], is_test_campaign=True)
    upload_dataset(client, headers, c["id"], CSV)
    client.put(f"/api/campaigns/{c['id']}/content/email", headers=headers,
               json={"subject": "Hi {{Name}}", "body": "Hello {{Name}}"})
    patch = {"email_enabled": True}
    if whatsapp:
        # Toggling whatsapp_enabled also makes /send fan the *initial* blast
        # out over WhatsApp (existing per-channel-content requirement in
        # send_campaign), not just offer it as a follow-up fallback -- so
        # content has to be authored here too or the send itself 400s.
        patch["whatsapp_enabled"] = True
        client.put(f"/api/campaigns/{c['id']}/content/whatsapp", headers=headers,
                   json={"subject": "", "body": "Hello {{Name}}"})
    r = client.put(f"/api/campaigns/{c['id']}", headers=headers, json=patch)
    assert r.status_code == 200, r.text
    return c


def _add_step(client, headers, cid, **overrides):
    payload = {
        "trigger_type": "no_reply", "delay_value": 0, "delay_unit": "hours",
        "primary_channel": "email", "subject": "Reminder", "body_template": "Hi {{Name}}, following up",
    }
    payload.update(overrides)
    r = client.post(f"/api/campaigns/{cid}/followups/steps", headers=headers, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _no_weekend_skip(client, headers, cid):
    r = client.put(f"/api/campaigns/{cid}/followups/settings", headers=headers, json={
        "max_touches_per_week": 3, "skip_weekends": False,
        "negative_reply_handling": "tag_and_stop", "default_send_time": None,
    })
    assert r.status_code == 200, r.text


def _initial_message(campaign_id):
    db = SessionLocal()
    try:
        return db.query(Message).filter_by(campaign_id=campaign_id, step_id=None).first()
    finally:
        db.close()


def test_step_crud_and_reorder(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    s1 = _add_step(client, admin_headers, c["id"], trigger_type="not_opened", delay_value=3, delay_unit="days")
    s2 = _add_step(client, admin_headers, c["id"], trigger_type="no_reply", delay_value=7, delay_unit="days")
    assert (s1["step_order"], s2["step_order"]) == (1, 2)
    assert s1["stats"] == {"sent": 0, "open_rate": None, "click_rate": None, "reply_rate": None}

    steps = client.get(f"/api/campaigns/{c['id']}/followups/steps", headers=admin_headers).json()
    assert [s["id"] for s in steps] == [s1["id"], s2["id"]]

    moved = client.post(f"/api/campaigns/{c['id']}/followups/steps/{s2['id']}/move",
                         headers=admin_headers, json={"direction": "up"})
    assert moved.status_code == 200, moved.text
    assert [s["id"] for s in moved.json()] == [s2["id"], s1["id"]]

    # can't move the first step further up
    bad = client.post(f"/api/campaigns/{c['id']}/followups/steps/{s2['id']}/move",
                       headers=admin_headers, json={"direction": "up"})
    assert bad.status_code == 400

    client.delete(f"/api/campaigns/{c['id']}/followups/steps/{s1['id']}", headers=admin_headers)
    remaining = client.get(f"/api/campaigns/{c['id']}/followups/steps", headers=admin_headers).json()
    assert len(remaining) == 1 and remaining[0]["id"] == s2["id"] and remaining[0]["step_order"] == 1


def test_settings_default_and_update(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    got = client.get(f"/api/campaigns/{c['id']}/followups/settings", headers=admin_headers).json()
    assert got == {
        "campaign_id": c["id"], "max_touches_per_week": 3, "skip_weekends": True,
        "negative_reply_handling": "tag_and_stop", "default_send_time": None, "restart_on_resend": False,
    }

    updated = client.put(f"/api/campaigns/{c['id']}/followups/settings", headers=admin_headers, json={
        "max_touches_per_week": 5, "skip_weekends": False,
        "negative_reply_handling": "stop_only", "default_send_time": "09:00",
    })
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["max_touches_per_week"] == 5
    assert body["negative_reply_handling"] == "stop_only"
    assert body["default_send_time"] == "09:00"


def test_trigger_fires_and_completes_when_due_and_condition_holds(client, admin_headers, project):
    c = _ready_campaign(client, admin_headers, project)
    _no_weekend_skip(client, admin_headers, c["id"])
    _add_step(client, admin_headers, c["id"], trigger_type="not_opened", delay_value=0, delay_unit="hours")

    send = client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    assert send.status_code == 200, send.text
    drain_queue()
    drain_queue()  # follow-up step's own Message gets enqueued mid-burst; a second pass is harmless if idle

    db = SessionLocal()
    try:
        msgs = db.query(Message).filter_by(campaign_id=c["id"]).order_by(Message.id).all()
        assert len(msgs) == 2
        followup = next(m for m in msgs if m.step_id is not None)
        assert followup.status == "sent"
        assert followup.channel == "email"

        run = db.query(FollowUpRun).filter_by(campaign_id=c["id"]).one()
        assert run.last_message_id == followup.id
        assert run.status == "completed"  # only step configured -- sequence exhausted
    finally:
        db.close()


def test_trigger_cancelled_when_condition_already_satisfied(client, admin_headers, project):
    """A step with a delay long enough to still be scheduled (not due yet) --
    simulating the 'opened' event before the timer fires must cancel it
    immediately rather than waiting the timer out (spec: 'cancelled ...
    moves to evaluating the next step's trigger')."""
    c = _ready_campaign(client, admin_headers, project)
    _no_weekend_skip(client, admin_headers, c["id"])
    _add_step(client, admin_headers, c["id"], trigger_type="not_opened", delay_value=1, delay_unit="hours")

    client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    drain_queue()
    msg = _initial_message(c["id"])

    db = SessionLocal()
    try:
        run = db.query(FollowUpRun).filter_by(campaign_id=c["id"]).one()
        assert run.status == "active"
        assert run.scheduled_job_id  # timer sitting in the future, not due yet
    finally:
        db.close()

    sim = client.post(f"/api/campaigns/{c['id']}/followups/messages/{msg.id}/simulate",
                       headers=admin_headers, json={"event": "opened"})
    assert sim.status_code == 200, sim.text

    db = SessionLocal()
    try:
        assert db.query(Message).filter_by(campaign_id=c["id"]).count() == 1  # step never sent
        run = db.query(FollowUpRun).filter_by(campaign_id=c["id"]).one()
        assert run.status == "completed"  # no more steps after the cancelled one
    finally:
        db.close()

    # the now-stale timer job firing later must be a harmless no-op
    run_scheduled()
    drain_queue()
    db = SessionLocal()
    try:
        assert db.query(Message).filter_by(campaign_id=c["id"]).count() == 1
    finally:
        db.close()


def test_reply_interested_stops_sequence_and_completes_campaign(client, admin_headers, project):
    c = _ready_campaign(client, admin_headers, project)
    _no_weekend_skip(client, admin_headers, c["id"])
    _add_step(client, admin_headers, c["id"], trigger_type="no_reply", delay_value=1, delay_unit="hours")

    client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    drain_queue()
    msg = _initial_message(c["id"])

    r = client.post(f"/api/campaigns/{c['id']}/followups/messages/{msg.id}/simulate", headers=admin_headers,
                     json={"event": "replied", "reply_text": "Yes, very interested!"})
    assert r.status_code == 200, r.text

    db = SessionLocal()
    try:
        run = db.query(FollowUpRun).filter_by(campaign_id=c["id"]).one()
        assert run.status == "stopped_interested"
        assert db.query(Message).filter_by(campaign_id=c["id"]).count() == 1  # no follow-up ever sent
        assert db.query(Suppression).filter_by(project_id=project["id"]).count() == 0
    finally:
        db.close()

    campaign = client.get(f"/api/campaigns/{c['id']}", headers=admin_headers).json()
    assert campaign["status"] == "completed"  # nothing left pending -- reply resolved the only work


def test_reply_not_interested_stops_and_tags_contact(client, admin_headers, project):
    c = _ready_campaign(client, admin_headers, project)
    _no_weekend_skip(client, admin_headers, c["id"])
    _add_step(client, admin_headers, c["id"], trigger_type="no_reply", delay_value=1, delay_unit="hours")

    client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    drain_queue()
    msg = _initial_message(c["id"])

    r = client.post(f"/api/campaigns/{c['id']}/followups/messages/{msg.id}/simulate", headers=admin_headers,
                     json={"event": "replied", "reply_text": "Please stop, not interested."})
    assert r.status_code == 200, r.text

    db = SessionLocal()
    try:
        run = db.query(FollowUpRun).filter_by(campaign_id=c["id"]).one()
        assert run.status == "stopped_not_interested"
        tag = db.query(Suppression).filter_by(project_id=project["id"], contact="alice@example.com").first()
        assert tag is not None and tag.reason == "not_interested"
    finally:
        db.close()


def test_channel_fallback_used_when_enabled_on_campaign(client, admin_headers, project):
    c = _ready_campaign(client, admin_headers, project, whatsapp=True)
    _no_weekend_skip(client, admin_headers, c["id"])
    _add_step(client, admin_headers, c["id"], trigger_type="no_reply", delay_value=0, delay_unit="hours",
              fallback_channel="whatsapp")

    client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    drain_queue()
    drain_queue()

    db = SessionLocal()
    try:
        followup = db.query(Message).filter(Message.campaign_id == c["id"], Message.step_id.isnot(None)).one()
        assert followup.channel == "whatsapp"
    finally:
        db.close()


def test_channel_fallback_ignored_when_not_enabled_on_campaign(client, admin_headers, project):
    c = _ready_campaign(client, admin_headers, project)  # whatsapp NOT enabled on this campaign
    _no_weekend_skip(client, admin_headers, c["id"])
    _add_step(client, admin_headers, c["id"], trigger_type="no_reply", delay_value=0, delay_unit="hours",
              fallback_channel="whatsapp")

    client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    drain_queue()
    drain_queue()

    db = SessionLocal()
    try:
        followup = db.query(Message).filter(Message.campaign_id == c["id"], Message.step_id.isnot(None)).one()
        assert followup.channel == "email"  # fallback not usable -- stays on primary
    finally:
        db.close()


def _step_stats(client, headers, cid, step_id):
    steps = client.get(f"/api/campaigns/{cid}/followups/steps", headers=headers).json()
    return next(s for s in steps if s["id"] == step_id)["stats"]


def test_step_performance_excludes_simulated_engagement(client, admin_headers, project):
    """Follow-ups Performance is a filtered rollup of the same Message rows
    Tracking & Reports reads from -- a row tainted by Simulate must drop out
    of the rollup entirely (not just the numerator), or QA/demo activity on a
    test campaign would leak into what's meant to read as real engagement."""
    c = _ready_campaign(client, admin_headers, project)
    _no_weekend_skip(client, admin_headers, c["id"])
    step = _add_step(client, admin_headers, c["id"], trigger_type="not_opened", delay_value=0, delay_unit="hours")

    client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    drain_queue()
    drain_queue()

    db = SessionLocal()
    try:
        followup = db.query(Message).filter(Message.campaign_id == c["id"], Message.step_id == step["id"]).one()
    finally:
        db.close()

    # one real send, zero engagement yet -- genuinely 0%, not "no data"
    stats = _step_stats(client, admin_headers, c["id"], step["id"])
    assert stats == {"sent": 1, "open_rate": 0.0, "click_rate": 0.0, "reply_rate": 0.0}

    sim = client.post(f"/api/campaigns/{c['id']}/followups/messages/{followup.id}/simulate",
                       headers=admin_headers, json={"event": "opened"})
    assert sim.status_code == 200, sim.text

    db = SessionLocal()
    try:
        assert db.get(Message, followup.id).engagement_source == "simulated"
    finally:
        db.close()

    # the now-tainted row drops out of the rollup entirely -- back to "no data"
    stats = _step_stats(client, admin_headers, c["id"], step["id"])
    assert stats == {"sent": 0, "open_rate": None, "click_rate": None, "reply_rate": None}


def test_simulate_blocked_on_non_test_campaign(client, admin_headers, project):
    """Simulate must never be callable against a real (non-test) campaign --
    it writes directly to the Message engagement fields that also drive live
    follow-up trigger logic, so it must not be reachable outside a campaign
    explicitly flagged as a test/sandbox one (see routers/followups.py)."""
    c = make_campaign(client, admin_headers, project["id"])  # is_test_campaign defaults False
    upload_dataset(client, admin_headers, c["id"], CSV)
    client.put(f"/api/campaigns/{c['id']}/content/email", headers=admin_headers,
               json={"subject": "Hi {{Name}}", "body": "Hello {{Name}}"})
    client.put(f"/api/campaigns/{c['id']}", headers=admin_headers, json={"email_enabled": True})

    client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    drain_queue()
    msg = _initial_message(c["id"])

    r = client.post(f"/api/campaigns/{c['id']}/followups/messages/{msg.id}/simulate",
                     headers=admin_headers, json={"event": "opened"})
    assert r.status_code == 403, r.text

    db = SessionLocal()
    try:
        assert db.get(Message, msg.id).opened_at is None
    finally:
        db.close()


def test_resend_archives_followup_run_and_does_not_restart_by_default(client, admin_headers, project):
    """P0.5, revised 2026-08-11: resend no longer rejects a campaign that
    already has messages -- it archives the prior run's FollowUpRun/Message
    rows into FollowUpRunHistory/MessageHistory first (see
    app/campaign_resend.py) and starts a clean run. By default
    (CampaignFollowUpSettings.restart_on_resend=False, the spec's stated
    "safest default" pending a separate decision on restart semantics) a
    resend does NOT auto-start a new follow-up run for a recipient who
    already had one -- see app/followups.py::maybe_start_run."""
    c = _ready_campaign(client, admin_headers, project)
    _no_weekend_skip(client, admin_headers, c["id"])
    _add_step(client, admin_headers, c["id"], trigger_type="no_reply", delay_value=0, delay_unit="hours")

    client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    drain_queue()
    drain_queue()

    db = SessionLocal()
    try:
        assert db.query(FollowUpRun).filter_by(campaign_id=c["id"]).count() == 1
        assert db.query(Message).filter_by(campaign_id=c["id"]).count() == 2  # original + 1 follow-up step
    finally:
        db.close()

    resend = client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    assert resend.status_code == 200, resend.text
    drain_queue()
    drain_queue()

    db = SessionLocal()
    try:
        # Prior run archived, not lost.
        archived_messages = db.query(MessageHistory).filter_by(campaign_id=c["id"], sent_run_number=1).all()
        assert len(archived_messages) == 2
        archived_runs = db.query(FollowUpRunHistory).filter_by(campaign_id=c["id"], sent_run_number=1).all()
        assert len(archived_runs) == 1

        # Live tables hold only the new run's original blast -- no follow-up
        # auto-restarted for it (restart_on_resend defaults to False).
        live_messages = db.query(Message).filter_by(campaign_id=c["id"]).all()
        assert len(live_messages) == 1
        assert {m.sent_run_number for m in live_messages} == {2}
        assert db.query(FollowUpRun).filter_by(campaign_id=c["id"]).count() == 0
    finally:
        db.close()


def test_resend_restarts_followups_when_explicitly_enabled(client, admin_headers, project):
    c = _ready_campaign(client, admin_headers, project)
    _no_weekend_skip(client, admin_headers, c["id"])
    _add_step(client, admin_headers, c["id"], trigger_type="no_reply", delay_value=0, delay_unit="hours")
    settings_update = client.put(f"/api/campaigns/{c['id']}/followups/settings", headers=admin_headers, json={
        "max_touches_per_week": 3, "skip_weekends": False,
        "negative_reply_handling": "tag_and_stop", "default_send_time": None, "restart_on_resend": True,
    })
    assert settings_update.status_code == 200, settings_update.text

    client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    drain_queue()
    drain_queue()

    resend = client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    assert resend.status_code == 200, resend.text
    drain_queue()
    drain_queue()

    db = SessionLocal()
    try:
        # A fresh follow-up run started for the new send, and it too
        # advanced through its step (2 live messages: new blast + follow-up).
        assert db.query(FollowUpRun).filter_by(campaign_id=c["id"]).count() == 1
        live_messages = db.query(Message).filter_by(campaign_id=c["id"]).all()
        assert len(live_messages) == 2
        assert {m.sent_run_number for m in live_messages} == {2}
    finally:
        db.close()
