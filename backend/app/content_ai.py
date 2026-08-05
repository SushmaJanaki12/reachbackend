"""Generative AI content drafting for campaign messages -- replaces the old
manual 'branded template' authoring mode in the Content step with a
prompt -> draft flow. Requires OPENAI_API_KEY (settings.ai_suggestions_configured);
callers must check that and surface a clear error before calling generate().
"""
import json
import logging

from .config import settings

logger = logging.getLogger(__name__)

_client = None
_client_checked = False


def _get_client():
    global _client, _client_checked
    if _client_checked:
        return _client
    _client_checked = True
    if not settings.ai_suggestions_configured:
        return None
    try:
        from openai import OpenAI
        _client = OpenAI(api_key=settings.openai_api_key, timeout=20.0, max_retries=1)
    except Exception:
        logger.exception("failed to initialize OpenAI client")
        _client = None
    return _client


CHANNEL_GUIDANCE = {
    "email": "Write a marketing email: a short, compelling subject line and a body of 2-4 short paragraphs.",
    "whatsapp": "Write a concise WhatsApp message: a few short lines, no subject line, friendly tone.",
    "sms": "Write a very short SMS message: under 300 characters, no subject line, plain text only.",
}


def generate(prompt: str, channel: str, columns: list[str], project) -> dict | None:
    """Returns {"subject": str, "body": str} (subject always "" for
    non-email channels), or None if AI isn't configured or the call fails --
    callers turn None into a clear user-facing error, never a silent no-op."""
    client = _get_client()
    if client is None:
        return None

    tag_list = ", ".join("{{" + c + "}}" for c in columns) if columns else "{{Name}}"
    placeholder_hint = (
        f"You may personalize using ONLY these exact merge tags: {tag_list}. "
        "Copy each tag verbatim (exact spelling, capitalization and spacing) -- never invent a new tag name or "
        "rephrase one (e.g. do not write {{phone number}} if the given tag is {{Mobile number}}). "
        "Every merge tag resolves to THAT RECIPIENT's own data, never the sender's -- so never use one to state "
        "the company's own contact details (e.g. never write \"contact us at {{Email}}\" or \"call {{Mobile "
        "number}}\", since that would tell the recipient to contact themselves). No company phone/email/website "
        "has been supplied, so do not invent one -- if a call-to-action needs contact info, phrase it generically "
        "(e.g. \"reply to this message\") instead of fabricating a phone number, email address or link."
    )
    system = (
        "You draft marketing campaign content for a company. "
        f"{CHANNEL_GUIDANCE.get(channel, CHANNEL_GUIDANCE['email'])} {placeholder_hint} "
        'Respond with JSON only: {"subject": "<empty string if not applicable>", "body": "<message text>"}.'
    )
    user_msg = f"Company / sender: {project.name if project else ''}\nRequest: {prompt}"

    try:
        resp = client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
            response_format={"type": "json_object"},
            timeout=20,
        )
        data = json.loads(resp.choices[0].message.content)
        body = str(data.get("body") or "").strip()
        if not body:
            return None
        subject = str(data.get("subject") or "").strip() if channel == "email" else ""
        return {"subject": subject, "body": body}
    except Exception:
        logger.warning("OpenAI content generation failed", exc_info=True)
        return None
