from app.email_template import render_email_template
from app.models import Recipient
from tests.conftest import make_campaign, drain_queue

CSV = "Name,Email Address,Mobile Number,Company\nAlice,alice@example.com,9876543210,Acme\n"


def _upload(client, headers, cid, csv=CSV):
    return client.post(f"/api/campaigns/{cid}/dataset", headers=headers,
                       files={"file": ("data.csv", csv, "text/csv")})


FULL_FIELDS = {
    "headline": "Big News",
    "opening_line": "Hope you're well, {{Name}}.",
    "show_bullets": True,
    "campaign_name": "Autumn Launch",
    "bullets": [
        {"label": "Speed", "text": "Twice as fast"},
        {"label": "Price", "text": "Half the cost"},
        {"label": "Support", "text": "24/7 chat"},
    ],
    "show_callout": True,
    "callout_label": "Tip",
    "callout_text": "Reply to this email with questions.",
    "show_cta": True,
    "action_url": "https://example.com/go",
    "action_label": "Get started",
    "show_badges": True,
    "show_secondary": True,
    "secondary_action_url": "https://example.com/learn",
    "secondary_action_label": "Learn more",
}

BLANK_FIELDS = {
    "headline": "Just the basics",
    "opening_line": "Hello there.",
    "show_bullets": False,
    "show_callout": False,
    "show_cta": False,
    "show_badges": False,
    "show_secondary": False,
}


class _Project:
    logo_url = "https://cdn.example.com/logo.png"
    name = "Acme Inc"
    company_website = "https://acme.example.com"
    company_address = "1 Market St"
    sender_name = "Jane Doe"
    sender_designation = "Growth Lead"
    sender_phone = "+1-555-0100"
    badge1_url = "https://cdn.example.com/b1.png"
    badge2_url = "https://cdn.example.com/b2.png"
    badge3_url = "https://cdn.example.com/b3.png"


class _Recipient:
    name = "Alice"
    email = "alice@example.com"
    data = {"Company": "Acme"}


# ---------- pure render function ----------
def test_render_with_all_blocks_enabled_includes_every_field():
    html = render_email_template(_Project(), FULL_FIELDS, _Recipient())
    assert "Big News" in html
    assert "Speed" in html and "Twice as fast" in html
    assert "Support" in html and "24/7 chat" in html
    assert "Reply to this email with questions." in html
    assert 'href="https://example.com/go"' in html
    assert "Get started" in html
    assert 'href="https://example.com/learn"' in html
    assert "https://cdn.example.com/b1.png" in html
    assert "Jane Doe" in html and "Growth Lead" in html
    assert "Alice" in html
    assert "BLOCK:" not in html  # marker comments never leak into the output


def test_render_with_all_blocks_disabled_strips_every_optional_section():
    html = render_email_template(_Project(), BLANK_FIELDS, _Recipient())
    assert "Just the basics" in html
    # None of the optional-block-only content should be present.
    for leftover in ("BulletLabel", "Speed", "Twice as fast", "Reply to this email",
                      "Get started", "Learn more", "b1.png", "b2.png", "b3.png"):
        assert leftover not in html
    assert "BLOCK:" not in html


def test_render_with_mixed_blocks_only_shows_enabled_ones():
    fields = {**BLANK_FIELDS, "show_cta": True, "action_url": "https://example.com/go", "action_label": "Go"}
    html = render_email_template(_Project(), fields, _Recipient())
    assert 'href="https://example.com/go"' in html
    assert "Go" in html
    for leftover in ("Speed", "Reply to this email", "Learn more"):
        assert leftover not in html


def test_render_escapes_user_supplied_text_and_recipient_data():
    fields = {**BLANK_FIELDS, "headline": "<script>alert(1)</script>", "opening_line": "Hi & welcome"}
    html = render_email_template(_Project(), fields, _Recipient())
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "Hi &amp; welcome" in html


def test_render_rejects_javascript_scheme_urls():
    fields = {**BLANK_FIELDS, "show_cta": True, "action_url": "javascript:alert(1)", "action_label": "Click"}
    html = render_email_template(_Project(), fields, _Recipient())
    assert "javascript:" not in html


def test_render_tracks_missing_recipient_placeholder():
    fields = {**BLANK_FIELDS, "opening_line": "Hi {{NoSuchColumn}}"}
    missing = []
    render_email_template(_Project(), fields, _Recipient(), missing)
    assert "NoSuchColumn" in missing


def test_render_without_recipient_leaves_name_email_blank():
    html = render_email_template(_Project(), BLANK_FIELDS, None)
    assert "Hi <strong></strong>" in html


