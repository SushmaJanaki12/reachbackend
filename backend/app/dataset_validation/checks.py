"""Validation checks (PRD Sec. 7). Operates on already-parsed rows plus a
confirmed column mapping; produces a flat issue list the router/scoring/
report code all consume.

Issue shape: {row_number, field, severity, issue_type, description,
suggested_fix, fix_id}. severity is one of:
  - "error"    blocks import outright (missing/invalid email)
  - "duplicate" excluded from import by default (within-file dup email)
  - "warning"  importable, but flagged; a "ready" row may still carry these

A row's default import eligibility: no "error" and no "duplicate" issues.
"Ignore Warnings" additionally allows rows that only carry "warning" issues
through -- see the /import endpoint.
"""
import re

import phonenumbers

from .email_typo import detect_typo
from .mapping import apply_mapping

EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
                       r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")

ROLE_PREFIXES = {
    "info", "admin", "noreply", "no-reply", "support", "sales", "contact",
    "help", "webmaster", "postmaster", "marketing", "billing", "office", "hello",
}

DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com",
    "throwawaymail.com", "yopmail.com", "trashmail.com", "getnada.com",
    "dispostable.com", "fakeinbox.com", "sharklasers.com", "maildrop.cc",
    "temp-mail.org", "mintemail.com", "mailnesia.com",
}

SEQUENTIAL_LOCAL_RE = re.compile(r"^(test|demo|sample|example|user)\d*$", re.IGNORECASE)

PLACEHOLDER_VALUES = {"n/a", "na", "none", "unknown", "-", "customer", "test", "xxx", "tbd", "n.a"}

CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
FORMULA_PREFIX_CHARS = ("=", "+", "-", "@")

US_STATES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa",
    "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan",
    "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york", "north carolina",
    "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island",
    "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont",
    "virginia", "washington", "west virginia", "wisconsin", "wyoming",
    "ny", "ca", "tx", "fl", "wa", "il", "pa", "oh", "ga", "nc", "mi", "nj", "va", "az",
}
US_NAMES = {"us", "usa", "u.s.", "u.s.a.", "united states", "united states of america"}

_COUNTRY_TO_REGION = {
    "united states": "US", "usa": "US", "us": "US",
    "united kingdom": "GB", "uk": "GB", "great britain": "GB",
    "india": "IN", "canada": "CA", "australia": "AU", "germany": "DE",
    "france": "FR", "spain": "ES", "italy": "IT", "netherlands": "NL",
    "ireland": "IE", "new zealand": "NZ", "singapore": "SG",
    "united arab emirates": "AE", "uae": "AE", "south africa": "ZA",
    "brazil": "BR", "mexico": "MX", "japan": "JP", "china": "CN",
    "philippines": "PH", "pakistan": "PK", "bangladesh": "BD", "nigeria": "NG",
}

_REGION_TO_COUNTRY_NAME = {
    "US": "United States", "GB": "United Kingdom", "IN": "India", "CA": "Canada",
    "AU": "Australia", "DE": "Germany", "FR": "France", "ES": "Spain", "IT": "Italy",
    "NL": "Netherlands", "IE": "Ireland", "NZ": "New Zealand", "SG": "Singapore",
    "AE": "United Arab Emirates", "ZA": "South Africa", "BR": "Brazil", "MX": "Mexico",
    "JP": "Japan", "CN": "China", "PH": "Philippines", "PK": "Pakistan",
    "BD": "Bangladesh", "NG": "Nigeria",
}


def _issue(row_number, field, severity, issue_type, description, suggested_fix=None):
    return {
        "row_number": row_number,
        "field": field,
        "severity": severity,
        "issue_type": issue_type,
        "description": description,
        "suggested_fix": suggested_fix,
        "fix_id": f"{row_number}:{field}:{issue_type}",
    }


def _region_for_country(country: str) -> str | None:
    return _COUNTRY_TO_REGION.get(country.strip().lower()) if country else None


def check_phone(mobile: str, country: str) -> dict:
    """Returns {"valid": bool, "formatted": str|None}. Never treated as an
    error (Sec. 7.4) -- mobile isn't mandatory and format confidence drops
    without a reliable Country value."""
    if not mobile:
        return {"valid": True, "formatted": None}
    region = _region_for_country(country)
    try:
        parsed = phonenumbers.parse(mobile, region)
        if phonenumbers.is_valid_number(parsed):
            return {"valid": True, "formatted": phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)}
        return {"valid": False, "formatted": None}
    except phonenumbers.NumberParseException:
        digits = re.sub(r"\D", "", mobile)
        return {"valid": len(digits) >= 8, "formatted": None}


