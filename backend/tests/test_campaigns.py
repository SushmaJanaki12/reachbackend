from app.database import SessionLocal
from app.models import Message, MessageHistory
from tests.conftest import make_campaign, drain_queue, _token

# Clean fixture used by the shared `_upload()` helper -- tests that only care
# about "a campaign with some recipients" (content, send, tracking, preview)
# use this so they aren't coupled to dataset-validation behavior. Tests that
# exercise validation itself use MESSY_CSV below.
CSV = (
    "Name,Email Address,Mobile Number,Company\n"
    "Alice,alice@example.com,9876543210,Acme\n"
    "Bob,bob@example.com,9123456789,Beta\n"
    "Carol,carol@example.com,9988776655,Gamma\n"
)

MESSY_CSV = (
    "Name,Email Address,Mobile Number,Company\n"
    "Alice,alice@example.com,9876543210,Acme\n"
    "Bob,bad-email,9123456789,Beta\n"
    "Carol,carol@example.com,not-a-number,Gamma\n"
    "Dave,alice@example.com,9000000000,Acme\n"
    "Eve,eve@gmial.com,9111111111,Delta\n"
)


def _validate(client, headers, cid, csv=CSV):
    r = client.post(f"/api/campaigns/{cid}/dataset/validate", headers=headers,
                     files={"file": ("data.csv", csv, "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()


def _confirm_mapping(client, headers, cid, session):
    r = client.post(f"/api/campaigns/{cid}/dataset/validate/{session['id']}/mapping", headers=headers,
                     json={"column_mapping": session["column_mapping"]})
    assert r.status_code == 200, r.text
    return r.json()


def _upload(client, headers, cid, csv=CSV, mode="valid_only"):
    """Runs the full validate -> confirm mapping -> import flow and returns
    the /import response (same CampaignOut shape the old blind-upload
    endpoint used to return), so tests that only care about the resulting
    recipient list don't need to know about the staging flow."""
    session = _validate(client, headers, cid, csv)
    _confirm_mapping(client, headers, cid, session)
    return client.post(f"/api/campaigns/{cid}/dataset/validate/{session['id']}/import", headers=headers,
                        json={"mode": mode})


def test_create_campaign(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"], "New Camp")
    assert c["status"] == "draft"
    assert c["project_id"] == project["id"]


def test_dataset_upload_and_columns(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    r = _upload(client, admin_headers, c["id"])
    assert r.status_code == 200
    body = r.json()
    assert body["recipient_count"] == 3
    assert "Company" in body["columns"]


def test_dataset_missing_email_column_flags_every_row_and_blocks_import(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    bad = "Name,Company\nAlice,Acme\n"
    session = _validate(client, admin_headers, c["id"], bad)
    assert session["summary"]["ready_for_import"] == 0
    assert any(i["issue_type"] == "missing_email" for i in session["issues"])

    _confirm_mapping(client, admin_headers, c["id"], session)
    imp = client.post(f"/api/campaigns/{c['id']}/dataset/validate/{session['id']}/import",
                       headers=admin_headers, json={"mode": "valid_only"})
    assert imp.status_code == 400


def test_header_variants_with_trailing_whitespace_are_mapped_not_flagged_missing(client, admin_headers, project):
    """s.no / "name " / email / "phone number " (trailing spaces, no exact
    "Phone", no First/Last split, s.no not a recognized field) should all
    resolve via header normalization + the synonym table, not fall through
    to a false missing-mandatory-column error."""
    c = make_campaign(client, admin_headers, project["id"])
    csv = "s.no,name ,email,phone number \n1,John Doe,john@example.com,9876543210\n"
    session = _validate(client, admin_headers, c["id"], csv)

    assert session["column_mapping"] == {
        "s.no": None, "name": "name", "email": "email", "phone number": "mobile",
    }
    assert not any(i["issue_type"] == "missing_email" for i in session["issues"])
    assert session["summary"]["ready_for_import"] == 1


def test_import_requires_confirmed_mapping(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    session = _validate(client, admin_headers, c["id"])
    assert session["mapping_confirmed"] is False
    imp = client.post(f"/api/campaigns/{c['id']}/dataset/validate/{session['id']}/import",
                       headers=admin_headers, json={"mode": "valid_only"})
    assert imp.status_code == 400


def test_validation_flags_duplicates_invalid_email_and_typos(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    session = _validate(client, admin_headers, c["id"], MESSY_CSV)
    issue_types = {i["issue_type"] for i in session["issues"]}
    assert "invalid_email" in issue_types    # Bob: "bad-email"
    assert "duplicate_email" in issue_types  # Dave: duplicate of Alice's email
    assert "possible_typo" in issue_types    # Eve: gmial.com
    assert "invalid_phone" in issue_types    # Carol: "not-a-number"

    typo_issue = next(i for i in session["issues"] if i["issue_type"] == "possible_typo")
    assert typo_issue["suggested_fix"] == "eve@gmail.com"

    # ready_for_import (valid_only): only Alice is fully clean.
    # ready_for_import_with_overrides: Alice + Carol (phone warning) + Eve (typo warning);
    # Bob (error) and Dave (duplicate) stay excluded either way.
    assert session["summary"]["ready_for_import"] == 1
    assert session["summary"]["ready_for_import_with_overrides"] == 3


def test_apply_fix_corrects_typo_and_import_valid_only_then_includes_it(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    session = _validate(client, admin_headers, c["id"], MESSY_CSV)
    typo_issue = next(i for i in session["issues"] if i["issue_type"] == "possible_typo")

    fixed = client.post(f"/api/campaigns/{c['id']}/dataset/validate/{session['id']}/fixes",
                         headers=admin_headers, json={"fix_ids": [typo_issue["fix_id"]]})
    assert fixed.status_code == 200
    assert not any(i["issue_type"] == "possible_typo" for i in fixed.json()["issues"])
    assert fixed.json()["summary"]["ready_for_import"] == 2  # Alice + now-fixed Eve

    _confirm_mapping(client, admin_headers, c["id"], session)
    imp = client.post(f"/api/campaigns/{c['id']}/dataset/validate/{session['id']}/import",
                       headers=admin_headers, json={"mode": "valid_only"})
    assert imp.status_code == 200
    assert imp.json()["recipient_count"] == 2


def test_ignore_warnings_requires_permission_and_logs_override(client, admin_headers, project):
    uid = next(u["id"] for u in client.get("/api/users", headers=admin_headers).json()
               if u["email"] == "user@reach.io")
    scoped_project = client.post("/api/projects", headers=admin_headers, json={
        "name": "Scoped for override test", "email": "scoped-override@acme.com", "member_ids": [uid],
    }).json()
    c = make_campaign(client, admin_headers, scoped_project["id"])

    session = _validate(client, admin_headers, c["id"], MESSY_CSV)
    _confirm_mapping(client, admin_headers, c["id"], session)

    user_headers = {"Authorization": f"Bearer {_token(client, 'user@reach.io', 'User@123')}"}
    denied = client.post(f"/api/campaigns/{c['id']}/dataset/validate/{session['id']}/import",
                          headers=user_headers, json={"mode": "ignore_warnings"})
    assert denied.status_code == 403

    allowed = client.post(f"/api/campaigns/{c['id']}/dataset/validate/{session['id']}/import",
                           headers=admin_headers, json={"mode": "ignore_warnings"})
    assert allowed.status_code == 200
    assert allowed.json()["recipient_count"] == 3  # Alice, Carol, Eve -- Bob/Dave still excluded


def test_download_validation_report(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    session = _validate(client, admin_headers, c["id"], MESSY_CSV)
    r = client.get(f"/api/campaigns/{c['id']}/dataset/validate/{session['id']}/report", headers=admin_headers)
    assert r.status_code == 200
    assert "invalid_email" in r.text
    assert "Row" in r.text


def test_undo_import_batch_removes_only_that_batch(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    imported = _upload(client, admin_headers, c["id"]).json()
    assert imported["recipient_count"] == 3
    batch_id = imported["last_import_batch_id"]
    assert batch_id

    client.post(f"/api/campaigns/{c['id']}/recipients", headers=admin_headers,
                json={"name": "Manual", "email": "manual@example.com", "mobile": "9000000002"})
    assert len(client.get(f"/api/campaigns/{c['id']}/recipients", headers=admin_headers).json()) == 4

    undone = client.post(f"/api/campaigns/{c['id']}/dataset/batches/{batch_id}/undo", headers=admin_headers)
    assert undone.status_code == 200

    remaining = client.get(f"/api/campaigns/{c['id']}/recipients", headers=admin_headers).json()
    assert [r["name"] for r in remaining] == ["Manual"]


def test_add_and_remove_recipient(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    _upload(client, admin_headers, c["id"])
    add = client.post(f"/api/campaigns/{c['id']}/recipients", headers=admin_headers,
                      json={"name": "Dave", "email": "dave@example.com", "mobile": "9000000000"})
    assert add.status_code == 200
    rid = add.json()["id"]
    assert len(client.get(f"/api/campaigns/{c['id']}/recipients", headers=admin_headers).json()) == 4

    delr = client.delete(f"/api/campaigns/{c['id']}/recipients/{rid}", headers=admin_headers)
    assert delr.status_code == 200
    assert len(client.get(f"/api/campaigns/{c['id']}/recipients", headers=admin_headers).json()) == 3


def test_toggle_recipient_active_only_affects_that_recipient_and_keeps_order(client, admin_headers, project):
    """Regression test: toggling one recipient's active flag must not change any
    other recipient's state, and the list order must stay stable (by id) across
    the update -- Postgres can otherwise relocate an updated row's tuple, and
    without an explicit ORDER BY the row would appear to jump to the end of the
    list on the next fetch, looking like a different recipient got toggled."""
    c = make_campaign(client, admin_headers, project["id"])
    _upload(client, admin_headers, c["id"])
    before = client.get(f"/api/campaigns/{c['id']}/recipients", headers=admin_headers).json()
    assert [r["name"] for r in before] == ["Alice", "Bob", "Carol"]
    bob_id = next(r["id"] for r in before if r["name"] == "Bob")

    patch = client.patch(f"/api/campaigns/{c['id']}/recipients/{bob_id}", headers=admin_headers, json={"active": False})
    assert patch.status_code == 200

    after = client.get(f"/api/campaigns/{c['id']}/recipients", headers=admin_headers).json()
    assert [r["name"] for r in after] == ["Alice", "Bob", "Carol"]
    active_by_name = {r["name"]: r["active"] for r in after}
    assert active_by_name == {"Alice": True, "Bob": False, "Carol": True}


def test_add_recipient_requires_contact(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    r = client.post(f"/api/campaigns/{c['id']}/recipients", headers=admin_headers, json={"name": "NoContact"})
    assert r.status_code == 400


def test_content_and_preview(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    _upload(client, admin_headers, c["id"])
    client.put(f"/api/campaigns/{c['id']}/content/email", headers=admin_headers,
               json={"subject": "Hi {{Name}}", "body": "Hello {{Name}} from {{Company}}"})
    r = client.post(f"/api/campaigns/{c['id']}/preview", headers=admin_headers,
                    json={"channel": "email", "subject": "Hi {{Name}}", "body": "Hello {{Name}} from {{Company}}"})
    assert r.status_code == 200
    assert r.json()["subject"] == "Hi Alice"
    assert r.json()["body"] == "Hello Alice from Acme"


def test_html_in_body_is_treated_as_literal_text(client, admin_headers, project):
    """The Email content editor is plain text -- there is no HTML rendering
    mode. If markup ends up in a preview payload it must survive as literal
    characters, not be parsed or stripped, and the response must not carry
    any HTML-vs-plain-text flag."""
    c = make_campaign(client, admin_headers, project["id"])
    _upload(client, admin_headers, c["id"])
    html_body = "Hello {{Name}}, <b>bold</b> <img src=x onerror=alert(1)> <script>evil()</script>"

    r = client.post(f"/api/campaigns/{c['id']}/preview", headers=admin_headers,
                    json={"channel": "email", "subject": "Hi {{Name}}", "body": html_body})
    assert r.status_code == 200
    assert "is_html" not in r.json()
    # Placeholders resolve, but the markup itself passes through untouched as text.
    assert r.json()["body"] == html_body.replace("{{Name}}", "Alice")


def test_save_html_in_email_content_is_rejected(client, admin_headers, project):
    """Content is meant to be plain text with {{Placeholder}} tokens. A since-reverted
    HTML/signature feature used to let raw markup be saved into email content -- the
    save endpoint must now reject it outright rather than persisting it."""
    c = make_campaign(client, admin_headers, project["id"])
    _upload(client, admin_headers, c["id"])
    html_body = "Hello {{Name}}, <b>bold</b> <img src=x onerror=alert(1)>"

    body_rejected = client.put(f"/api/campaigns/{c['id']}/content/email", headers=admin_headers,
                                json={"subject": "Hi {{Name}}", "body": html_body})
    assert body_rejected.status_code == 400

    subject_rejected = client.put(f"/api/campaigns/{c['id']}/content/email", headers=admin_headers,
                                   json={"subject": "Hi <b>{{Name}}</b>", "body": "Hello {{Name}}"})
    assert subject_rejected.status_code == 400

    # Plain text with placeholders still saves fine.
    ok = client.put(f"/api/campaigns/{c['id']}/content/email", headers=admin_headers,
                     json={"subject": "Hi {{Name}}", "body": "Hello {{Name}} from {{Company}}"})
    assert ok.status_code == 200


def test_send_simulated_and_summary(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    _upload(client, admin_headers, c["id"])
    # Manually add recipients with bad contact info -- decoupled from the bulk
    # import validation flow (which would now block/exclude these), so this
    # test can still exercise send-time per-message failure handling.
    client.post(f"/api/campaigns/{c['id']}/recipients", headers=admin_headers,
                json={"name": "BadEmail", "email": "not-an-email", "mobile": "9000000001"})
    client.post(f"/api/campaigns/{c['id']}/recipients", headers=admin_headers,
                json={"name": "BadMobile", "email": "badmobile@example.com", "mobile": "notanumber"})
    for ch in ("email", "whatsapp", "sms"):
        client.put(f"/api/campaigns/{c['id']}/content/{ch}", headers=admin_headers,
                   json={"subject": "Hi {{Name}}", "body": "Hello {{Name}}"})
    client.put(f"/api/campaigns/{c['id']}", headers=admin_headers,
               json={"email_enabled": True, "whatsapp_enabled": True, "sms_enabled": True})

    send = client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    assert send.status_code == 200
    assert send.json()["status"] == "sending"
    drain_queue()

    s = client.get(f"/api/campaigns/{c['id']}/summary", headers=admin_headers).json()
    assert s["status"] == "completed"
    # 5 recipients x 3 channels = 15 messages
    assert s["total_messages"] == 15
    # BadEmail fails email (1); BadMobile fails whatsapp & sms (2) = 3 failures
    assert s["failed"] == 3
    assert s["total_recipients"] == 5


def test_send_without_recipients_fails(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    client.put(f"/api/campaigns/{c['id']}/content/email", headers=admin_headers, json={"body": "hi"})
    r = client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    assert r.status_code == 400


def test_send_while_sending_rejected(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    _upload(client, admin_headers, c["id"])
    client.put(f"/api/campaigns/{c['id']}/content/email", headers=admin_headers, json={"body": "Hello {{Name}}"})
    client.put(f"/api/campaigns/{c['id']}", headers=admin_headers, json={"email_enabled": True})

    first = client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    assert first.status_code == 200
    assert first.json()["status"] == "sending"

    # A second send while the first is still in flight is rejected -- avoids
    # two overlapping runs racing on the same Message rows.
    concurrent_resend = client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    assert concurrent_resend.status_code == 409

    drain_queue()
    completed = client.get(f"/api/campaigns/{c['id']}", headers=admin_headers).json()
    assert completed["status"] == "completed"


def test_resend_after_completion_archives_prior_run_and_starts_fresh(client, admin_headers, project):
    """P0.5, revised 2026-08-11: resend used to be blocked outright once a
    campaign had any Message rows (an earlier revision of this same fix --
    see git history). Resend is now allowed repeatedly: the prior run's
    Message rows are archived into MessageHistory (see
    app/campaign_resend.py) rather than destroyed, and the live `messages`
    table starts clean for the new run."""
    c = make_campaign(client, admin_headers, project["id"])
    _upload(client, admin_headers, c["id"])  # 3 recipients (Alice, Bob, Carol)
    client.put(f"/api/campaigns/{c['id']}/content/email", headers=admin_headers, json={"body": "Hello {{Name}}"})
    client.put(f"/api/campaigns/{c['id']}", headers=admin_headers, json={"email_enabled": True})

    first = client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    assert first.status_code == 200
    drain_queue()
    first_recipients = client.get(f"/api/campaigns/{c['id']}/recipients", headers=admin_headers).json()

    db = SessionLocal()
    try:
        first_run_ids = {m.id for m in db.query(Message).filter_by(campaign_id=c["id"]).all()}
        assert len(first_run_ids) == 3
    finally:
        db.close()

    resend = client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    assert resend.status_code == 200, resend.text
    assert resend.json()["status"] == "sending"
    drain_queue()

    # Recipients (and the campaign itself) are untouched by a resend.
    after_recipients = client.get(f"/api/campaigns/{c['id']}/recipients", headers=admin_headers).json()
    assert first_recipients == after_recipients

    db = SessionLocal()
    try:
        # Prior run's rows archived intact, not deleted.
        archived = db.query(MessageHistory).filter_by(campaign_id=c["id"], sent_run_number=1).all()
        assert len(archived) == 3
        assert {a.to_address for a in archived} == {r["email"] for r in first_recipients}
        assert all(a.status == "sent" for a in archived)

        # Live table now holds only the new run -- different Message rows,
        # tagged with the new run number, none of the old ids reused.
        live = db.query(Message).filter_by(campaign_id=c["id"]).all()
        assert len(live) == 3
        assert {m.sent_run_number for m in live} == {2}
        assert {m.id for m in live}.isdisjoint(first_run_ids)
    finally:
        db.close()

    # Both runs are independently visible via the run-scoped tracking API.
    run1_rows = client.get(f"/api/campaigns/{c['id']}/tracking/email",
                            headers=admin_headers, params={"run": 1}).json()
    assert len(run1_rows) == 3
    current_rows = client.get(f"/api/campaigns/{c['id']}/tracking/email", headers=admin_headers).json()
    assert len(current_rows) == 3
    assert {r["id"] for r in run1_rows}.isdisjoint({r["id"] for r in current_rows})

    runs = client.get(f"/api/campaigns/{c['id']}/send-runs", headers=admin_headers).json()
    assert [r["run_number"] for r in runs] == [1, 2]
    assert runs[1]["is_current"] is True and runs[0]["is_current"] is False
    assert runs[0]["message_count"] == 3 and runs[1]["message_count"] == 3


def test_duplicate_campaign_is_clean_draft_sendable_again(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"], name="Original")
    _upload(client, admin_headers, c["id"])
    client.put(f"/api/campaigns/{c['id']}/content/email", headers=admin_headers,
               json={"subject": "Hi {{Name}}", "body": "Hello {{Name}}"})
    client.put(f"/api/campaigns/{c['id']}", headers=admin_headers, json={"email_enabled": True})

    send = client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    assert send.status_code == 200
    drain_queue()
    completed = client.get(f"/api/campaigns/{c['id']}", headers=admin_headers).json()
    assert completed["status"] == "completed"

    dup = client.post(f"/api/campaigns/{c['id']}/duplicate", headers=admin_headers)
    assert dup.status_code == 200, dup.text
    clone = dup.json()
    assert clone["id"] != c["id"]
    assert clone["status"] == "draft"
    assert clone["name"] == "Original (copy)"
    assert clone["email_enabled"] is True
    # Config carried over, but not recipients or Message history.
    assert clone["recipient_count"] == 0

    clone_contents = client.get(f"/api/campaigns/{clone['id']}/content", headers=admin_headers).json()
    email_content = next(c for c in clone_contents if c["channel"] == "email")
    assert email_content["subject"] == "Hi {{Name}}"
    assert email_content["body"] == "Hello {{Name}}"

    # The clone has no messages yet and is entirely independent of the
    # source campaign's own Message history (unlike resending the source
    # in place, which archives and replaces it -- see test_campaign_resend.py).
    _upload(client, admin_headers, clone["id"])
    clone_send = client.post(f"/api/campaigns/{clone['id']}/send", headers=admin_headers)
    assert clone_send.status_code == 200, clone_send.text


def test_preview_rejects_recipient_from_another_campaign(client, admin_headers, project):
    c1 = make_campaign(client, admin_headers, project["id"], "Camp1")
    c2 = make_campaign(client, admin_headers, project["id"], "Camp2")
    _upload(client, admin_headers, c1["id"])
    _upload(client, admin_headers, c2["id"])
    other_recipient_id = client.get(f"/api/campaigns/{c2['id']}/recipients", headers=admin_headers).json()[0]["id"]

    r = client.post(f"/api/campaigns/{c1['id']}/preview", headers=admin_headers,
                    json={"channel": "email", "subject": "Hi", "body": "Hi",
                          "recipient_id": other_recipient_id})
    assert r.status_code == 404


def test_tracking_and_export(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    _upload(client, admin_headers, c["id"])
    client.post(f"/api/campaigns/{c['id']}/recipients", headers=admin_headers,
                json={"name": "BadEmail", "email": "not-an-email", "mobile": "9000000003"})
    client.put(f"/api/campaigns/{c['id']}/content/email", headers=admin_headers, json={"body": "Hello {{Name}}"})
    client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    drain_queue()

    tr = client.get(f"/api/campaigns/{c['id']}/tracking/email", headers=admin_headers)
    assert tr.status_code == 200
    rows = tr.json()
    assert len(rows) == 4
    assert any(m["status"] == "failed" for m in rows)  # BadEmail

    csv = client.get(f"/api/campaigns/{c['id']}/report.csv", headers=admin_headers)
    assert csv.status_code == 200
    assert "Channel" in csv.text


def test_list_all_campaigns(client, admin_headers, project):
    make_campaign(client, admin_headers, project["id"], "AllList")
    r = client.get("/api/campaigns", headers=admin_headers)
    assert r.status_code == 200
    assert any(c["name"] == "AllList" for c in r.json())
    assert all("project_name" in c for c in r.json())