# ---------- API integration ----------
def test_set_content_template_mode_saves_and_ignores_body(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    _upload(client, admin_headers, c["id"])
    r = client.put(f"/api/campaigns/{c['id']}/content/email", headers=admin_headers, json={
        "subject": "Hi {{Name}}",
        "body": "this should be ignored in template mode",
        "content_mode": "template",
        "template_fields": FULL_FIELDS,
    })
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["content_mode"] == "template"
    assert out["body"] == ""
    assert out["template_fields"]["headline"] == "Big News"
    assert len(out["template_fields"]["bullets"]) == 3


def test_set_content_defaults_to_plain_mode(client, admin_headers, project):
    """Existing plain-text campaigns are unaffected: omitting content_mode
    still saves plain text exactly as before."""
    c = make_campaign(client, admin_headers, project["id"])
    r = client.put(f"/api/campaigns/{c['id']}/content/email", headers=admin_headers,
                   json={"subject": "Hi {{Name}}", "body": "Hello {{Name}}"})
    assert r.status_code == 200
    out = r.json()
    assert out["content_mode"] == "plain"
    assert out["body"] == "Hello {{Name}}"
    assert out["template_fields"]["headline"] == ""


def test_template_mode_still_rejects_html_subject(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    r = client.put(f"/api/campaigns/{c['id']}/content/email", headers=admin_headers, json={
        "subject": "Hi <b>{{Name}}</b>",
        "content_mode": "template",
        "template_fields": FULL_FIELDS,
    })
    assert r.status_code == 400


def test_preview_template_endpoint_renders_html_with_recipient_data(client, admin_headers, project):
    c = make_campaign(client, admin_headers, project["id"])
    _upload(client, admin_headers, c["id"])
    r = client.post(f"/api/campaigns/{c['id']}/preview-template", headers=admin_headers, json={
        "fields": FULL_FIELDS,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert "Alice" in body["html"]
    assert "Big News" in body["html"]
    assert body["missing"] == []


def test_preview_template_rejects_recipient_from_another_campaign(client, admin_headers, project):
    c1 = make_campaign(client, admin_headers, project["id"], "T1")
    c2 = make_campaign(client, admin_headers, project["id"], "T2")
    _upload(client, admin_headers, c1["id"])
    _upload(client, admin_headers, c2["id"])
    other_id = client.get(f"/api/campaigns/{c2['id']}/recipients", headers=admin_headers).json()[0]["id"]

    r = client.post(f"/api/campaigns/{c1['id']}/preview-template", headers=admin_headers, json={
        "fields": BLANK_FIELDS, "recipient_id": other_id,
    })
    assert r.status_code == 404


def test_send_template_mode_email_uses_is_html(client, admin_headers, project, monkeypatch):
    """The worker send path must render the branded HTML and pass is_html=True
    -- this is the one content mode allowed to bypass the plain-text escaping
    used everywhere else."""
    import app.worker as worker_mod
    s = worker_mod.settings
    monkeypatch.setattr(s, "azure_tenant_id", "tenant")
    monkeypatch.setattr(s, "o365_client_id", "client")
    monkeypatch.setattr(s, "o365_client_secret", "secret")
    monkeypatch.setattr(s, "o365_from_email", "from@acme.com")

    calls = []

    def fake_send_campaign_email(project, to, subject, body, is_html=False, attachments=None):
        calls.append({"to": to, "subject": subject, "body": body, "is_html": is_html})
        return "provider-id"
    monkeypatch.setattr(worker_mod, "send_campaign_email", fake_send_campaign_email)

    c = make_campaign(client, admin_headers, project["id"])
    _upload(client, admin_headers, c["id"])
    client.put(f"/api/campaigns/{c['id']}/content/email", headers=admin_headers, json={
        "subject": "Hi {{Name}}",
        "content_mode": "template",
        "template_fields": FULL_FIELDS,
    })
    client.put(f"/api/campaigns/{c['id']}", headers=admin_headers, json={"email_enabled": True})

    send = client.post(f"/api/campaigns/{c['id']}/send", headers=admin_headers)
    assert send.status_code == 200
    drain_queue()

    assert len(calls) == 1
    assert calls[0]["is_html"] is True
    assert "Big News" in calls[0]["body"]
    assert "Alice" in calls[0]["body"]
    assert calls[0]["subject"] == "Hi Alice"

    summary = client.get(f"/api/campaigns/{c['id']}/summary", headers=admin_headers).json()
    assert summary["status"] == "completed"
    assert summary["failed"] == 0
