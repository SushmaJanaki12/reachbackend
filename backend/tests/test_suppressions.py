import app.worker as worker_mod
from tests.conftest import make_campaign, drain_queue, upload_dataset

CSV = (
    "Name,Email Address,Mobile Number,Company\n"
    "Alice,alice@example.com,9876543210,Acme\n"
    "Bob,bob@example.com,9123456789,Beta\n"
)


def _upload(client, headers, cid, csv=CSV):
    return upload_dataset(client, headers, cid, csv)


def _configure_real_providers(monkeypatch):
    """Flip settings so the worker's process_message() takes the real-provider
    branches, then stub the provider calls themselves so no network I/O happens."""
    s = worker_mod.settings
    monkeypatch.setattr(s, "azure_tenant_id", "tenant")
    monkeypatch.setattr(s, "o365_client_id", "client")
    monkeypatch.setattr(s, "o365_client_secret", "secret")
    monkeypatch.setattr(s, "o365_from_email", "from@acme.com")
    monkeypatch.setattr(s, "sms_username", "user")
    monkeypatch.setattr(s, "sms_password", "pass")
    monkeypatch.setattr(s, "sms_from", "ACME")
    monkeypatch.setattr(s, "sms_api_url", "https://example.com/api")

    email_calls, sms_calls = [], []
    monkeypatch.setattr(worker_mod, "send_campaign_email",
                        lambda project, to, subject, body, is_html=False, attachments=None, reply_to=None:
                            (email_calls.append(to), "email-provider-id")[1])
    monkeypatch.setattr(worker_mod, "send_sms",
                        lambda to, body, template_id=None: (sms_calls.append(to), "sms-provider-id")[1])
    return email_calls, sms_calls


def _ready_campaign(client, admin_headers, project, channels=("email", "sms")):
    c = make_campaign(client, admin_headers, project["id"])
    _upload(client, admin_headers, c["id"])
    for ch in channels:
        client.put(f"/api/campaigns/{c['id']}/content/{ch}", headers=admin_headers,
                   json={"subject": "Hi {{Name}}", "body": "Hello {{Name}}"})
    client.put(f"/api/campaigns/{c['id']}", headers=admin_headers,
              json={"email_enabled": "email" in channels, "sms_enabled": "sms" in channels})
    return c


def _suppress(client, admin_headers, project_id, contact, channel, reason="manual"):
    r = client.post(f"/api/projects/{project_id}/suppressions", headers=admin_headers,
                    json={"contact": contact, "channel": channel, "reason": reason})
    assert r.status_code == 200, r.text
    return r.json()


def test_suppressed_contact_never_calls_provider(client, admin_headers, project, monkeypatch):
    email_calls, sms_calls = _configure_real_providers(monkeypatch)
    _suppress(client, admin_headers, project["id"], "alice@example.com", "email")

    c = _ready_campaign(client, admin_headers, project)
    send = client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    assert send.status_code == 200
    assert send.json()["status"] == "sending"
    drain_queue()

    rows = client.get(f"/api/campaigns/{c['id']}/tracking/email", headers=admin_headers).json()
    alice = next(m for m in rows if m["to_address"] == "alice@example.com")
    assert alice["status"] == "suppressed"
    assert "opted out" in alice["error"]
    assert "alice@example.com" not in email_calls

    bob = next(m for m in rows if m["to_address"] == "bob@example.com")
    assert bob["status"] == "sent"
    assert "bob@example.com" in email_calls

    summary = client.get(f"/api/campaigns/{c['id']}/summary", headers=admin_headers).json()
    assert summary["suppressed"] == 1
    assert summary["status"] == "completed"


def test_suppression_is_per_channel(client, admin_headers, project, monkeypatch):
    email_calls, sms_calls = _configure_real_providers(monkeypatch)
    _suppress(client, admin_headers, project["id"], "alice@example.com", "email")

    c = _ready_campaign(client, admin_headers, project, channels=("email", "sms"))
    client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    drain_queue()

    email_rows = client.get(f"/api/campaigns/{c['id']}/tracking/email", headers=admin_headers).json()
    sms_rows = client.get(f"/api/campaigns/{c['id']}/tracking/sms", headers=admin_headers).json()

    alice_email = next(m for m in email_rows if m["to_address"] == "alice@example.com")
    alice_sms = next(m for m in sms_rows if m["recipient_name"] == "Alice")
    assert alice_email["status"] == "suppressed"
    assert alice_sms["status"] == "sent"
    assert "9876543210" in sms_calls


def test_suppression_is_project_scoped(client, admin_headers, project, monkeypatch):
    email_calls, _ = _configure_real_providers(monkeypatch)

    other = client.post("/api/projects", headers=admin_headers, json={
        "name": "Other Project", "email": "other@acme.com",
    })
    assert other.status_code == 200, other.text
    other_project = other.json()

    _suppress(client, admin_headers, other_project["id"], "alice@example.com", "email")

    c = _ready_campaign(client, admin_headers, project, channels=("email",))
    client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    drain_queue()

    rows = client.get(f"/api/campaigns/{c['id']}/tracking/email", headers=admin_headers).json()
    alice = next(m for m in rows if m["to_address"] == "alice@example.com")
    assert alice["status"] == "sent"
    assert "alice@example.com" in email_calls


def test_add_suppression_is_idempotent(client, admin_headers, project):
    first = _suppress(client, admin_headers, project["id"], "  Alice@Example.com ", "email")
    second = _suppress(client, admin_headers, project["id"], "alice@example.com", "email")
    assert first["id"] == second["id"]
    assert first["contact"] == "alice@example.com"

    listing = client.get(f"/api/projects/{project['id']}/suppressions", headers=admin_headers).json()
    assert len([s for s in listing if s["contact"] == "alice@example.com"]) == 1


def test_remove_suppression(client, admin_headers, project):
    row = _suppress(client, admin_headers, project["id"], "bob@example.com", "sms")
    delr = client.delete(f"/api/projects/{project['id']}/suppressions/{row['id']}", headers=admin_headers)
    assert delr.status_code == 200
    listing = client.get(f"/api/projects/{project['id']}/suppressions", headers=admin_headers).json()
    assert all(s["id"] != row["id"] for s in listing)


def test_user_without_permission_cannot_manage_suppressions(client, user_headers, project):
    r = client.post(f"/api/projects/{project['id']}/suppressions", headers=user_headers,
                    json={"contact": "x@example.com", "channel": "email"})
    assert r.status_code == 403
