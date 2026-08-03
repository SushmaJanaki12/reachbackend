from tests.conftest import make_campaign, drain_queue

CSV = (
    "Name,Email Address,Mobile Number,Company\n"
    "Alice,alice@example.com,9876543210,Acme\n"
    "Bob,bad-email,9123456789,Beta\n"
    "Carol,carol@example.com,not-a-number,Gamma\n"
)


def _upload(client, headers, cid, csv=CSV):
    return client.post(f"/api/campaigns/{cid}/dataset", headers=headers,
                       files={"file": ("data.csv", csv, "text/csv")})


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


def test_dataset_missing_mandatory_column(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    bad = "Name,Company\nAlice,Acme\n"
    r = _upload(client, admin_headers, c["id"], bad)
    assert r.status_code == 400
    assert "Mobile" in r.json()["detail"] or "Email" in r.json()["detail"]


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
    # 3 recipients x 3 channels = 9 messages
    assert s["total_messages"] == 9
    # Bob invalid email + Carol invalid mobile (whatsapp & sms) = 3 failures
    assert s["failed"] == 3
    assert s["total_recipients"] == 3


def test_send_without_recipients_fails(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    client.put(f"/api/campaigns/{c['id']}/content/email", headers=admin_headers, json={"body": "hi"})
    r = client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    assert r.status_code == 400


def test_send_completed_campaign_rejected(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    _upload(client, admin_headers, c["id"])
    client.put(f"/api/campaigns/{c['id']}/content/email", headers=admin_headers, json={"body": "Hello {{Name}}"})
    client.put(f"/api/campaigns/{c['id']}", headers=admin_headers, json={"email_enabled": True})

    first = client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    assert first.status_code == 200
    assert first.json()["status"] == "sending"

    resend = client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    assert resend.status_code == 409

    drain_queue()
    completed = client.get(f"/api/campaigns/{c['id']}", headers=admin_headers).json()
    assert completed["status"] == "completed"

    resend_after_complete = client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    assert resend_after_complete.status_code == 409


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
    client.put(f"/api/campaigns/{c['id']}/content/email", headers=admin_headers, json={"body": "Hello {{Name}}"})
    client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    drain_queue()

    tr = client.get(f"/api/campaigns/{c['id']}/tracking/email", headers=admin_headers)
    assert tr.status_code == 200
    rows = tr.json()
    assert len(rows) == 3
    assert any(m["status"] == "failed" for m in rows)  # Bob

    csv = client.get(f"/api/campaigns/{c['id']}/report.csv", headers=admin_headers)
    assert csv.status_code == 200
    assert "Channel" in csv.text


def test_list_all_campaigns(client, admin_headers, project):
    make_campaign(client, admin_headers, project["id"], "AllList")
    r = client.get("/api/campaigns", headers=admin_headers)
    assert r.status_code == 200
    assert any(c["name"] == "AllList" for c in r.json())
    assert all("project_name" in c for c in r.json())
