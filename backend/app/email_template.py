"""Renders the fixed branded email shell (app/templates/default_email.html)
from structured campaign/project fields. Never touches raw admin-typed HTML --
the only HTML on this path is the fixed template file itself.
"""
import html as _html
import re
from datetime import date
from pathlib import Path

from .campaign_utils import render_template

TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "default_email.html"

_BLOCK_NAMES = ("bullets", "callout", "cta", "badges", "secondary")

# Fields that end up in an href/src -- escaped as text is not enough (an
# unescaped `javascript:` scheme would still execute), so these get an
# additional scheme allowlist instead of being passed through untouched.
_URL_KEYS = {
    "CompanyLogoUrl", "CompanyWebsite", "ActionUrl", "SecondaryActionUrl",
    "Badge1Url", "Badge2Url", "Badge3Url", "UnsubscribeUrl",
}


def _block_pattern(name: str) -> re.Pattern:
    return re.compile(rf"<!--\s*BLOCK:{name}:start\s*-->.*?<!--\s*BLOCK:{name}:end\s*-->", re.DOTALL)


def _strip_markers(raw: str) -> str:
    return re.sub(r"<!--\s*BLOCK:\w+:(start|end)\s*-->", "", raw)


def _safe_url(value: str) -> str:
    value = (value or "").strip()
    if not re.match(r"^https?://", value, re.IGNORECASE):
        return ""
    return _html.escape(value, quote=True)


def load_shell(fields: dict) -> str:
    """The base HTML with disabled optional blocks removed and markers stripped."""
    raw = TEMPLATE_PATH.read_text(encoding="utf-8")
    bullets = (fields.get("bullets") or [])[:3]
    enabled = {
        "bullets": bool(fields.get("show_bullets")) and any((b.get("label") or b.get("text")) for b in bullets),
        "callout": bool(fields.get("show_callout")),
        "cta": bool(fields.get("show_cta")),
        "badges": bool(fields.get("show_badges")),
        "secondary": bool(fields.get("show_secondary")),
    }
    for name in _BLOCK_NAMES:
        if not enabled[name]:
            raw = _block_pattern(name).sub("", raw)
    return _strip_markers(raw)


def render_email_template(project, fields: dict, recipient, missing: list | None = None) -> str:
    """Render the branded shell for one recipient.

    `fields` is the campaign's structured content (dict form of the
    TemplateFields schema). `recipient` may be None (e.g. no recipients
    uploaded yet) -- Name/Email/UnsubscribeUrl are then simply blank.
    """
    shell = load_shell(fields)

    # Recipient-level placeholders (e.g. {{Name}}, {{Company}}) can appear
    # *inside* the campaign's free-text fields (headline, opening line, bullet
    # and callout text) -- resolve those first, against raw (unescaped)
    # recipient data, before the result is escaped into the HTML shell below.
    # A single substitution pass over the shell can't do this: the recipient
    # token lives inside a field *value*, not inside the shell's own markup.
    recipient_data = dict((recipient.data if recipient else {}) or {})
    recipient_data["Name"] = recipient.name if recipient else ""
    recipient_data["Email"] = recipient.email if recipient else ""
    # Also resolvable inside free-text fields (headline/opening line/bullets/
    # callout) -- additive, matches the templates module's supported merge
    # variable list (see docs/PRD "Personalization variables").
    recipient_data["SenderName"] = project.sender_name if project else ""
    recipient_data["CurrentDate"] = date.today().isoformat()

    def resolve(text: str) -> str:
        return render_template(text or "", recipient_data, missing)

    bullets = (fields.get("bullets") or [])[:3]
    campaign_values = {
        "CampaignHeadline": resolve(fields.get("headline", "")),
        "OpeningLine": resolve(fields.get("opening_line", "")),
        "CampaignName": resolve(fields.get("campaign_name", "")),
        "CalloutLabel": resolve(fields.get("callout_label", "")),
        "CalloutText": resolve(fields.get("callout_text", "")),
        "ActionUrl": fields.get("action_url", ""),
        "ActionLabel": resolve(fields.get("action_label", "")),
        "SecondaryActionUrl": fields.get("secondary_action_url", ""),
        "SecondaryActionLabel": resolve(fields.get("secondary_action_label", "")),
    }
    for i in (1, 2, 3):
        b = bullets[i - 1] if i <= len(bullets) else {}
        campaign_values[f"BulletLabel{i}"] = resolve(b.get("label", ""))
        campaign_values[f"BulletText{i}"] = resolve(b.get("text", ""))

    project_values = {
        "CompanyLogoUrl": project.logo_url,
        "CompanyName": project.name,
        "CompanyWebsite": project.company_website,
        "CompanyAddress": project.company_address,
        "SenderName": project.sender_name,
        "SenderDesignation": project.sender_designation,
        "SenderPhone": project.sender_phone,
        "Badge1Url": project.badge1_url,
        "Badge2Url": project.badge2_url,
        "Badge3Url": project.badge3_url,
    }

    values = {**project_values, **campaign_values}
    values["Name"] = recipient.name if recipient else ""
    values["Email"] = recipient.email if recipient else ""
    # No unsubscribe-token system exists yet -- default to blank rather than
    # flagging it as a missing/unresolved placeholder on every single send.
    values["UnsubscribeUrl"] = ""

    escaped = {
        k: (_safe_url(v) if k in _URL_KEYS else _html.escape(str(v if v is not None else ""), quote=True))
        for k, v in values.items()
    }

    return render_template(shell, escaped, missing)
