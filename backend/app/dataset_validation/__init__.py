"""AI Smart Data Validation: orchestrates parsing -> mapping -> checks ->
scoring for the /campaigns/{id}/dataset/validate endpoint family. Submodules
stay independently testable; this module is just the glue the router calls.
"""
from ..config import settings
from . import ai_client, fixes, mapping, scoring
from .checks import evaluate_rows
from .mapping import suggest_mapping as _heuristic_mapping

__all__ = ["suggest_mapping", "evaluate", "build_summary", "TARGET_FIELDS", "MANDATORY_TARGETS"]

TARGET_FIELDS = mapping.TARGET_FIELDS
MANDATORY_TARGETS = mapping.MANDATORY_TARGETS


def suggest_mapping(headers: list[str], rows: list[dict]) -> dict[str, str | None]:
    """Best-guess header -> target field. AI-enhanced when configured, with
    the deterministic alias/fuzzy match as both the default and the
    per-header fallback wherever the AI call didn't return (or wasn't run)."""
    guess = _heuristic_mapping(headers)
    if settings.ai_suggestions_configured:
        sample = {h: [r["values"].get(h, "") for r in rows[:5]] for h in headers}
        ai_guess = ai_client.suggest_column_mapping(headers, sample, TARGET_FIELDS)
        if ai_guess:
            for header, target in ai_guess.items():
                if target:
                    guess[header] = target
    return guess


def evaluate(rows: list[dict], column_mapping: dict[str, str | None], empty_rows_skipped: int = 0) -> dict:
    """rows: parsed data rows (empty rows already excluded upstream, see
    parsing.py). Returns {issues, summary, quality_score}."""
    issues, mapped_rows = evaluate_rows(rows, column_mapping)
    if settings.ai_suggestions_configured:
        issues = fixes.enrich_with_ai(issues, mapped_rows)
    return {
        "issues": issues,
        "summary": build_summary(issues, mapped_rows, empty_rows_skipped),
        "quality_score": scoring.compute_score(issues, mapped_rows),
    }


def build_summary(issues: list[dict], mapped_rows: list[dict], empty_rows_skipped: int = 0) -> dict:
    total = len(mapped_rows)
    row_severities: dict[int, set] = {}
    for i in issues:
        row_severities.setdefault(i["row_number"], set()).add(i["severity"])

    error_rows = {rn for rn, sev in row_severities.items() if "error" in sev}
    duplicate_rows = {rn for rn, sev in row_severities.items() if "duplicate" in sev} - error_rows
    warning_only_rows = {
        rn for rn, sev in row_severities.items()
        if "warning" in sev and rn not in error_rows and rn not in duplicate_rows
    }
    clean_count = total - len(error_rows) - len(duplicate_rows) - len(warning_only_rows)

    return {
        "total_rows": total,
        "empty_rows_skipped": empty_rows_skipped,
        "valid_rows": clean_count,
        "invalid_rows": len(error_rows),
        "warning_rows": len(warning_only_rows),
        "duplicate_rows": len(duplicate_rows),
        "ready_for_import": clean_count,
        "ready_for_import_with_overrides": clean_count + len(warning_only_rows),
    }


def rows_ready_for_import(rows: list[dict], issues: list[dict], ignore_warnings: bool) -> list[dict]:
    """Filters working rows down to the ones eligible to become Recipients."""
    row_severities: dict[int, set] = {}
    for i in issues:
        row_severities.setdefault(i["row_number"], set()).add(i["severity"])

    def eligible(rn: int) -> bool:
        sev = row_severities.get(rn, set())
        if "error" in sev or "duplicate" in sev:
            return False
        if "warning" in sev and not ignore_warnings:
            return False
        return True

    return [r for r in rows if eligible(r["row_number"])]
