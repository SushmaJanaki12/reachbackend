"""Reply-sentiment classification for follow-up sequences (see app/followups.py).

Keyword-based for now, per spec -- a single swappable entry point so an
LLM-based classifier can replace the body later without any caller changes.
"""
import re
from typing import Literal

Sentiment = Literal["interested", "not_interested", "unclear"]

# Checked in order; a reply is classified by whichever list it matches first.
# Negative phrases are checked before positive ones so e.g. "not interested"
# doesn't get caught by a looser "interested" match.
_NEGATIVE_PHRASES = [
    "not interested", "no longer interested", "not right now", "no thanks",
    "unsubscribe", "remove me", "stop", "opt out", "opt-out", "do not contact",
]
_POSITIVE_PHRASES = [
    "interested", "yes", "sounds good", "let's talk", "lets talk",
    "sign me up", "count me in", "sure", "please proceed",
]


def classify_reply(text: str) -> Sentiment:
    normalized = re.sub(r"\s+", " ", (text or "")).strip().lower()
    if not normalized:
        return "unclear"
    if any(phrase in normalized for phrase in _NEGATIVE_PHRASES):
        return "not_interested"
    if any(phrase in normalized for phrase in _POSITIVE_PHRASES):
        return "interested"
    return "unclear"
