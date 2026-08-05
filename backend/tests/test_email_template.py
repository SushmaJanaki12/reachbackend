from app.email_template import render_email_template

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
