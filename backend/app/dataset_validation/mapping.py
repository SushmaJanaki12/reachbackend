"""Column mapping: source file headers -> target contact fields.

The `Recipient` model only has a single `name` field (no First/Last split),
so `first_name`/`last_name` are recognized as mapping targets but get
combined into `name` at apply-time rather than requiring a schema change.
Every other recognized column is stored verbatim in `Recipient.data` (as it
is today), so nothing is lost even if a header isn't recognized -- an
unmapped column just isn't treated as a target field.
"""
import difflib
import re

TARGET_FIELDS = [
    "name", "first_name", "last_name", "email", "mobile",
    "company", "job_title", "city", "state", "country",
]

MANDATORY_TARGETS = {"email"}  # PRD Sec. 5: Email is the only mandatory field

_ALIASES: dict[str, list[str]] = {
    "name": ["name", "full name", "recipient name", "contact name"],
    "first_name": ["first name", "firstname", "fname", "given name"],
    "last_name": ["last name", "lastname", "lname", "surname", "family name"],
    "email": ["email", "email address", "email id", "e-mail", "e mail"],
    "mobile": ["mobile", "mobile number", "phone", "mobile no", "phone number",
               "contact number", "cell", "cell phone"],
    "company": ["company", "company name", "organization", "organisation"],
    "job_title": ["job title", "jobtitle", "title", "designation", "position"],
    "city": ["city", "town"],
    "state": ["state", "province", "region"],
    "country": ["country"],
}

_ALIAS_TO_TARGET = {alias: target for target, aliases in _ALIASES.items() for alias in aliases}


def _normalize(header: str) -> str:
    return re.sub(r"[\s_\-]+", " ", header.strip().lower())


def suggest_mapping(headers: list[str]) -> dict[str, str | None]:
    """Best-guess header -> target field, exact-alias match first, then a
    fuzzy fallback for near-miss headers. Never applied silently -- callers
    must have the user confirm/correct it before it's used for import."""
    mapping: dict[str, str | None] = {}
    used_targets: set[str] = set()
    for header in headers:
        norm = _normalize(header)
        target = _ALIAS_TO_TARGET.get(norm)
        if target is None:
            close = difflib.get_close_matches(norm, _ALIAS_TO_TARGET.keys(), n=1, cutoff=0.78)
            target = _ALIAS_TO_TARGET.get(close[0]) if close else None
        if target in used_targets:
            target = None  # don't map two headers to the same single-value target
        mapping[header] = target
        if target:
            used_targets.add(target)
    return mapping


def apply_mapping(values: dict[str, str], column_mapping: dict[str, str | None]) -> dict[str, str]:
    """Derive normalized target-field values from a row's raw {header: value}
    plus the confirmed mapping. `values` (raw, header-keyed) is left
    untouched -- it's what ends up in Recipient.data, same as today."""
    mapped: dict[str, str] = {t: "" for t in TARGET_FIELDS}
    for header, target in column_mapping.items():
        if not target or target not in TARGET_FIELDS:
            continue
        val = (values.get(header) or "").strip()
        if not val:
            continue
        if target in ("first_name", "last_name"):
            mapped[target] = val
        else:
            mapped[target] = val

    if not mapped["name"]:
        combined = " ".join(p for p in (mapped["first_name"], mapped["last_name"]) if p)
        if combined:
            mapped["name"] = combined
    return mapped
