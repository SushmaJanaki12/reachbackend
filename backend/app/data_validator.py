"""AI Smart Data Validation for campaign contact uploads.

Parses CSV/XLS/XLSX, maps columns, scores quality, and returns a structured
validation report. Does not write to the database.
"""
from __future__ import annotations

import csv
import io
import re
import socket
from collections import Counter
from functools import lru_cache
from typing import Any

from openpyxl import load_workbook

from .campaign_utils import valid_email, valid_mobile

# ---- column aliases (lowercase) ----
NAME_ALIASES = ("name", "full name", "contact name", "recipient name", "fullname")
EMAIL_ALIASES = ("email", "email address", "email id", "e-mail", "mail", "email_id")
MOBILE_ALIASES = (
    "mobile", "mobile number", "phone", "mobile no", "phone number",
    "contact number", "cell", "cellphone", "mobile_number", "phonenumber",
)
SNO_ALIASES = ("s.no", "s no", "sno", "sr no", "sr.no", "serial", "serial no", "#", "no")

# Suspicious / spam-trap style patterns (heuristic)
_DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "tempmail.com", "throwaway.email",
    "yopmail.com", "sharklasers.com", "trashmail.com", "10minutemail.com",
    "temp-mail.org", "fakeinbox.com", "getnada.com", "tempail.com",
    "discard.email", "maildrop.cc", "mailnesia.com", "moakt.com",
    "emailondeck.com", "mintemail.com", "mytrashmail.com", "trashmail.me",
}
# Reserved / non-routable TLDs and labels
_BAD_TLDS = {"local", "localhost", "test", "invalid", "example", "internal", "lan", "home"}
_ROLE_LOCALS = {
    "noreply", "no-reply", "donotreply", "do-not-reply", "support", "admin",
    "administrator", "postmaster", "webmaster", "hostmaster", "abuse",
    "info", "sales", "contact", "hello", "mailer-daemon",
}
_SUSPICIOUS_LOCAL = re.compile(r"^(test|spam|asdf|abc|xxx|qwerty|fake|dummy)\b", re.I)
_INVALID_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
# Stricter address shape beyond the basic campaign_utils check
_STRICT_EMAIL = re.compile(
    r"^(?![.])"  # no leading dot
    r"[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
)


@lru_cache(maxsize=512)
def _dns_mail_capability(domain: str) -> tuple[str, str]:
    """Check whether *domain* can receive mail.

    Returns (status, detail) where status is one of:
      ok_mx      – MX records found
      ok_a       – no MX, but A/AAAA exists (some hosts still accept mail)
      nxdomain   – domain does not exist
      no_record  – no MX and no A/AAAA
      error      – lookup failed (timeout/network); treated as warning, not hard fail
    """
    domain = (domain or "").strip().lower().strip(".")
    if not domain:
        return "no_record", "empty domain"

    # Prefer dnspython when installed
    try:
        import dns.resolver  # type: ignore
        resolver = dns.resolver.Resolver(configure=True)
        resolver.timeout = 2.0
        resolver.lifetime = 3.0
        try:
            answers = resolver.resolve(domain, "MX")
            if answers:
                return "ok_mx", f"{len(list(answers))} MX"
        except dns.resolver.NXDOMAIN:
            return "nxdomain", "NXDOMAIN"
        except dns.resolver.NoAnswer:
            pass  # try A below
        except dns.resolver.NoNameservers:
            return "error", "no nameservers"
        except dns.exception.Timeout:
            return "error", "DNS timeout"
        except Exception as e:
            return "error", type(e).__name__

        try:
            resolver.resolve(domain, "A")
            return "ok_a", "A only (no MX)"
        except dns.resolver.NXDOMAIN:
            return "nxdomain", "NXDOMAIN"
        except Exception:
            try:
                resolver.resolve(domain, "AAAA")
                return "ok_a", "AAAA only (no MX)"
            except dns.resolver.NXDOMAIN:
                return "nxdomain", "NXDOMAIN"
            except Exception:
                return "no_record", "no MX/A/AAAA"
    except ImportError:
        pass

    # Fallback without dnspython: A/AAAA via getaddrinfo (cannot read MX)
    try:
        socket.setdefaulttimeout(2.0)
        socket.getaddrinfo(domain, None)
        return "ok_a", "A/AAAA via socket (MX not checked — install dnspython)"
    except socket.gaierror:
        return "nxdomain", "getaddrinfo failed"
    except Exception as e:
        return "error", type(e).__name__


