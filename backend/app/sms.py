"""SMS sending via the Metamorph Systems bulk-SMS HTTP gateway.

POST to the endpoint with credentials + message as query-string params.
HTTP 200 is treated as accepted (the gateway returns its real status in the
plain-text body; set SMS_SUCCESS_TOKEN to require a substring for stricter checks).

India DLT note: the sender ID (SMS_FROM), the template (SMS_TEMPLATE_ID) and the
message text are all pre-registered with the operator. Message wording must match
the registered template or the operator will reject delivery even on HTTP 200.
"""
import re
import urllib.request
import urllib.parse
import urllib.error

from .config import settings


class SmsError(Exception):
    pass


# Any {{var}} or {#var#} style placeholder is treated as a DLT variable.
_PLACEHOLDER = re.compile(r"\{\{[^}]*\}\}|\{#[^#}]*#?\}")


def _normalize_for_dlt(text: str) -> str:
    """Placeholders -> sentinel, whitespace collapsed, lowercased — for DLT comparison."""
    s = _PLACEHOLDER.sub("\x00", text or "")
    return re.sub(r"\s+", " ", s).strip().lower()


def matches_template(template_body: str, message: str) -> bool:
    """True if the fixed (non-variable) text of message matches the registered template."""
    return _normalize_for_dlt(template_body) == _normalize_for_dlt(message)


def _normalize(mobile: str) -> str:
    """Return the number with the 91 country code, digits only (no +)."""
    digits = re.sub(r"\D", "", mobile or "")
    if not digits:
        return ""
    if digits.startswith("91") and len(digits) == 12:
        return digits
    if len(digits) == 10:
        return "91" + digits
    return digits


def send_sms(mobile: str, text: str, template_id: str | None = None) -> str:
    if not settings.sms_configured:
        raise SmsError("SMS gateway is not configured")
    number = _normalize(mobile)
    if len(number) < 10:
        raise SmsError("Invalid mobile number")
    params = {
        "username": settings.sms_username,
        "password": settings.sms_password,
        "from": settings.sms_from,
        "to": number,
        "message": text or "",
        "sms_type": "2",  # transactional
        "template_id": str(template_id or settings.sms_template_id),
    }
    # Credentials and message text go in the POST body, not the URL, so they
    # never end up in access/proxy/CDN logs that record the request line.
    data = urllib.parse.urlencode(params).encode()
    try:
        req = urllib.request.Request(
            settings.sms_api_url, data=data, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
            body = resp.read().decode(errors="replace").strip()
    except urllib.error.HTTPError as e:
        raise SmsError(f"SMS gateway HTTP {e.code}: {e.read().decode(errors='replace')[:200]}")
    except Exception as e:
        raise SmsError(f"SMS gateway request failed: {e}")

    if status != 200:
        raise SmsError(f"Gateway returned HTTP {status}: {body[:200]}")
    if settings.sms_success_token and settings.sms_success_token.lower() not in body.lower():
        raise SmsError(f"Gateway rejected: {body[:200]}")
    return (body[:120] or "sms-accepted")


def verify_configured() -> dict:
    if not settings.sms_configured:
        raise SmsError("SMS gateway is not configured")
    return {"ok": True, "sender": settings.sms_from}
