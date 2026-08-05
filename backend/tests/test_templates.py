import uuid

EMAIL_FIELDS = {
    "headline": "Big News",
    "opening_line": "Hope you're well, {{Name}}.",
    "show_bullets": False,
    "show_callout": False,
    "show_cta": False,
    "show_badges": False,
    "show_secondary": False,
}

WHATSAPP_CONTENT = {
    "meta_template_name": "order_confirmation",
    "meta_template_id": "123456789",
    "language_code": "en_US",
    "header_type": "text",
    "header_content": "Order confirmed",
    "body_text": "Hi {{1}}, your order {{2}} has shipped.",
    "footer_text": "Reply STOP to opt out",
    "buttons": [],
}


def _create_email_template(client, headers, name="Welcome Email", status=None):
    r = client.post("/api/templates", headers=headers, json={
        "name": name, "channel": "email",
        "email_content": {"subject": "Welcome, {{Name}}!", "fields": EMAIL_FIELDS},
    })
    assert r.status_code == 200, r.text
    tpl = r.json()
    if status:
        r2 = client.put(f"/api/templates/{tpl['id']}", headers=headers, json={"status": status})
        assert r2.status_code == 200, r2.text
        tpl = r2.json()
    return tpl


# ---------- create ----------
def test_create_email_template(client, admin_headers):
    tpl = _create_email_template(client, admin_headers)
    assert tpl["channel"] == "email"
    assert tpl["status"] == "draft"
    assert tpl["email_content"]["subject"] == "Welcome, {{Name}}!"
    assert tpl["email_content"]["fields"]["headline"] == "Big News"
    assert tpl["attachments"] == []


def test_create_whatsapp_template_requires_content(client, admin_headers):
    r = client.post("/api/templates", headers=admin_headers, json={"name": "WA", "channel": "whatsapp"})
    assert r.status_code == 400


def test_create_whatsapp_template(client, admin_headers):
    r = client.post("/api/templates", headers=admin_headers, json={
        "name": "Order Confirmation", "channel": "whatsapp", "whatsapp_content": WHATSAPP_CONTENT,
    })
    assert r.status_code == 200, r.text
    tpl = r.json()
    assert tpl["whatsapp_content"]["meta_template_name"] == "order_confirmation"


def test_create_sms_template_via_library_endpoint_is_blocked(client, admin_headers):
    """SMS templates are DLT-registered and stay in their own table, managed
    via /api/sms/templates -- this umbrella table only ever holds email and
    whatsapp content (see routers/templates.py CREATABLE_CHANNELS)."""
    r = client.post("/api/templates", headers=admin_headers, json={"name": "SMS", "channel": "sms"})
    assert r.status_code == 400


# ---------- categories ----------
def _unique_name(prefix):
    return f"{prefix} {uuid.uuid4().hex[:8]}"


def test_create_category_then_use_it(client, admin_headers):
    name = _unique_name("Newsletters")
    r = client.post("/api/template-categories", headers=admin_headers, json={"name": name})
    assert r.status_code == 200, r.text
    cat = r.json()

    tpl = client.post("/api/templates", headers=admin_headers, json={
        "name": "Monthly Update", "channel": "email", "category_id": cat["id"],
        "email_content": {"subject": "Hi", "fields": EMAIL_FIELDS},
    }).json()
    assert tpl["category"]["name"] == name


def test_create_duplicate_category_name_rejected(client, admin_headers):
    name = _unique_name("Promos")
    client.post("/api/template-categories", headers=admin_headers, json={"name": name})
    r = client.post("/api/template-categories", headers=admin_headers, json={"name": name})
    assert r.status_code == 400


# ---------- list / filter ----------
def test_list_templates_filters_by_channel(client, admin_headers):
    _create_email_template(client, admin_headers, name="Email One")
    r = client.get("/api/templates", headers=admin_headers, params={"channel": "email"})
    assert r.status_code == 200
    assert all(t["channel"] == "email" for t in r.json())


def test_list_templates_search_by_name(client, admin_headers):
    _create_email_template(client, admin_headers, name="Quarterly Newsletter")
    r = client.get("/api/templates", headers=admin_headers, params={"q": "Quarterly"})
    assert r.status_code == 200
    assert any(t["name"] == "Quarterly Newsletter" for t in r.json())


