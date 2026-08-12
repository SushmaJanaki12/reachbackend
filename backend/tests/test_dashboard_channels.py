def test_channels_status_simulated(client, admin_headers):
    r = client.get("/api/channels/status", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    # providers were blanked for tests -> everything simulated
    assert body["email"]["live"] is False
    assert body["sms"]["live"] is False
    assert body["whatsapp"]["live"] is False


def test_channels_status_reflects_project_smtp(client, admin_headers, project):
    """The Review & Send channel card must match what app.mailer.send_campaign_email
    will actually do for this project -- not the workspace-level O365 config
    (that mismatch was the "hardcodes Office 365" addendum bug)."""
    r = client.get("/api/channels/status", params={"project_id": project["id"]}, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["email"]["live"] is False  # no project SMTP configured yet -> unchanged

    smtp_payload = {
        "smtp_enabled": True, "smtp_host": "smtp.acme.com", "smtp_port": 587,
        "smtp_encryption": "starttls", "smtp_username": "u", "smtp_password": "s3cret",
        "smtp_from_name": "Acme", "smtp_from_email": "noreply@acme.com",
    }
    client.put(f"/api/projects/{project['id']}", headers=admin_headers, json=smtp_payload)

    r = client.get("/api/channels/status", params={"project_id": project["id"]}, headers=admin_headers)
    assert r.status_code == 200
    email = r.json()["email"]
    assert email["live"] is True
    assert "smtp.acme.com" in email["provider"]

    # disabling the override falls back to the workspace default again
    client.put(f"/api/projects/{project['id']}", headers=admin_headers, json={"smtp_enabled": False})
    r = client.get("/api/channels/status", params={"project_id": project["id"]}, headers=admin_headers)
    assert r.json()["email"]["live"] is False


def test_email_status_not_configured(client, admin_headers):
    r = client.get("/api/email/status", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["configured"] is False


def test_sms_status_not_configured(client, admin_headers):
    r = client.get("/api/sms/status", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["configured"] is False


def test_dashboard_overview_shape(client, admin_headers):
    r = client.get("/api/dashboard/overview", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    for key in ("totals", "campaign_status", "by_channel", "delivery", "recent_projects", "top_campaigns"):
        assert key in body
    for key in ("projects", "campaigns", "recipients", "messages", "success_rate"):
        assert key in body["totals"]
    assert body["by_channel"].keys() >= {"email", "whatsapp", "sms"}


def test_dashboard_scoped_for_user(client, user_headers):
    # user only sees assigned projects; endpoint must still succeed
    r = client.get("/api/dashboard/overview", headers=user_headers)
    assert r.status_code == 200
    assert "totals" in r.json()


def test_dashboard_excludes_test_campaigns(client, admin_headers, project):
    """P1.5 gap check: a test campaign's fabricated (Simulate-driven) data
    must never inflate the cross-campaign analytics on this dashboard --
    verifies the exclusion routers/dashboard.py already applies
    (Campaign.is_test_campaign.is_(False)), which had no direct test."""
    before = client.get("/api/dashboard/overview", headers=admin_headers).json()["totals"]["campaigns"]

    client.post("/api/campaigns", headers=admin_headers,
                json={"project_id": project["id"], "name": "Test Camp", "is_test_campaign": True})
    after_test = client.get("/api/dashboard/overview", headers=admin_headers).json()["totals"]["campaigns"]
    assert after_test == before  # test campaign not counted

    client.post("/api/campaigns", headers=admin_headers,
                json={"project_id": project["id"], "name": "Real Camp", "is_test_campaign": False})
    after_real = client.get("/api/dashboard/overview", headers=admin_headers).json()["totals"]["campaigns"]
    assert after_real == before + 1  # real campaign counted