def evaluate_rows(rows: list[dict], column_mapping: dict[str, str | None]) -> tuple[list[dict], list[dict]]:
    """Returns (issues, mapped_rows). mapped_rows mirrors `rows` 1:1, each
    augmented with a "mapped" dict of target-field values."""
    mapped_rows = [{**row, "mapped": apply_mapping(row["values"], column_mapping)} for row in rows]
    issues: list[dict] = []

    # ---- within-file duplicate emails (Sec. 7.1) ----
    seen_emails: dict[str, int] = {}
    for row in mapped_rows:
        email = row["mapped"]["email"].strip().lower()
        if not email:
            continue
        if email in seen_emails:
            issues.append(_issue(
                row["row_number"], "email", "duplicate", "duplicate_email",
                f"Duplicate of the email on row {seen_emails[email]}; only the first occurrence imports by default.",
            ))
        else:
            seen_emails[email] = row["row_number"]

    # ---- file-level casing-consistency clusters for state/city (Sec. 7.8) ----
    canonical = {}
    for field in ("state", "city"):
        variants: dict[str, dict[str, int]] = {}
        for row in mapped_rows:
            val = row["mapped"][field].strip()
            if not val:
                continue
            norm = val.lower()
            variants.setdefault(norm, {})
            variants[norm][val] = variants[norm].get(val, 0) + 1
        canonical[field] = {
            norm: max(forms, key=forms.get) for norm, forms in variants.items() if len(forms) > 1
        }

    for row in mapped_rows:
        rn = row["row_number"]
        mapped = row["mapped"]

        # ---- Sec. 7.2 / 7.3: email presence + format ----
        email = mapped["email"].strip()
        if not email:
            issues.append(_issue(rn, "email", "error", "missing_email", "Email address is required."))
        elif not EMAIL_RE.match(email):
            issues.append(_issue(rn, "email", "error", "invalid_email", f"'{email}' is not a valid email address."))
        else:
            local = email.split("@", 1)[0].lower()
            domain = email.split("@", 1)[1].lower()
            if local in ROLE_PREFIXES:
                issues.append(_issue(
                    rn, "email", "warning", "role_based_email",
                    f"'{email}' looks like a role-based address, not a person.",
                ))
            if domain in DISPOSABLE_DOMAINS or SEQUENTIAL_LOCAL_RE.match(local):
                issues.append(_issue(
                    rn, "email", "warning", "suspicious_pattern",
                    f"'{email}' matches a suspicious pattern (disposable domain or test-looking address).",
                ))
        if email:
            typo_fix = detect_typo(email)
            if typo_fix:
                issues.append(_issue(
                    rn, "email", "warning", "possible_typo",
                    f"'{email}' may be a mistyped domain.",
                    suggested_fix=typo_fix,
                ))

        # ---- Sec. 7.4: phone format ----
        mobile = mapped["mobile"].strip()
        if mobile:
            result = check_phone(mobile, mapped["country"])
            if not result["valid"]:
                issues.append(_issue(
                    rn, "mobile", "warning", "invalid_phone",
                    f"'{mobile}' doesn't look like a valid phone number"
                    + (f" for {mapped['country']}." if mapped["country"] else " (no Country value to validate against)."),
                ))
            elif result["formatted"] and result["formatted"] != mobile:
                issues.append(_issue(
                    rn, "mobile", "warning", "inconsistent_phone_format",
                    "Phone number format doesn't match the standard international format.",
                    suggested_fix=result["formatted"],
                ))
            # Sec. 9.2: fill Country from a recognizable phone country code --
            # only when confidently parseable (leading '+'), never guessed.
            if not mapped["country"].strip() and mobile.startswith("+"):
                try:
                    parsed = phonenumbers.parse(mobile, None)
                    region = phonenumbers.region_code_for_number(parsed)
                    country_name = _REGION_TO_COUNTRY_NAME.get(region)
                    if country_name:
                        issues.append(_issue(
                            rn, "country", "warning", "fill_country_from_phone",
                            f"Country is blank; the phone number's country code suggests {country_name}.",
                            suggested_fix=country_name,
                        ))
                except phonenumbers.NumberParseException:
                    pass

        # ---- Sec. 7.8: state/country mismatch + casing ----
        state, country = mapped["state"].strip(), mapped["country"].strip()
        if state and country and state.lower() in US_STATES and country.lower() not in US_NAMES:
            issues.append(_issue(
                rn, "state", "warning", "state_country_mismatch",
                f"State '{state}' looks like a US state, but Country is '{country}'.",
            ))
        for field in ("state", "city"):
            val = mapped[field].strip()
            if val and val.lower() in canonical[field] and canonical[field][val.lower()] != val:
                issues.append(_issue(
                    rn, field, "warning", "inconsistent_casing",
                    f"'{val}' has inconsistent casing/formatting elsewhere in the file.",
                    suggested_fix=canonical[field][val.lower()],
                ))

        # ---- Sec. 7.6: control chars / formula injection ----
        for header, val in row["values"].items():
            if not val:
                continue
            if CONTROL_CHAR_RE.search(val):
                issues.append(_issue(
                    rn, header, "warning", "control_characters",
                    f"'{header}' contains non-printable characters.",
                    suggested_fix=CONTROL_CHAR_RE.sub("", val),
                ))
            elif val[0] in FORMULA_PREFIX_CHARS:
                issues.append(_issue(
                    rn, header, "warning", "formula_injection",
                    f"'{header}' starts with '{val[0]}', which spreadsheet apps may treat as a formula.",
                    suggested_fix="'" + val,
                ))

    return issues, mapped_rows


def is_personalization_ready(mapped: dict) -> bool:
    name = mapped.get("name", "").strip()
    return bool(name) and name.strip().lower() not in PLACEHOLDER_VALUES
