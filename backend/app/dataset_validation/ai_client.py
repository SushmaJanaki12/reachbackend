"""Optional OpenAI-backed enhancement for column-mapping and fix suggestions.

Blank OPENAI_API_KEY (the default) means every function here returns None
immediately -- same "blank creds = simulated" pattern as email/SMS in
config.py. A configured key still degrades to None on any error, timeout,
or malformed response: callers always have a deterministic heuristic to
fall back to (mapping.suggest_mapping / fixes.py's static dictionary), so a
flaky OpenAI call must never fail or block an upload.
"""
import json
import logging

from ..config import settings

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
        _client = OpenAI(api_key=settings.openai_api_key, timeout=8.0, max_retries=1)
    except Exception:
        logger.exception("failed to initialize OpenAI client")
        _client = None
    return _client


def _chat_json(system: str, user: str) -> dict | None:
    client = _get_client()
    if client is None:
        return None
    try:
        resp = client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            timeout=8,
        )
        return json.loads(resp.choices[0].message.content)
    except Exception:
        logger.warning("OpenAI call failed, falling back to heuristic", exc_info=True)
        return None


def suggest_column_mapping(headers: list[str], sample_values: dict[str, list[str]],
                            target_fields: list[str]) -> dict[str, str | None] | None:
    data = _chat_json(
        "You map spreadsheet column headers to a fixed set of contact fields. "
        "Respond with JSON only: {\"mapping\": {\"<header>\": \"<target_field_or_null>\"}}.",
        f"Allowed target fields: {target_fields}\n"
        f"Headers: {headers}\n"
        f"Sample values per header: {json.dumps(sample_values)[:4000]}",
    )
    if not data:
        return None
    mapping = data.get("mapping")
    if not isinstance(mapping, dict):
        return None
    return {h: (t if t in target_fields else None) for h, t in mapping.items() if h in headers}


def suggest_email_fixes(candidate_emails: list[str]) -> dict[str, str] | None:
    if not candidate_emails:
        return None
    data = _chat_json(
        "You fix likely typos in email addresses (e.g. gmial.com -> gmail.com). "
        "Only suggest a fix you're confident about; use null otherwise. "
        "Respond with JSON only: {\"fixes\": {\"<email>\": \"<corrected_or_null>\"}}.",
        f"Emails: {json.dumps(candidate_emails)}",
    )
    if not data:
        return None
    fixes = data.get("fixes")
    if not isinstance(fixes, dict):
        return None
    return {e: f for e, f in fixes.items() if e in candidate_emails and f and f != e}