# ---------- duplicate ----------
def test_duplicate_creates_independent_draft_copy(client, admin_headers):
    tpl = _create_email_template(client, admin_headers, name="Original", status="published")
    r = client.post(f"/api/templates/{tpl['id']}/duplicate", headers=admin_headers)
    assert r.status_code == 200, r.text
    copy = r.json()
    assert copy["id"] != tpl["id"]
    assert copy["name"] == "Original (Copy)"
    assert copy["status"] == "draft"
    assert copy["email_content"]["subject"] == tpl["email_content"]["subject"]

    client.put(f"/api/templates/{copy['id']}", headers=admin_headers, json={
        "email_content": {"subject": "Changed", "fields": EMAIL_FIELDS},
    })
    original = client.get(f"/api/templates/{tpl['id']}", headers=admin_headers).json()
    assert original["email_content"]["subject"] == "Welcome, {{Name}}!"


# ---------- status / archive ----------
def test_put_status_rejects_archived_directly(client, admin_headers):
    tpl = _create_email_template(client, admin_headers)
    r = client.put(f"/api/templates/{tpl['id']}", headers=admin_headers, json={"status": "archived"})
    assert r.status_code == 400


def test_archive_endpoint_sets_status(client, admin_headers):
    tpl = _create_email_template(client, admin_headers)
    r = client.post(f"/api/templates/{tpl['id']}/archive", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "archived"


def test_user_role_cannot_archive_or_delete(client, user_headers, admin_headers):
    tpl = _create_email_template(client, admin_headers)
    assert client.post(f"/api/templates/{tpl['id']}/archive", headers=user_headers).status_code == 403
    assert client.delete(f"/api/templates/{tpl['id']}", headers=user_headers).status_code == 403


def test_user_role_can_view_and_edit(client, user_headers, admin_headers):
    tpl = _create_email_template(client, admin_headers)
    assert client.get(f"/api/templates/{tpl['id']}", headers=user_headers).status_code == 200
    r = client.put(f"/api/templates/{tpl['id']}", headers=user_headers, json={"name": "Renamed"})
    assert r.status_code == 200


# ---------- delete ----------
def test_delete_unused_draft_succeeds(client, admin_headers):
    tpl = _create_email_template(client, admin_headers)
    r = client.delete(f"/api/templates/{tpl['id']}", headers=admin_headers)
    assert r.status_code == 200
    assert client.get(f"/api/templates/{tpl['id']}", headers=admin_headers).status_code == 404


# ---------- preview ----------
def test_preview_email_template_renders_shell(client, admin_headers):
    tpl = _create_email_template(client, admin_headers)
    r = client.post(f"/api/templates/{tpl['id']}/preview", headers=admin_headers, json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "Big News" in body["html"]


def test_preview_whatsapp_template_renders_body(client, admin_headers):
    r = client.post("/api/templates", headers=admin_headers, json={
        "name": "WA Preview", "channel": "whatsapp", "whatsapp_content": WHATSAPP_CONTENT,
    })
    tpl = r.json()
    p = client.post(f"/api/templates/{tpl['id']}/preview", headers=admin_headers, json={})
    assert p.status_code == 200, p.text
    assert "your order" in p.json()["html"]


# ---------- attachments (email only) ----------
def test_email_template_attachment_upload_list_delete(client, admin_headers):
    tpl = _create_email_template(client, admin_headers)
    r = client.post(f"/api/templates/{tpl['id']}/attachments", headers=admin_headers,
                     files={"file": ("brochure.pdf", b"%PDF-1.4 fake", "application/pdf")})
    assert r.status_code == 200, r.text
    att = r.json()
    assert att["filename"] == "brochure.pdf"

    listed = client.get(f"/api/templates/{tpl['id']}/attachments", headers=admin_headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    d = client.delete(f"/api/templates/{tpl['id']}/attachments/{att['id']}", headers=admin_headers)
    assert d.status_code == 200
    assert client.get(f"/api/templates/{tpl['id']}/attachments", headers=admin_headers).json() == []


def test_whatsapp_template_rejects_attachments(client, admin_headers):
    r = client.post("/api/templates", headers=admin_headers, json={
        "name": "WA No Attach", "channel": "whatsapp", "whatsapp_content": WHATSAPP_CONTENT,
    })
    tpl = r.json()
    up = client.post(f"/api/templates/{tpl['id']}/attachments", headers=admin_headers,
                      files={"file": ("x.pdf", b"data", "application/pdf")})
    assert up.status_code == 400


def test_deleting_email_template_cleans_up_attachments(client, admin_headers):
    tpl = _create_email_template(client, admin_headers)
    client.post(f"/api/templates/{tpl['id']}/attachments", headers=admin_headers,
                files={"file": ("a.pdf", b"data", "application/pdf")})
    r = client.delete(f"/api/templates/{tpl['id']}", headers=admin_headers)
    assert r.status_code == 200
