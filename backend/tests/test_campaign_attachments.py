import app.worker as worker_mod
from tests.conftest import make_campaign, drain_queue, upload_dataset

CSV = "Name,Email Address,Mobile Number\nAlice,alice@example.com,9876543210\n"


def test_upload_list_and_delete_attachment(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])

    r = client.post(f"/api/campaigns/{c['id']}/attachments", headers=admin_headers,
                    files={"file": ("brochure.pdf", b"%PDF-1.4 fake content", "application/pdf")})
    assert r.status_code == 200, r.text
    att = r.json()
    assert att["filename"] == "brochure.pdf"
    assert att["content_type"] == "application/pdf"
    assert att["size_bytes"] == len(b"%PDF-1.4 fake content")

    listed = client.get(f"/api/campaigns/{c['id']}/attachments", headers=admin_headers).json()
    assert len(listed) == 1
    assert listed[0]["id"] == att["id"]

    d = client.delete(f"/api/campaigns/{c['id']}/attachments/{att['id']}", headers=admin_headers)
    assert d.status_code == 200
    assert client.get(f"/api/campaigns/{c['id']}/attachments", headers=admin_headers).json() == []


def test_dangerous_extension_rejected(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    r = client.post(f"/api/campaigns/{c['id']}/attachments", headers=admin_headers,
                    files={"file": ("payload.exe", b"MZ\x90\x00", "application/octet-stream")})
    assert r.status_code == 400
    assert "not allowed" in r.json()["detail"]
    assert client.get(f"/api/campaigns/{c['id']}/attachments", headers=admin_headers).json() == []


def test_total_size_cap_enforced_across_multiple_uploads(client, admin_headers, project):
    """The 10MB cap (app/storage.py::MAX_CAMPAIGN_ATTACHMENTS_BYTES) applies to
    the campaign's attachment total, not any single file -- two files each
    under the cap but summing over it must still be rejected."""
    c = make_campaign(client, admin_headers, project["id"])
    six_mb = b"a" * (6 * 1024 * 1024)

    first = client.post(f"/api/campaigns/{c['id']}/attachments", headers=admin_headers,
                        files={"file": ("part1.bin", six_mb, "application/octet-stream")})
    assert first.status_code == 200, first.text

    second = client.post(f"/api/campaigns/{c['id']}/attachments", headers=admin_headers,
                         files={"file": ("part2.bin", six_mb, "application/octet-stream")})
    assert second.status_code == 400
    assert "10MB" in second.json()["detail"]

    # Rejected upload must not have been persisted.
    listed = client.get(f"/api/campaigns/{c['id']}/attachments", headers=admin_headers).json()
    assert len(listed) == 1


def test_empty_file_rejected(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    r = client.post(f"/api/campaigns/{c['id']}/attachments", headers=admin_headers,
                    files={"file": ("empty.txt", b"", "text/plain")})
    assert r.status_code == 400


def test_attachments_scoped_to_campaign(client, admin_headers, project):
    c1 = make_campaign(client, admin_headers, project["id"], "Camp 1")
    c2 = make_campaign(client, admin_headers, project["id"], "Camp 2")
    r = client.post(f"/api/campaigns/{c1['id']}/attachments", headers=admin_headers,
                    files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 200
    assert client.get(f"/api/campaigns/{c2['id']}/attachments", headers=admin_headers).json() == []

    # Deleting via the wrong campaign id must 404, not delete another campaign's file.
    att_id = r.json()["id"]
    d = client.delete(f"/api/campaigns/{c2['id']}/attachments/{att_id}", headers=admin_headers)
    assert d.status_code == 404


def test_uploaded_attachment_reaches_send_campaign_email_at_send_time(client, admin_headers, project, monkeypatch):
    """End-to-end: a file attached via the Content tab must actually be read
    back off disk and passed into the resolver at send time. The resolver's
    own per-tier attachment pass-through (project SMTP / admin SMTP / Graph)
    is covered directly in tests/test_mailer.py; this test only proves the
    worker wires the stored attachment bytes into that call in the first
    place."""
    c = make_campaign(client, admin_headers, project["id"])
    upload_dataset(client, admin_headers, c['id'], CSV)
    client.put(f"/api/campaigns/{c['id']}/content/email", headers=admin_headers,
              json={"subject": "Hi {{Name}}", "body": "Hello {{Name}}"})
    client.put(f"/api/campaigns/{c['id']}", headers=admin_headers, json={"email_enabled": True})

    upload = client.post(f"/api/campaigns/{c['id']}/attachments", headers=admin_headers,
                         files={"file": ("brochure.txt", b"attachment body", "text/plain")})
    assert upload.status_code == 200

    # Make email_channel_configured() true (O365 tier) so the worker takes the
    # real send path instead of falling back to simulated dispatch.
    s = worker_mod.settings
    monkeypatch.setattr(s, "azure_tenant_id", "tenant")
    monkeypatch.setattr(s, "o365_client_id", "client")
    monkeypatch.setattr(s, "o365_client_secret", "secret")
    monkeypatch.setattr(s, "o365_from_email", "from@acme.com")

    calls = []

    def fake_send_campaign_email(project, to, subject, body, is_html=False, attachments=None, reply_to=None):
        calls.append(attachments)
        return "provider-id"
    monkeypatch.setattr(worker_mod, "send_campaign_email", fake_send_campaign_email)

    send = client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    assert send.status_code == 200
    drain_queue()

    assert len(calls) == 1
    assert calls[0] == [("brochure.txt", b"attachment body", "text/plain")]


def test_no_attachments_passes_none_not_empty_list(client, admin_headers, project, monkeypatch):
    """Regression guard for acceptance criterion 5: a campaign with no
    attachments must not regress to sending an empty attachments list (which
    would still build empty MIME parts / Graph payload entries)."""
    c = make_campaign(client, admin_headers, project["id"])
    upload_dataset(client, admin_headers, c['id'], CSV)
    client.put(f"/api/campaigns/{c['id']}/content/email", headers=admin_headers,
              json={"subject": "Hi {{Name}}", "body": "Hello {{Name}}"})
    client.put(f"/api/campaigns/{c['id']}", headers=admin_headers, json={"email_enabled": True})

    s = worker_mod.settings
    monkeypatch.setattr(s, "azure_tenant_id", "tenant")
    monkeypatch.setattr(s, "o365_client_id", "client")
    monkeypatch.setattr(s, "o365_client_secret", "secret")
    monkeypatch.setattr(s, "o365_from_email", "from@acme.com")

    calls = []

    def fake_send_campaign_email(project, to, subject, body, is_html=False, attachments=None, reply_to=None):
        calls.append(attachments)
        return "provider-id"
    monkeypatch.setattr(worker_mod, "send_campaign_email", fake_send_campaign_email)

    client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    drain_queue()

    assert calls == [None]
