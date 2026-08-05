"""Suggest-and-confirm fix application (PRD Sec. 9). Every fix already
proposed lives as a `suggested_fix` on an issue from checks.py; nothing here
is ever applied without the caller (the /fixes endpoint) passing an explicit
fix_id or accept_all=True.
"""
from . import ai_client
from .mapping import TARGET_FIELDS


def enrich_with_ai(issues: list[dict], mapped_rows: list[dict]) -> list[dict]:
    """Asks OpenAI (if configured) for a second opinion on invalid-format
    emails the static typo dictionary/edit-distance check in checks.py
    couldn't explain. No-op (returns issues unchanged) if AI isn't
    configured or the call fails -- see ai_client's fallback contract."""
    already_fixed_rows = {i["row_number"] for i in issues if i["issue_type"] == "possible_typo"}
    unexplained = [
        (row["row_number"], row["mapped"]["email"].strip())
        for row in mapped_rows
        if row["row_number"] not in already_fixed_rows
        for i in issues
        if i["row_number"] == row["row_number"] and i["issue_type"] == "invalid_email"
    ]
    if not unexplained:
        return issues

    candidates = list({email for _, email in unexplained})
    ai_fixes = ai_client.suggest_email_fixes(candidates)
    if not ai_fixes:
        return issues

    by_row = dict(unexplained)
    for row_number, email in by_row.items():
        fix = ai_fixes.get(email)
        if fix:
            issues.append({
                "row_number": row_number, "field": "email", "severity": "warning",
                "issue_type": "possible_typo", "description": f"AI suggests '{email}' may be mistyped.",
                "suggested_fix": fix, "fix_id": f"{row_number}:email:possible_typo",
            })
    return issues


def apply_fixes(rows: list[dict], column_mapping: dict[str, str | None], issues: list[dict],
                 fix_ids: set[str] | None, accept_all: bool) -> tuple[list[dict], list[str]]:
    """Mutates `rows` (the working copy) in place, applying every issue whose
    suggested_fix was accepted. Returns (rows, applied_fix_ids)."""
    reverse_mapping: dict[str, str] = {}
    for header, target in column_mapping.items():
        if target and target not in reverse_mapping:
            reverse_mapping[target] = header

    rows_by_number = {r["row_number"]: r for r in rows}
    applied = []
    for issue in issues:
        if not issue.get("suggested_fix"):
            continue
        if not accept_all and issue["fix_id"] not in (fix_ids or set()):
            continue
        row = rows_by_number.get(issue["row_number"])
        if not row:
            continue
        field = issue["field"]
        header = reverse_mapping.get(field) if field in TARGET_FIELDS else field
        if header and header in row["values"]:
            row["values"][header] = issue["suggested_fix"]
            applied.append(issue["fix_id"])
    return rows, applied
