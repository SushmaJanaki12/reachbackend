"""AI Data Quality Score (PRD Sec. 8.1) -- a weighted composite of five
sub-scores, each `1 - (issue_count / total_rows)`. Weights are the PRD's
proposed starting point, not yet validated with stakeholders (flagged as an
open question in the PRD itself); they live here as the single place to
tune them.
"""
from .checks import is_personalization_ready

WEIGHTS = {
    "valid_email": 0.35,
    "duplicate_rate": 0.20,
    "missing_mandatory": 0.20,
    "invalid_phone": 0.10,
    "personalization_readiness": 0.15,
}

LABEL_BANDS = [(90, "Excellent"), (75, "Good"), (50, "Needs Attention"), (0, "Poor")]


def _label(overall: int) -> str:
    for threshold, label in LABEL_BANDS:
        if overall >= threshold:
            return label
    return "Poor"


def compute_score(issues: list[dict], mapped_rows: list[dict]) -> dict:
    total = len(mapped_rows) or 1

    def count(issue_type=None, severity=None):
        return sum(
            1 for i in issues
            if (issue_type is None or i["issue_type"] == issue_type)
            and (severity is None or i["severity"] == severity)
        )

    ready = sum(1 for r in mapped_rows if is_personalization_ready(r["mapped"]))

    sub = {
        "valid_email": 1 - count("invalid_email") / total,
        "duplicate_rate": 1 - count(severity="duplicate") / total,
        "missing_mandatory": 1 - count("missing_email") / total,
        "invalid_phone": 1 - count("invalid_phone") / total,
        "personalization_readiness": ready / total,
    }
    overall = round(100 * sum(sub[k] * WEIGHTS[k] for k in WEIGHTS))
    overall = max(0, min(100, overall))

    return {
        "overall": overall,
        "label": _label(overall),
        "breakdown": {k: round(v * 100) for k, v in sub.items()},
    }