def _norm_header(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").strip().lower())


def _find_col(headers: list[str], aliases: tuple[str, ...]) -> str | None:
    norm_map = {_norm_header(h): h for h in headers if h}
    for a in aliases:
        if a in norm_map:
            return norm_map[a]
    # fuzzy: header contains alias
    for nh, orig in norm_map.items():
        for a in aliases:
            if a in nh or nh in a:
                return orig
    return None


def parse_upload(raw: bytes, filename: str, content_type: str = "") -> tuple[list[str], list[dict[str, str]]]:
    """Return (headers, rows) as string dicts. Raises ValueError on bad input."""
    filename = (filename or "").lower()
    rows: list[dict[str, str]] = []
    headers: list[str] = []

    if filename.endswith(".csv") or content_type in ("text/csv", "application/vnd.ms-excel"):
        text = raw.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValueError("No header row found in CSV")
        headers = [str(h).strip() if h else f"col_{i}" for i, h in enumerate(reader.fieldnames)]
        for r in reader:
            row = {}
            for i, h in enumerate(reader.fieldnames):
                key = headers[i]
                val = r.get(h, "")
                row[key] = "" if val is None else str(val).strip()
            if any(v for v in row.values()):
                rows.append(row)
    elif filename.endswith((".xlsx", ".xls")):
        # openpyxl handles xlsx; .xls may fail — surface clear error
        try:
            wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        except Exception as e:
            raise ValueError(f"Could not read spreadsheet: {e}") from e
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        first = next(it, None)
        if not first:
            raise ValueError("Spreadsheet is empty")
        headers = [str(h).strip() if h is not None else f"col_{i}" for i, h in enumerate(first)]
        for values in it:
            if values is None:
                continue
            row = {}
            for i, h in enumerate(headers):
                if not h:
                    continue
                val = values[i] if i < len(values) else None
                row[h] = "" if val is None else str(val).strip()
            if any(v for v in row.values()):
                rows.append(row)
    else:
        raise ValueError("Unsupported file type. Upload .csv, .xls, or .xlsx")

    if not rows:
        raise ValueError("No data rows found in the file")
    return headers, rows


def map_columns(headers: list[str]) -> dict[str, str | None]:
    return {
        "name": _find_col(headers, NAME_ALIASES),
        "email": _find_col(headers, EMAIL_ALIASES),
        "mobile": _find_col(headers, MOBILE_ALIASES),
        "sno": _find_col(headers, SNO_ALIASES),
    }



def _email_issues(email: str) -> list[dict]:
    issues = []
    if not email:
        issues.append({"type": "missing_field", "field": "email", "severity": "error",
                       "description": "Email is missing", "suggested_fix": "Provide a valid email address"})
        return issues

    if _INVALID_CHARS.search(email):
        issues.append({"type": "invalid_characters", "field": "email", "severity": "error",
                       "description": "Email contains invalid control characters",
                       "suggested_fix": "Remove non-printable characters"})

    email_l = email.strip().lower()
    # Basic + strict shape
    if not valid_email(email_l) or not _STRICT_EMAIL.match(email_l):
        issues.append({"type": "invalid_email", "field": "email", "severity": "error",
                       "description": f"Invalid email format: {email}",
                       "suggested_fix": "Correct to a standard address like name@domain.com"})
        return issues

    if ".." in email_l:
        issues.append({"type": "invalid_email", "field": "email", "severity": "error",
                       "description": "Email contains consecutive dots",
                       "suggested_fix": "Remove repeated dots in the address"})
        return issues

    local, _, domain = email_l.partition("@")
    if not local or not domain or "." not in domain:
        issues.append({"type": "invalid_email", "field": "email", "severity": "error",
                       "description": f"Email domain looks incomplete: {domain or '(none)'}",
                       "suggested_fix": "Use a full domain including TLD, e.g. example.com"})
        return issues

    if len(local) > 64 or len(email_l) > 254:
        issues.append({"type": "invalid_email", "field": "email", "severity": "error",
                       "description": "Email exceeds maximum allowed length",
                       "suggested_fix": "Use a shorter address"})
        return issues

    labels = domain.split(".")
    tld = labels[-1] if labels else ""
    if len(tld) < 2 or not tld.isalpha():
        issues.append({"type": "invalid_email", "field": "email", "severity": "error",
                       "description": f"Invalid or missing TLD: .{tld}",
                       "suggested_fix": "Use a real top-level domain (com, in, org, …)"})
        return issues

    if tld in _BAD_TLDS or domain in _BAD_TLDS:
        issues.append({"type": "invalid_email", "field": "email", "severity": "error",
                       "description": f"Non-routable domain/TLD: {domain}",
                       "suggested_fix": "Replace with a public, deliverable domain"})
        return issues

    if domain in _DISPOSABLE_DOMAINS or any(domain.endswith("." + d) for d in _DISPOSABLE_DOMAINS):
        issues.append({"type": "suspicious_contact", "field": "email", "severity": "error",
                       "description": f"Disposable/temporary email domain: {domain}",
                       "suggested_fix": "Replace with a permanent business or personal email"})
        # disposable = hard fail for deliverability posture
        return issues

    if local in _ROLE_LOCALS or _SUSPICIOUS_LOCAL.search(local):
        issues.append({"type": "suspicious_contact", "field": "email", "severity": "warning",
                       "description": f"Role/suspicious local-part: {local}",
                       "suggested_fix": "Prefer a personal inbox for campaign outreach"})

    # MX / DNS deliverability signal
    status, detail = _dns_mail_capability(domain)
    if status == "nxdomain":
        issues.append({"type": "undeliverable_domain", "field": "email", "severity": "error",
                       "description": f"Domain does not exist (DNS NXDOMAIN): {domain}",
                       "suggested_fix": "Fix the domain name — this address cannot receive mail"})
    elif status == "no_record":
        issues.append({"type": "undeliverable_domain", "field": "email", "severity": "error",
                       "description": f"No MX or A record for domain: {domain}",
                       "suggested_fix": "Verify the domain; mail servers are not advertised in DNS"})
    elif status == "ok_a":
        issues.append({"type": "weak_dns", "field": "email", "severity": "warning",
                       "description": f"Domain has no MX record ({detail}): {domain}",
                       "suggested_fix": "Confirm mail is accepted; prefer domains with MX records"})
    elif status == "error":
        issues.append({"type": "dns_check_failed", "field": "email", "severity": "warning",
                       "description": f"Could not verify DNS for {domain} ({detail})",
                       "suggested_fix": "Re-validate when network/DNS is available; install dnspython for MX checks"})
    # status == ok_mx → no issue

    return issues


def _mobile_issues(mobile: str) -> list[dict]:
    issues = []
    if not mobile:
        issues.append({"type": "missing_field", "field": "mobile", "severity": "error",
                       "description": "Mobile number is missing",
                       "suggested_fix": "Provide a phone number with at least 8 digits"})
        return issues
    digits = re.sub(r"\D", "", mobile)
    if not valid_mobile(mobile):
        issues.append({"type": "invalid_phone", "field": "mobile", "severity": "error",
                       "description": f"Invalid phone number: {mobile}",
                       "suggested_fix": "Use digits only, with country code if available (min 8 digits)"})
    elif len(digits) > 15:
        issues.append({"type": "invalid_phone", "field": "mobile", "severity": "warning",
                       "description": f"Phone unusually long ({len(digits)} digits)",
                       "suggested_fix": "Confirm number formatting"})
    return issues


def validate_rows(
    headers: list[str],
    rows: list[dict[str, str]],
    *,
    existing_emails: set[str] | None = None,
    existing_mobiles: set[str] | None = None,
) -> dict[str, Any]:
    """Run all PRD checks and return a full validation report dict."""
    existing_emails = existing_emails or set()
    existing_mobiles = existing_mobiles or set()
    mapping = map_columns(headers)

    name_col = mapping["name"]
    email_col = mapping["email"]
    mobile_col = mapping["mobile"]

    mapping_suggestions = []
    if not name_col:
        mapping_suggestions.append("No Name column detected — map a column to Name (required)")
    if not email_col:
        mapping_suggestions.append("No Email column detected — map Email / Email Address (required)")
    if not mobile_col:
        mapping_suggestions.append("No Mobile column detected — map Mobile Number / Phone (required)")
    for h in headers:
        nh = _norm_header(h)
        if nh and nh not in (
            _norm_header(name_col or ""), _norm_header(email_col or ""),
            _norm_header(mobile_col or ""), _norm_header(mapping["sno"] or ""),
        ):
            # optional custom fields — good for personalization
            pass
    if mapping_suggestions:
        mapping_suggestions.insert(0, "AI column mapping: align headers to Name, Email, Mobile Number")

    row_results: list[dict] = []
    seen_emails: dict[str, int] = {}
    seen_mobiles: dict[str, int] = {}
    issue_counter: Counter = Counter()

    for idx, row in enumerate(rows, start=2):  # row 1 = header
        name = (row.get(name_col) or "").strip() if name_col else ""
        email = (row.get(email_col) or "").strip().lower() if email_col else ""
        mobile = (row.get(mobile_col) or "").strip() if mobile_col else ""

        issues: list[dict] = []

        # empty row (shouldn't happen after parse, but guard)
        if not any(row.values()):
            issues.append({"type": "empty_row", "field": "*", "severity": "error",
                           "description": "Empty row", "suggested_fix": "Remove this row"})
        if not name and name_col:
            issues.append({"type": "missing_field", "field": "name", "severity": "error",
                           "description": "Name is missing", "suggested_fix": "Fill in the contact name"})
        elif not name_col:
            issues.append({"type": "missing_field", "field": "name", "severity": "error",
                           "description": "Name column not mapped", "suggested_fix": "Add a Name column"})

        issues.extend(_email_issues(email))
        issues.extend(_mobile_issues(mobile))

        # duplicates within file
        if email and valid_email(email):
            if email in seen_emails:
                issues.append({"type": "duplicate", "field": "email", "severity": "error",
                               "description": f"Duplicate email (first seen on row {seen_emails[email]})",
                               "suggested_fix": "Keep one row; remove or merge duplicates"})
            else:
                seen_emails[email] = idx
            if email in existing_emails:
                issues.append({"type": "existing_contact", "field": "email", "severity": "warning",
                               "description": "Email already exists in this campaign",
                               "suggested_fix": "Skip or update the existing recipient"})

        if mobile and valid_mobile(mobile):
            digits = re.sub(r"\D", "", mobile)
            if digits in seen_mobiles:
                issues.append({"type": "duplicate", "field": "mobile", "severity": "warning",
                               "description": f"Duplicate mobile (first seen on row {seen_mobiles[digits]})",
                               "suggested_fix": "Confirm if same person; otherwise remove duplicate"})
            else:
                seen_mobiles[digits] = idx

        # personalization readiness: name present + at least one extra column value
        extra_vals = [
            v for k, v in row.items()
            if k not in (name_col, email_col, mobile_col, mapping["sno"]) and (v or "").strip()
        ]
        personalization_ready = bool(name) and (bool(extra_vals) or bool(email))

        errors = [i for i in issues if i["severity"] == "error"]
        warnings = [i for i in issues if i["severity"] == "warning"]
        for i in issues:
            issue_counter[i["type"]] += 1

        status = "invalid" if errors else ("warning" if warnings else "valid")
        row_results.append({
            "row_number": idx,
            "name": name,
            "email": email,
            "mobile": mobile,
            "status": status,
            "issues": issues,
            "personalization_ready": personalization_ready,
            "data": row,
        })

    total = len(row_results)
    valid_rows = [r for r in row_results if r["status"] == "valid"]
    warning_rows = [r for r in row_results if r["status"] == "warning"]
    invalid_rows = [r for r in row_results if r["status"] == "invalid"]
    # ready = valid + warnings (importable if user ignores warnings)
    ready_count = len(valid_rows) + len(warning_rows)

    valid_email_count = sum(1 for r in row_results if r["email"] and valid_email(r["email"]))
    valid_mobile_count = sum(1 for r in row_results if r["mobile"] and valid_mobile(r["mobile"]))
    dup_count = issue_counter.get("duplicate", 0)
    missing_count = issue_counter.get("missing_field", 0)
    invalid_phone_count = issue_counter.get("invalid_phone", 0)
    personalization_count = sum(1 for r in row_results if r["personalization_ready"])

    def pct(n: int, d: int = total) -> float:
        return round(100.0 * n / d, 1) if d else 0.0

    # Quality score 0-100
    score = 100.0
    if total:
        score -= pct(len(invalid_rows)) * 0.55
        score -= min(20.0, pct(dup_count) * 0.3)
        score -= min(15.0, pct(missing_count) * 0.2)
        score -= min(10.0, pct(invalid_phone_count) * 0.15)
        score += min(10.0, pct(personalization_count) * 0.1)
        # mapping failures are harsh
        if not name_col or not email_col or not mobile_col:
            score = min(score, 40.0)
    score = int(max(0, min(100, round(score))))

    recommendations: list[str] = []
    if not name_col or not email_col or not mobile_col:
        recommendations.append("Fix column headers to include Name, Email, and Mobile Number (download the sample CSV)")
    if dup_count:
        recommendations.append(f"Remove {dup_count} duplicate contact(s) before import")
    if missing_count:
        recommendations.append("Fill missing mandatory fields (name, email, mobile)")
    if issue_counter.get("invalid_email"):
        recommendations.append("Correct invalid email formats to reduce bounces")
    if invalid_phone_count:
        recommendations.append("Standardize phone numbers (digits, optional country code)")
    if issue_counter.get("suspicious_contact"):
        recommendations.append("Review suspicious/disposable emails — they often bounce or harm sender reputation")
    if personalization_count < total * 0.5 and total:
        recommendations.append("Add columns like Company or Designation to improve personalization readiness")
    if not recommendations and score >= 85:
        recommendations.append("Data quality looks strong — safe to import valid records")

    return {
        "quality_score": score,
        "score_breakdown": {
            "valid_emails_pct": pct(valid_email_count),
            "valid_phones_pct": pct(valid_mobile_count),
            "duplicates": dup_count,
            "missing_fields": missing_count,
            "invalid_phones": invalid_phone_count,
            "personalization_readiness_pct": pct(personalization_count),
            "overall_quality": score,
        },
        "summary": {
            "total_rows": total,
            "valid_rows": len(valid_rows),
            "invalid_rows": len(invalid_rows),
            "warning_rows": len(warning_rows),
            "duplicates": dup_count,
            "errors": sum(1 for r in row_results for i in r["issues"] if i["severity"] == "error"),
            "warnings": sum(1 for r in row_results for i in r["issues"] if i["severity"] == "warning"),
            "ready_for_import": ready_count,
        },
        "column_mapping": {
            "name": name_col,
            "email": email_col,
            "mobile": mobile_col,
            "sno": mapping["sno"],
            "headers": headers,
            "suggestions": mapping_suggestions,
        },
        "recommendations": recommendations,
        "rows": row_results,
        # import helpers (client/server)
        "importable_rows": [
            {
                "name": r["name"],
                "email": r["email"],
                "mobile": r["mobile"],
                "data": r["data"],
            }
            for r in row_results
            if r["status"] in ("valid", "warning")
        ],
    }


def sample_csv_bytes() -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["s.no", "name", "email", "mobile number", "company", "designation"])
    w.writerow([1, "Ada Lovelace", "ada@example.com", "919876543210", "Analytical Engines", "Mathematician"])
    w.writerow([2, "Grace Hopper", "grace@example.com", "919876543211", "US Navy", "Rear Admiral"])
    w.writerow([3, "Alan Turing", "alan@example.com", "919876543212", "Bletchley Park", "Cryptanalyst"])
    return buf.getvalue().encode("utf-8-sig")


def error_report_csv(report: dict) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["row_number", "name", "email", "mobile", "status", "issue_type", "severity", "description", "suggested_fix"])
    for r in report.get("rows") or []:
        issues = r.get("issues") or []
        if not issues:
            continue
        for issue in issues:
            w.writerow([
                r.get("row_number"),
                r.get("name"),
                r.get("email"),
                r.get("mobile"),
                r.get("status"),
                issue.get("type"),
                issue.get("severity"),
                issue.get("description"),
                issue.get("suggested_fix"),
            ])
    return buf.getvalue().encode("utf-8-sig")
