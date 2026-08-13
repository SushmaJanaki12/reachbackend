"""
One-off cleanup: for campaign_content rows (channel='email') flagged by
find_html_content.py, drop leftover HTML/signature markup from `body`.

Only auto-cleans rows where the plain-text message is unambiguously
separable from the HTML: the body starts with plain text, followed by a
block that begins with one of the telltale old-signature-feature tags
(<table, <span style=, <img src=, <td style=) and runs to the end of the
string. In that case the signature block is dropped and `body` becomes
just the plain-text prefix.

Anything else (HTML mixed into the message itself, HTML that doesn't match
the known signature-block shape, multiple/ambiguous HTML regions) is left
untouched and reported as needing manual review via the UI.

Usage:
    cd backend && python -m scripts.clean_html_content          # dry run
    cd backend && python -m scripts.clean_html_content --apply  # write changes
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models import CampaignContent, Campaign

HTML_TAG_RE = re.compile(r"<[a-zA-Z][^>]*>")
SIGNATURE_START_RE = re.compile(r'^<(table|span\s+style=|img\s+src=|td\s+style=)', re.IGNORECASE)


def snippet(text: str, length: int = 150) -> str:
    text = text.replace("\n", " ").replace("\r", " ")
    return text[:length] + ("..." if len(text) > length else "")


def try_clean(body: str) -> str | None:
    """Return the cleaned plain-text body, or None if not safely separable."""
    match = HTML_TAG_RE.search(body)
    if not match:
        return None
    prefix = body[: match.start()]
    html_part = body[match.start():]
    if not SIGNATURE_START_RE.match(html_part):
        return None
    plain = prefix.rstrip()
    if not plain:
        return None
    return plain


def main() -> None:
    apply_changes = "--apply" in sys.argv

    db = SessionLocal()
    try:
        rows = (
            db.query(CampaignContent, Campaign)
            .join(Campaign, Campaign.id == CampaignContent.campaign_id)
            .filter(CampaignContent.channel == "email")
            .all()
        )

        cleaned, flagged = [], []
        for content, campaign in rows:
            subject_has_html = bool(HTML_TAG_RE.search(content.subject or ""))
            body_has_html = bool(HTML_TAG_RE.search(content.body or ""))
            if not (subject_has_html or body_has_html):
                continue

            if subject_has_html:
                # Never seen in this dataset's telltale patterns; always manual.
                flagged.append((content, campaign, "subject contains HTML"))
                continue

            new_body = try_clean(content.body or "")
            if new_body is None:
                flagged.append((content, campaign, "HTML not unambiguously separable from message text"))
                continue

            cleaned.append((content, campaign, new_body))

        print(f"{len(cleaned)} row(s) safely cleanable, {len(flagged)} row(s) need manual review.\n")

        for content, campaign, new_body in cleaned:
            print("=" * 80)
            print(f"CLEAN campaign_id={campaign.id} ({campaign.name!r}) content.id={content.id}")
            print(f"  old body snippet: {snippet(content.body)!r}")
            print(f"  new body: {new_body!r}")
            if apply_changes:
                content.body = new_body

        for content, campaign, reason in flagged:
            print("=" * 80)
            print(f"FLAG (manual review) campaign_id={campaign.id} ({campaign.name!r}) content.id={content.id}")
            print(f"  reason: {reason}")
            print(f"  body snippet: {snippet(content.body)!r}")

        if apply_changes:
            db.commit()
            print(f"\nApplied: {len(cleaned)} row(s) updated in the database.")
        else:
            print("\nDry run only -- rerun with --apply to write these changes.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
