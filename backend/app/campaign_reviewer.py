"""AI Marketing Campaign Reviewer for REACH.

Reviews campaign content against professional digital marketing best practices.
Does NOT rewrite content, invent recipient data, or alter placeholders.
Returns a structured quality score and constructive feedback.
"""
from __future__ import annotations

import re
from typing import Any

# Placeholders commonly used in REACH campaigns (case-insensitive match).
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([\w ]+?)\s*\}\}")
_COMMON_PLACEHOLDERS = {
    "name", "first_name", "firstname", "email", "company", "designation",
    "mobile", "phone", "sendername", "currentdate",
}

# Spam / urgency signals
_SPAM_WORDS = re.compile(
    r"\b(free|winner|congratulations|act now|limited time|urgent|!!!+|click here|"
    r"buy now|order now|risk[- ]free|no obligation|guarantee|\$\$\$|100%\s*free|"
    r"double your|earn money|work from home|weight loss)\b",
    re.IGNORECASE,
)
_ALL_CAPS_WORD = re.compile(r"\b[A-Z]{4,}\b")
_EXCLAIM_RE = re.compile(r"!{2,}")
_CTA_HINTS = re.compile(
    r"\b(click|register|sign up|signup|book|schedule|reply|call|visit|learn more|"
    r"get started|download|join|apply|confirm|unsubscribe|view|shop|buy|try|"
    r"claim|redeem|rsvp|read more|see more|contact)\b",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_MULTI_SPACE = re.compile(r"[ \t]{2,}")
_SENTENCE_END = re.compile(r"[.!?]\s+")


def _text(value: Any) -> str:
    return (value or "").strip() if isinstance(value, str) else str(value or "").strip()


def _placeholders(text: str) -> list[str]:
    return [m.group(1).strip() for m in _PLACEHOLDER_RE.finditer(text or "")]


def _grade(score: int) -> str:
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 60:
        return "Needs Improvement"
    return "Poor"


def _has_cta(text: str) -> bool:
    return bool(_CTA_HINTS.search(text or "")) or bool(_URL_RE.search(text or ""))


def _spam_signals(text: str) -> list[str]:
    reasons: list[str] = []
    if not text:
        return reasons
    if _EXCLAIM_RE.search(text):
        reasons.append("Multiple consecutive exclamation marks detected")
    caps = _ALL_CAPS_WORD.findall(text)
    # Ignore common short acronyms length handled by {4,}
    if len(caps) >= 3:
        reasons.append(f"Several ALL-CAPS words ({', '.join(caps[:5])})")
    promo = _SPAM_WORDS.findall(text)
    if promo:
        unique = sorted({p.lower() for p in promo})
        reasons.append(f"Promotional/spam-prone wording: {', '.join(unique[:6])}")
    if text.isupper() and len(text) > 20:
        reasons.append("Entire message is in ALL CAPS")
    if text.count("!") >= 4:
        reasons.append("Excessive exclamation marks")
    return reasons


def _readability_notes(text: str) -> list[str]:
    notes: list[str] = []
    if not text:
        return ["Content is empty"]
    words = text.split()
    if len(words) > 250:
        notes.append("Email body is long; consider tightening for mobile readers")
    sentences = [s for s in _SENTENCE_END.split(text) if s.strip()]
    long_sentences = [s for s in sentences if len(s.split()) > 30]
    if long_sentences:
        notes.append("Some sentences are very long; shorter sentences improve scan-ability")
    if _MULTI_SPACE.search(text):
        notes.append("Irregular spacing detected; clean up formatting")
    return notes


def _subject_review(subject: str) -> tuple[int, list[str]]:
    feedback: list[str] = []
    score = 75
    s = _text(subject)
    if not s:
        return 20, ["Subject line is missing"]
    length = len(s)
    if length < 20:
        feedback.append(f"Subject is short ({length} chars); 30–50 characters often perform better")
        score -= 8
    elif length > 70:
        feedback.append(f"Subject is long ({length} chars); may truncate on mobile (aim ≤60)")
        score -= 10
    else:
        feedback.append(f"Subject length is appropriate ({length} chars)")
        score += 5
    if _placeholders(s):
        feedback.append("Subject uses personalization placeholders")
        score += 6
    else:
        feedback.append("No personalization in subject; consider {{Name}} or {{Company}}")
        score -= 4
    if s.isupper():
        feedback.append("Subject is ALL CAPS — high spam risk")
        score -= 20
    spam = _spam_signals(s)
    if spam:
        feedback.extend(spam)
        score -= 12
    if not any(c in s for c in "?.:"):
        # mild curiosity hint
        if length < 40:
            feedback.append("Subject is clear but low-curiosity; a light intrigue angle can lift opens")
    return max(0, min(100, score)), feedback


def _email_review(subject: str, body: str, template_fields: dict | None, content_mode: str) -> tuple[int, list[str], dict]:
    feedback: list[str] = []
    score = 70

    subj_score, subj_fb = _subject_review(subject)
    feedback.extend([f"[Subject] {f}" for f in subj_fb])
    score = int(score * 0.4 + subj_score * 0.6)

    # Resolve body text for plain vs template mode
    if content_mode == "template" and template_fields:
        parts = [
            _text(template_fields.get("headline")),
            _text(template_fields.get("opening_line")),
            _text(template_fields.get("callout_text")),
            _text(template_fields.get("action_label")),
            _text(template_fields.get("secondary_action_label")),
        ]
        for b in (template_fields.get("bullets") or []):
            if isinstance(b, dict):
                parts.append(_text(b.get("label")))
                parts.append(_text(b.get("text")))
        body_text = "\n".join(p for p in parts if p)
        if template_fields.get("show_cta") and _text(template_fields.get("action_label")):
            feedback.append("Branded template includes a structured CTA block")
            score += 5
        elif template_fields.get("show_cta"):
            feedback.append("CTA block enabled but action label is empty")
            score -= 8
        else:
            feedback.append("No CTA block enabled in template mode")
            score -= 10
        if not _text(template_fields.get("headline")):
            feedback.append("Template headline is empty — goal clarity suffers")
            score -= 8
    else:
        body_text = _text(body)

    if not body_text:
        feedback.append("Email body is empty")
        score = min(score, 35)
    else:
        words = body_text.split()
        feedback.append(f"Body length ~{len(words)} words")
        if len(words) < 30:
            feedback.append("Body is very short; may lack context for the offer")
            score -= 6
        elif 40 <= len(words) <= 180:
            feedback.append("Body length is in a good range for promotional email")
            score += 5
        feedback.extend(_readability_notes(body_text))
        if _has_cta(body_text):
            feedback.append("CTA language or link is present in the body")
            score += 6
        else:
            feedback.append("No clear CTA detected in the body")
            score -= 12
        ph = _placeholders(body_text)
        if ph:
            feedback.append(f"Personalization placeholders used: {', '.join(sorted(set(ph))[:8])}")
            score += 5
        else:
            feedback.append("Body has no personalization placeholders")
            score -= 3
        spam = _spam_signals(body_text)
        if spam:
            feedback.extend(spam)
            score -= 10

    return max(0, min(100, score)), feedback, {"body_preview_len": len(body_text)}


def _whatsapp_review(body: str) -> tuple[int, list[str]]:
    feedback: list[str] = []
    score = 72
    text = _text(body)
    if not text:
        return 15, ["WhatsApp message is empty"]
    length = len(text)
    emoji_count = sum(1 for c in text if ord(c) > 0x1F300)
    if length > 500:
        feedback.append(f"Message is long ({length} chars); WhatsApp performs better under ~300")
        score -= 12
    elif length > 300:
        feedback.append(f"Slightly long ({length} chars); consider trimming")
        score -= 5
    else:
        feedback.append(f"Length is concise ({length} chars)")
        score += 6
    if emoji_count > 5:
        feedback.append(f"High emoji count ({emoji_count}); keep to 1–3 for professional tone")
        score -= 8
    elif emoji_count > 0:
        feedback.append(f"Uses {emoji_count} emoji(s) — acceptable if brand-appropriate")
    if _has_cta(text):
        feedback.append("CTA present")
        score += 6
    else:
        feedback.append("No clear CTA — add a reply prompt or link")
        score -= 10
    if _placeholders(text):
        feedback.append("Personalization placeholders present")
        score += 4
    spam = _spam_signals(text)
    if spam:
        feedback.extend(spam)
        score -= 10
    return max(0, min(100, score)), feedback


def _sms_review(body: str) -> tuple[int, list[str]]:
    feedback: list[str] = []
    score = 70
    text = _text(body)
    if not text:
        return 15, ["SMS message is empty"]
    length = len(text)
    # GSM single segment ~160; UCS-2 ~70. Recommend staying under 160.
    if length <= 160:
        feedback.append(f"Fits a single SMS segment ({length}/160 chars)")
        score += 8
    elif length <= 320:
        feedback.append(f"Likely multi-segment ({length} chars); may increase cost and drop-off")
        score -= 8
    else:
        feedback.append(f"Very long for SMS ({length} chars); strong risk of truncation")
        score -= 18
    if _has_cta(text):
        feedback.append("CTA present")
        score += 6
    else:
        feedback.append("No clear CTA")
        score -= 10
    if _placeholders(text):
        feedback.append("Personalization placeholders present")
        score += 3
    # SMS should avoid fluff
    words = text.split()
    if len(words) > 40:
        feedback.append("Contains many words for SMS; remove non-essential phrases")
        score -= 6
    spam = _spam_signals(text)
    if spam:
        feedback.extend(spam)
        score -= 10
    return max(0, min(100, score)), feedback


def _estimate_metrics(email_score: int, has_personalization: bool, spam_level: str, subject_ok: bool) -> dict:
    # Conservative ranges grounded in B2B/email marketing norms.
    if email_score >= 85 and subject_ok and spam_level == "low":
        open_r, click_r, reply_r = "18–28%", "2.5–5%", "0.5–1.5%"
    elif email_score >= 70 and spam_level != "high":
        open_r, click_r, reply_r = "12–20%", "1.5–3.5%", "0.3–1%"
    elif email_score >= 55:
        open_r, click_r, reply_r = "8–14%", "0.8–2%", "0.2–0.6%"
    else:
        open_r, click_r, reply_r = "4–10%", "0.3–1%", "0.1–0.4%"
    if has_personalization and spam_level == "low":
        # slight uplift noted in summary ranges already mid-band
        pass
    return {"open_rate": open_r, "click_rate": click_r, "reply_rate": reply_r}


def review_campaign(
    *,
    name: str = "",
    description: str = "",
    email_enabled: bool = False,
    whatsapp_enabled: bool = False,
    sms_enabled: bool = False,
    email_subject: str = "",
    email_body: str = "",
    email_content_mode: str = "plain",
    email_template_fields: dict | None = None,
    whatsapp_body: str = "",
    sms_body: str = "",
) -> dict:
    """Review campaign content and return the standard JSON review payload."""
    strengths: list[str] = []
    issues: list[str] = []
    recommendations: list[str] = []

    channels_on = []
    if email_enabled:
        channels_on.append("email")
    if whatsapp_enabled:
        channels_on.append("whatsapp")
    if sms_enabled:
        channels_on.append("sms")

    # Goal clarity
    goal_bits = [description, email_subject, email_body]
    if email_content_mode == "template" and email_template_fields:
        goal_bits.extend([
            _text(email_template_fields.get("headline")),
            _text(email_template_fields.get("action_label")),
        ])
    goal_text = " ".join(_text(g) for g in goal_bits if g)
    if name and (description or email_subject or email_body or email_template_fields):
        strengths.append("Campaign has a name and content to evaluate")
    if not channels_on:
        issues.append("No channels enabled")
        recommendations.append("Enable at least one channel (email, WhatsApp, or SMS) before sending")

    email_score, email_fb = 0, []
    wa_score, wa_fb = 0, []
    sms_score, sms_fb = 0, []
    meta = {}

    if email_enabled:
        email_score, email_fb, meta = _email_review(
            email_subject, email_body, email_template_fields, email_content_mode
        )
    else:
        email_fb = ["Email channel disabled — skipped"]

    if whatsapp_enabled:
        wa_score, wa_fb = _whatsapp_review(whatsapp_body)
    else:
        wa_fb = ["WhatsApp channel disabled — skipped"]

    if sms_enabled:
        sms_score, sms_fb = _sms_review(sms_body)
    else:
        sms_fb = ["SMS channel disabled — skipped"]

    # Aggregate score from enabled channels
    enabled_scores = []
    if email_enabled:
        enabled_scores.append(email_score)
    if whatsapp_enabled:
        enabled_scores.append(wa_score)
    if sms_enabled:
        enabled_scores.append(sms_score)
    campaign_score = int(round(sum(enabled_scores) / len(enabled_scores))) if enabled_scores else 25

    # Personalization
    all_text = " ".join([
        email_subject, email_body, whatsapp_body, sms_body,
        _text((email_template_fields or {}).get("headline")),
        _text((email_template_fields or {}).get("opening_line")),
    ])
    used_ph = sorted(set(_placeholders(all_text)))
    if used_ph:
        personalization_review = (
            f"Placeholders detected: {', '.join('{{' + p + '}}' for p in used_ph)}. "
            "Ensure dataset columns match these keys (case-insensitive)."
        )
        strengths.append("Uses merge placeholders for personalization")
    else:
        personalization_review = (
            "No placeholders like {{Name}} or {{Company}} found. "
            "Adding relevant personalization usually improves engagement."
        )
        recommendations.append("Add personalization placeholders (e.g. {{Name}}, {{Company}}) where appropriate")
        campaign_score = max(0, campaign_score - 3)

    # Spam
    spam_reasons: list[str] = []
    for blob in (email_subject, email_body, whatsapp_body, sms_body):
        spam_reasons.extend(_spam_signals(blob))
    if email_content_mode == "template" and email_template_fields:
        for key in ("headline", "opening_line", "callout_text", "action_label"):
            spam_reasons.extend(_spam_signals(_text(email_template_fields.get(key))))
    # dedupe
    seen = set()
    spam_reasons = [r for r in spam_reasons if not (r in seen or seen.add(r))]
    if len(spam_reasons) >= 3:
        spam_level = "high"
        campaign_score = max(0, campaign_score - 15)
    elif spam_reasons:
        spam_level = "medium"
        campaign_score = max(0, campaign_score - 7)
    else:
        spam_level = "low"
        strengths.append("Low spam-signal profile")

    # CTA
    cta_ok = False
    if email_enabled:
        cta_ok = _has_cta(email_body) or (
            email_content_mode == "template"
            and bool((email_template_fields or {}).get("show_cta"))
            and bool(_text((email_template_fields or {}).get("action_label")))
        )
    if whatsapp_enabled:
        cta_ok = cta_ok or _has_cta(whatsapp_body)
    if sms_enabled:
        cta_ok = cta_ok or _has_cta(sms_body)
    if cta_ok:
        cta_review = "At least one enabled channel includes a recognizable CTA."
        strengths.append("CTA present on an enabled channel")
    else:
        cta_review = "No clear call-to-action detected on enabled channels."
        issues.append("Weak or missing CTA")
        recommendations.append("Add a single, specific CTA (e.g. Register, Reply YES, Visit link)")
        campaign_score = max(0, campaign_score - 8)

    # Grammar (lightweight heuristics only — not a full grammar engine)
    grammar_flags: list[str] = []
    for label, blob in (("email", email_body), ("whatsapp", whatsapp_body), ("sms", sms_body)):
        if blob and re.search(r"\bi\b", blob) and not re.search(r"\bI\b", blob):
            grammar_flags.append(f"{label}: lowercase standalone 'i' may need capitalization")
        if blob and re.search(r"[a-z]\.[A-Z]", blob):
            grammar_flags.append(f"{label}: missing space after a period")
    if grammar_flags:
        grammar_review = "; ".join(grammar_flags)
        recommendations.append("Proofread for capitalization and spacing")
        campaign_score = max(0, campaign_score - 2)
    else:
        grammar_review = "No obvious grammar red flags from heuristic checks (not a full linguistic review)."

    # Multi-channel consistency (simple token overlap on non-trivial words)
    consistency_review = "Only one channel enabled — consistency N/A."
    bodies = []
    if email_enabled:
        bodies.append(("email", email_body or _text((email_template_fields or {}).get("headline"))))
    if whatsapp_enabled:
        bodies.append(("whatsapp", whatsapp_body))
    if sms_enabled:
        bodies.append(("sms", sms_body))
    if len(bodies) >= 2:
        def tokens(t: str) -> set[str]:
            return {w.lower() for w in re.findall(r"[A-Za-z]{4,}", t or "")}

        sets = [(ch, tokens(t)) for ch, t in bodies]
        overlaps = []
        for i in range(len(sets)):
            for j in range(i + 1, len(sets)):
                a, b = sets[i][1], sets[j][1]
                if not a or not b:
                    overlaps.append(0.0)
                else:
                    overlaps.append(len(a & b) / max(1, len(a | b)))
        avg_overlap = sum(overlaps) / len(overlaps) if overlaps else 0
        if avg_overlap >= 0.15:
            consistency_review = (
                f"Channels appear to share core terms (overlap ~{avg_overlap:.0%}). "
                "Offer messaging looks reasonably aligned."
            )
            strengths.append("Multi-channel messaging is broadly consistent")
        else:
            consistency_review = (
                f"Low lexical overlap across channels (~{avg_overlap:.0%}). "
                "Confirm all channels promote the same offer and CTA."
            )
            issues.append("Possible multi-channel message mismatch")
            recommendations.append("Align offer, benefit, and CTA wording across email / WhatsApp / SMS")
            campaign_score = max(0, campaign_score - 5)

    # Goal clarity
    if email_enabled and not _text(email_subject) and email_content_mode != "template":
        issues.append("Email subject missing — objective harder to grasp at open time")
    if not goal_text or len(goal_text) < 15:
        issues.append("Campaign goal is unclear from available content")
        recommendations.append("State the objective clearly in the opening line and subject")
        campaign_score = max(0, campaign_score - 5)
    else:
        strengths.append("Enough content present to infer a campaign objective")

    # Mobile friendliness notes
    if email_enabled and len(_text(email_body)) > 1200:
        recommendations.append("Shorten email body for mobile screens (keep key CTA above the fold)")
    if sms_enabled and len(_text(sms_body)) > 160:
        recommendations.append("Keep SMS under 160 characters when possible")

    subject_ok = bool(_text(email_subject)) and not _text(email_subject).isupper()
    metrics = _estimate_metrics(
        email_score if email_enabled else campaign_score,
        bool(used_ph),
        spam_level,
        subject_ok,
    )

    campaign_score = max(0, min(100, campaign_score))
    grade = _grade(campaign_score)

    summary_parts = [
        f"Overall grade: {grade} ({campaign_score}/100).",
        f"Channels reviewed: {', '.join(channels_on) if channels_on else 'none'}.",
        f"Spam risk: {spam_level}.",
    ]
    if issues:
        summary_parts.append(f"Top concerns: {issues[0]}.")
    else:
        summary_parts.append("No critical issues flagged.")

    if campaign_score >= 75:
        final_rec = "Campaign is in good shape. Address minor notes, then proceed to a small test send."
    elif campaign_score >= 60:
        final_rec = "Needs improvement before a large send. Fix CTA, spam, or consistency items first."
    else:
        final_rec = "Not ready to send. Resolve high-priority issues (empty content, spam signals, missing CTA)."

    # Collect channel-driven issues into recommendations if scores low
    if email_enabled and email_score < 60:
        recommendations.append("Revise email subject/body using the email channel feedback")
    if whatsapp_enabled and wa_score < 60:
        recommendations.append("Shorten WhatsApp copy and clarify the CTA")
    if sms_enabled and sms_score < 60:
        recommendations.append("Tighten SMS to one clear offer + CTA within 160 characters")

    # Dedupe lists while preserving order
    def uniq(items: list[str]) -> list[str]:
        out, seen_local = [], set()
        for i in items:
            if i not in seen_local:
                seen_local.add(i)
                out.append(i)
        return out

    return {
        "campaign_score": campaign_score,
        "grade": grade,
        "summary": " ".join(summary_parts),
        "estimated_metrics": metrics,
        "strengths": uniq(strengths),
        "issues": uniq(issues),
        "recommendations": uniq(recommendations),
        "channel_reviews": {
            "email": {"score": email_score if email_enabled else 0, "feedback": email_fb},
            "whatsapp": {"score": wa_score if whatsapp_enabled else 0, "feedback": wa_fb},
            "sms": {"score": sms_score if sms_enabled else 0, "feedback": sms_fb},
        },
        "spam_risk": {
            "level": spam_level,
            "reasons": spam_reasons,
        },
        "cta_review": cta_review,
        "personalization_review": personalization_review,
        "grammar_review": grammar_review,
        "consistency_review": consistency_review,
        "final_recommendation": final_rec,
    }
