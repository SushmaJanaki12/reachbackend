"""
One-off audit: find campaign_content rows (channel='email') whose subject/body
still contain raw HTML markup left over from the reverted HTML/signature
feature.

Usage:
    cd backend && python -m scripts.find_html_content
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models import CampaignContent, Campaign

HTML_TAG_RE = re.compile(r"<[a-zA-Z][^>]*>")


def snippet(text: str, length: int = 150) -> str:
    text = text.replace("\n", " ").replace("\r", " ")
    return text[:length] + ("..." if len(text) > length else "")


def main() -> None:
    db = SessionLocal()
    try:
        rows = (
            db.query(CampaignContent, Campaign)
            .join(Campaign, Campaign.id == CampaignContent.campaign_id)
            .filter(CampaignContent.channel == "email")
            .all()
        )

        flagged = []
        for content, campaign in rows:
            hit_subject = bool(HTML_TAG_RE.search(content.subject or ""))
            hit_body = bool(HTML_TAG_RE.search(content.body or ""))
            if hit_subject or hit_body:
                flagged.append((content, campaign, hit_subject, hit_body))

        print(f"Scanned {len(rows)} email campaign_content rows; {len(flagged)} flagged.\n")

        for content, campaign, hit_subject, hit_body in flagged:
            print("=" * 80)
            print(f"campaign_id={campaign.id}  campaign_name={campaign.name!r}  content.id={content.id}")
            print(f"  subject has HTML: {hit_subject}  body has HTML: {hit_body}")
            if hit_subject:
                print(f"  subject: {snippet(content.subject)!r}")
            print(f"  body snippet: {snippet(content.body)!r}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
