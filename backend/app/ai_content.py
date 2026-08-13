"""AI campaign message generation (email / WhatsApp / SMS).

Uses an optional OpenAI-compatible API when OPENAI_API_KEY is set; otherwise
falls back to high-quality deterministic templates tuned for inbox placement
(short subject, low spam lexicon, clear CTA, personalization tokens).
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Always load backend/.env (file is next to app/), not whatever the CWD is
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)

from .campaign_reviewer import review_campaign

_SPAMMY = re.compile(
    r"\b(free|winner|congratulations|act now|limited time|urgent|!!!+|click here|"
    r"buy now|risk[- ]free|guarantee|\$\$\$)\b",
    re.I,
)


def _tone_line(tone: str) -> str:
    t = (tone or "professional").lower()
    if t == "friendly":
        return "warm and approachable"
    if t == "direct":
        return "concise and direct"
    return "professional and respectful"


def _fallback_generate(
    *,
    channel: str,
    goal: str,
    tone: str,
    product: str,
    sender_name: str,
    company: str,
    followup_number: int = 0,
) -> dict[str, Any]:
    goal = goal or "start a conversation and book a short call"
    product = product or company or "our solution"
    sender = sender_name or "the team"
    tone_desc = _tone_line(tone)

    if followup_number > 0:
        subject = f"{{{{Name}}}}, quick follow-up on {product}"
        email_body = (
            f"Hi {{{{Name}}}},\n\n"
            f"I wanted to follow up on my earlier note about {product}. "
            f"I know inboxes get busy — happy to keep this brief.\n\n"
            f"Would you be open to a short conversation about {goal}?\n\n"
            f"Best regards,\n{sender}"
        )
        wa = (
            f"Hi {{{{Name}}}} — gentle follow-up on {product}. "
            f"Open to a quick chat about {goal}? Reply YES and I’ll share times."
        )
        sms = (
            f"{{{{Name}}}}: follow-up on {product}. "
            f"Reply YES for a short call, or STOP to opt out."
        )
    else:
        subject = f"{{{{Name}}}}, idea for {{{{Company}}}}"
        if len(subject) > 60:
            subject = f"{{{{Name}}}}, quick idea for your team"
        email_body = (
            f"Hi {{{{Name}}}},\n\n"
            f"I came across {{{{Company}}}} and thought {product} might help your team "
            f"{goal}.\n\n"
            f"If useful, I’d be glad to share a brief overview — no long deck, just a "
            f"practical walkthrough.\n\n"
            f"Would you be available for a 15-minute call this week?\n\n"
            f"Best regards,\n{sender}\n{company}".strip()
        )
        wa = (
            f"Hi {{{{Name}}}} — {sender} from {company or 'our team'}. "
            f"We help teams with {product}. Open to a quick chat about {goal}? "
            f"Reply YES and I’ll suggest times."
        )
        sms = (
            f"{{{{Name}}}}: {product} for {{{{Company}}}}. "
            f"Reply YES for a short call, or STOP to opt out."
        )

    # Strip spammy words from fallback
    for key in ("subject",):
        pass
    subject = _SPAMMY.sub("", subject).replace("  ", " ").strip()

    payloads = {
        "email": {"subject": subject, "body": email_body},
        "whatsapp": {"subject": "", "body": wa},
        "sms": {"subject": "", "body": sms[:160]},
    }
    out = payloads.get(channel, payloads["email"])
    out["channel"] = channel
    out["tone"] = tone
    out["goal"] = goal
    out["followup_number"] = followup_number
    out["inbox_tips"] = [
        "Keep subject under 60 characters",
        "Avoid ALL CAPS and multiple exclamation marks",
        "Use {{Name}} / {{Company}} personalization",
        "One clear CTA (reply or short call)",
        "Authenticate domain (SPF/DKIM/DMARC) for inbox placement",
    ]
    return out


def _openai_generate(prompt: str, api_key: str, base_url: str) -> dict | None:
    url = base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "temperature": 0.7,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a senior B2B sales copywriter. Write cold-outreach that "
                    "earns primary-inbox placement and a high reply rate. "
                    "Return ONLY JSON with keys subject, body.\n"
                    "Rules:\n"
                    "- Sound human and specific; reference the goal naturally\n"
                    "- Subject under 55 chars; no clickbait, no ALL CAPS, no !!!\n"
                    "- Body: short paragraphs, under 120 words (email) / 60 (WhatsApp) / 160 chars (SMS)\n"
                    "- One clear, low-pressure CTA (reply or 15-min chat)\n"
                    "- Use {{Name}} and {{Company}} placeholders where natural\n"
                    "- Avoid spam triggers: free!!!, act now, limited time, guarantee, 100%, "
                    "click here, congratulations, winner, risk-free\n"
                    "- No fake urgency; no misleading promises\n"
                    "- Professional, warm, peer-to-peer tone"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode())
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception as e:
        # Visible in the uvicorn terminal — do not swallow silently
        print(f"[ai_content] OpenAI failed: {type(e).__name__}: {e}")
        if hasattr(e, "read"):
            try:
                print("[ai_content] body:", e.read().decode()[:500])
            except Exception:
                pass
        return None


def generate_message(
    *,
    channel: str = "email",
    goal: str = "",
    tone: str = "professional",
    product: str = "",
    sender_name: str = "",
    company: str = "",
    followup_number: int = 0,
    extra_context: str = "",
) -> dict[str, Any]:
    channel = (channel or "email").lower()
    if channel not in ("email", "whatsapp", "sms"):
        channel = "email"

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
    print(f"[ai_content] env={_ENV_PATH} exists={_ENV_PATH.exists()} key_len={len(api_key)}")
    
    if api_key:
        step_hint = (
            "First-touch intro: value + why them + soft CTA."
            if int(followup_number or 0) <= 0
            else f"Follow-up #{followup_number}: brief bump, new angle or social proof, no guilt."
        )
        prompt = (
            f"Channel: {channel}\nTone: {tone}\nCampaign goal: {goal or 'start a short conversation'}\n"
            f"Product/offer: {product}\nSender name: {sender_name}\nSender company: {company}\n"
            f"Step: {step_hint}\n"
            f"Extra context: {extra_context}\n"
            f"Write for best impression (trust, clarity, relevance). Length cap: "
            f"{'160 characters' if channel == 'sms' else '60 words' if channel == 'whatsapp' else '120 words'}."
        )
        parsed = _openai_generate(prompt, api_key, base_url)
        if parsed and parsed.get("body"):
            result = {
                "channel": channel,
                "subject": parsed.get("subject") or "",
                "body": parsed.get("body") or "",
                "tone": tone,
                "goal": goal,
                "followup_number": followup_number,
                "source": "openai",
                "inbox_tips": [
                    "AI draft — review before send",
                    "Verify SPF/DKIM/DMARC on sending domain",
                    "Personalize with merge fields before launch",
                ],
            }
            if channel != "email":
                result["subject"] = ""
            return result

    result = _fallback_generate(
        channel=channel, goal=goal, tone=tone, product=product,
        sender_name=sender_name, company=company, followup_number=followup_number,
    )
    result["source"] = "template"
    return result



def _openai_json(messages: list[dict], api_key: str, base_url: str, temperature: float = 0.3) -> dict | None:
    """Low-level chat completion expecting a JSON object response."""
    url = base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
        "temperature": temperature,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    raw = ""
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            data = json.loads(raw)
        content = data["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            parts = content.split("```", 2)
            if len(parts) > 1:
                content = parts[1].strip()
            if content.startswith("json"):
                content = content[4:].strip()
        return json.loads(content)
    except Exception as e:
        print(f"[ai_content] OpenAI JSON failed: {type(e).__name__}: {e}")
        if raw:
            print("[ai_content] raw snippet:", raw[:500])
        return None


def _looks_like_gibberish(text: str) -> bool:
    """Reject pure noise (1111, asdfgh, aaa) while allowing imperfect real phrases."""
    s = (text or "").strip()
    if not s:
        return True
    compact = re.sub(r"\s+", "", s)
    letters = re.findall(r"[A-Za-z]", s)
    digits = re.findall(r"\d", s)
    # only digits / symbols
    if not letters and digits:
        return True
    if len(compact) < 3:
        return True
    # single repeated character: aaaa, 1111
    if len(set(compact.lower())) <= 1:
        return True
    # keyboard smash / no vowels and long enough
    lower = "".join(letters).lower()
    if len(lower) >= 5:
        vowels = sum(1 for c in lower if c in "aeiou")
        if vowels == 0:
            return True
    # very high consonant-only ratio with no spaces and short "words"
    words = re.findall(r"[A-Za-z]{2,}", s)
    if not words and len(letters) >= 4:
        return True
    return False


def validate_goal_with_ai(
    goal: str,
    *,
    campaign_name: str = "",
    product: str = "",
) -> tuple[bool, str]:
    """Accept meaningful goals (even imperfect grammar) like ChatGPT/Grok.

    Only blocks empty input and obvious gibberish (e.g. 1111, aaaddg).
    Does NOT require perfect English or a formal outreach outcome phrasing.
    """
    clean_goal = " ".join((goal or "").split())
    if not clean_goal:
        return False, "Please type a campaign goal so AI can write your message."

    placeholder_goals = {"test", "testing", "none", "n/a", "na", "todo", "-", ".", "..", "..."}
    if clean_goal.lower() in placeholder_goals:
        return False, "Please type a real goal (e.g. introduce Niko to buyers)."

    if _looks_like_gibberish(clean_goal):
        return False, "That does not look like a real goal. Type a short meaningful phrase."

    # Soft AI check — default ACCEPT. Only reject clear nonsense.
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return True, "Goal accepted."

    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
    parsed = _openai_json(
        [
            {
                "role": "system",
                "content": (
                    "You are a permissive filter for outreach AI writing. "
                    "ACCEPT any goal that a human could mean for sales/marketing/outreach, "
                    "even with bad grammar, typos, or informal wording "
                    "(e.g. 'introduce niko brand to leads' is VALID). "
                    "REJECT only pure gibberish, random characters, or empty meaning "
                    "(e.g. '1111', 'asdfgh', 'aaaa'). "
                    "When unsure, set valid=true. "
                    "Return ONLY JSON: valid (boolean), reason (short string)."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "goal": clean_goal,
                        "campaign_name": campaign_name,
                        "product_or_company": product,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        api_key,
        base_url,
        temperature=0,
    )
    if not isinstance(parsed, dict):
        return True, "Goal accepted."

    valid = parsed.get("valid", True)
    if isinstance(valid, str):
        valid = valid.strip().lower() in {"true", "yes", "1"}
    # Bias toward accept if model is harsh on informal goals
    reason = str(parsed.get("reason") or "").strip()
    if valid:
        return True, reason or "Goal accepted."
    # Second chance: if local says not gibberish, still accept informal goals
    if not _looks_like_gibberish(clean_goal) and len(clean_goal) >= 8:
        return True, "Goal accepted (informal wording is OK)."
    return False, reason or "Please type a short meaningful goal."


def _grade_from_score(score: int) -> str:
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 60:
        return "Needs Improvement"
    return "Poor"



def ai_score_dataset(report: dict) -> dict | None:
    """Score an audience validation report with AI (quality + recommendations).

    Returns dict with quality_score, recommendations, summary_note, score_source=openai
    or None if API unavailable / parse failure.
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()

    summary = report.get("summary") or {}
    breakdown = report.get("score_breakdown") or {}
    mapping = report.get("column_mapping") or {}
    issue_samples = []
    for r in (report.get("rows") or [])[:40]:
        if r.get("status") == "valid":
            continue
        for iss in (r.get("issues") or [])[:3]:
            issue_samples.append({
                "row": r.get("row_number"),
                "email": r.get("email") or "",
                "status": r.get("status"),
                "issue": iss.get("description") or iss.get("type"),
            })

    payload = {
        "totals": summary,
        "rule_metrics": breakdown,
        "column_mapping": {
            "name": mapping.get("name"),
            "email": mapping.get("email"),
            "mobile": mapping.get("mobile"),
            "suggestions": mapping.get("suggestions") or [],
        },
        "sample_issues": issue_samples[:25],
        "rule_quality_score": report.get("quality_score"),
    }

    system = (
        "You are an expert B2B outreach data-quality reviewer. "
        "Given structured validation facts about a contact list (CSV/Excel), "
        "assign a quality_score from 0-100 for campaign readiness "
        "(deliverability, completeness, personalization readiness, risk of bounces). "
        "Be strict on invalid emails, missing phones when SMS/WhatsApp matters, "
        "duplicates, and bad column mapping. "
        "Return ONLY JSON with keys: "
        "quality_score (int 0-100), "
        "recommendations (array of short actionable strings, max 8), "
        "summary_note (one sentence for the user)."
    )
    parsed = _openai_json(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": "Score this contact dataset:\n" + json.dumps(payload, ensure_ascii=False)},
        ],
        api_key,
        base_url,
        temperature=0.2,
    )
    if not parsed or not isinstance(parsed, dict):
        return None
    try:
        score = int(parsed.get("quality_score", 0))
    except Exception:
        return None
    score = max(0, min(100, score))
    recs = parsed.get("recommendations") or []
    if isinstance(recs, str):
        recs = [recs]
    note = str(parsed.get("summary_note") or "").strip()
    return {
        "quality_score": score,
        "recommendations": [str(x) for x in recs if x][:8],
        "summary_note": note,
        "score_source": "openai",
    }


def ai_review_campaign(
    *,
    name: str = "",
    description: str = "",
    goal: str = "",
    email_enabled: bool = False,
    whatsapp_enabled: bool = False,
    sms_enabled: bool = False,
    email_subject: str = "",
    email_body: str = "",
    whatsapp_body: str = "",
    sms_body: str = "",
) -> dict | None:
    """Ask the model to score outreach copy for inbox quality and goal fit.

    Returns the same shape as campaign_reviewer.review_campaign, or None on failure.
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()

    channels = []
    if email_enabled:
        channels.append("email")
    if whatsapp_enabled:
        channels.append("whatsapp")
    if sms_enabled:
        channels.append("sms")
    if not channels:
        channels = ["email"]

    payload = {
        "campaign_name": name or "Untitled",
        "campaign_goal": goal or description or "",
        "channels_enabled": channels,
        "email_subject": email_subject if email_enabled else "",
        "email_body": email_body if email_enabled else "",
        "whatsapp_body": whatsapp_body if whatsapp_enabled else "",
        "sms_body": sms_body if sms_enabled else "",
    }

    system = (
        "You are an expert B2B cold-outreach and deliverability reviewer. "
        "Score the message for primary-inbox placement, clarity, personalization, "
        "spam risk, CTA strength, and fit to the stated campaign goal. "
        "Return ONLY a JSON object with exactly these keys:\n"
        "campaign_score (integer 0-100),\n"
        "grade (Excellent|Good|Needs Improvement|Poor),\n"
        "summary (string),\n"
        "estimated_metrics: {open_rate, click_rate, reply_rate} as short range strings like \"18-28%\",\n"
        "strengths (array of strings),\n"
        "issues (array of strings),\n"
        "recommendations (array of strings),\n"
        "channel_reviews: {email: {score:int, feedback:string[]}, whatsapp: {...}, sms: {...}},\n"
        "spam_risk: {level: low|medium|high, reasons: string[]},\n"
        "cta_review (string),\n"
        "personalization_review (string),\n"
        "grammar_review (string),\n"
        "consistency_review (string),\n"
        "final_recommendation (string),\n"
        "inbox_tips (array of short practical tips).\n"
        "Disabled channels must have score 0 and feedback noting they were skipped. "
        "Be strict on spammy wording, ALL CAPS, missing CTA, weak personalization, "
        "and mismatch between goal and copy. Keep feedback concrete and actionable."
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": "Review this campaign content:\n" + json.dumps(payload, ensure_ascii=False)},
    ]
    parsed = _openai_json(messages, api_key, base_url, temperature=0.2)
    if not parsed or not isinstance(parsed, dict):
        return None

    try:
        score = int(parsed.get("campaign_score", 0))
    except Exception:
        score = 0
    score = max(0, min(100, score))
    grade = parsed.get("grade") or _grade_from_score(score)

    def _ch(key: str) -> dict:
        raw = (parsed.get("channel_reviews") or {}).get(key) or {}
        try:
            sc = int(raw.get("score", 0))
        except Exception:
            sc = 0
        fb = raw.get("feedback") or []
        if isinstance(fb, str):
            fb = [fb]
        return {"score": max(0, min(100, sc)), "feedback": list(fb)[:12]}

    metrics = parsed.get("estimated_metrics") or {}
    spam = parsed.get("spam_risk") or {}
    level = str(spam.get("level") or "low").lower()
    if level not in ("low", "medium", "high"):
        level = "low"
    reasons = spam.get("reasons") or []
    if isinstance(reasons, str):
        reasons = [reasons]

    tips = parsed.get("inbox_tips") or []
    if isinstance(tips, str):
        tips = [tips]
    recs = list(parsed.get("recommendations") or [])
    if isinstance(recs, str):
        recs = [recs]
    # surface tips in recommendations for UIs that only show that list
    for tip in tips:
        if tip and tip not in recs:
            recs.append(tip)

    return {
        "campaign_score": score,
        "grade": grade,
        "summary": parsed.get("summary") or f"AI review: {grade} ({score}/100).",
        "estimated_metrics": {
            "open_rate": str(metrics.get("open_rate") or "12-20%"),
            "click_rate": str(metrics.get("click_rate") or "1.5-3%"),
            "reply_rate": str(metrics.get("reply_rate") or "0.5-1.5%"),
            "assumptions": list(metrics.get("assumptions") or [
                "AI estimate for cold outreach; not live analytics",
            ]),
        },
        "strengths": list(parsed.get("strengths") or [])[:10],
        "issues": list(parsed.get("issues") or [])[:10],
        "recommendations": recs[:12],
        "channel_reviews": {
            "email": _ch("email"),
            "whatsapp": _ch("whatsapp"),
            "sms": _ch("sms"),
        },
        "spam_risk": {"level": level, "reasons": list(reasons)[:10]},
        "cta_review": str(parsed.get("cta_review") or ""),
        "personalization_review": str(parsed.get("personalization_review") or ""),
        "grammar_review": str(parsed.get("grammar_review") or ""),
        "consistency_review": str(parsed.get("consistency_review") or ""),
        "final_recommendation": str(parsed.get("final_recommendation") or ""),
        "review_source": "openai",
        "inbox_tips": list(tips)[:8],
    }




def score_copy_rules(
    *,
    channel: str,
    subject: str = "",
    body: str = "",
    goal: str = "",
) -> dict[str, Any]:
    """Deterministic production score (0-100). Same input => same score.

    Checklist is what Improve targets — fixing items reliably raises the number.
    """
    ch = (channel or "email").lower()
    subject = (subject or "").strip()
    body = (body or "").strip()
    full = f"{subject}\n{body}".strip()

    issues: list[str] = []
    strengths: list[str] = []
    suggestions: list[str] = []
    points = 0
    max_points = 100

    # --- Length / structure (25) ---
    if ch == "email":
        subj_len = len(subject)
        if 8 <= subj_len <= 55:
            points += 12
            strengths.append("Subject length is inbox-friendly")
        elif subj_len == 0:
            issues.append("Missing subject line")
            suggestions.append("Add a clear subject under 55 characters")
        else:
            points += 5
            issues.append("Subject too short or too long")
            suggestions.append("Keep subject between 8 and 55 characters")

        words = len(body.split())
        if 40 <= words <= 130:
            points += 13
            strengths.append("Body length is scannable")
        elif 20 <= words < 40 or 130 < words <= 180:
            points += 7
            suggestions.append("Aim for ~50–120 words in the body")
        elif words < 20:
            issues.append("Body is too short to convey value")
            suggestions.append("Add a short value line and one clear CTA")
        else:
            points += 3
            issues.append("Body is too long for cold outreach")
            suggestions.append("Cut to under 120 words")
    elif ch == "whatsapp":
        words = len(body.split())
        if 15 <= words <= 70:
            points += 25
            strengths.append("WhatsApp length is conversational")
        elif words:
            points += 12
            suggestions.append("Keep WhatsApp under ~60 words")
        else:
            issues.append("Empty WhatsApp body")
    else:  # sms
        n = len(body)
        if 20 <= n <= 160:
            points += 25
            strengths.append("SMS fits standard length")
        elif n:
            points += 10
            issues.append("SMS may be truncated or too short")
            suggestions.append("Keep SMS under 160 characters")
        else:
            issues.append("Empty SMS body")

    # --- Personalization (20) ---
    has_name = bool(re.search(r"\{\{\s*(name|first_name|firstname)\s*\}\}", full, re.I))
    has_company = bool(re.search(r"\{\{\s*company\s*\}\}", full, re.I))
    if has_name and has_company:
        points += 20
        strengths.append("Uses {{Name}} and {{Company}}")
    elif has_name or has_company:
        points += 12
        suggestions.append("Add both {{Name}} and {{Company}} for higher personalization")
    else:
        issues.append("No {{Name}} / {{Company}} personalization")
        suggestions.append("Open with Hi {{Name}} and mention {{Company}}")

    # --- Spam risk (20) ---
    spam_hits = _SPAM_WORDS.findall(full) if '_SPAM_WORDS' in dir() else []
    try:
        from .campaign_reviewer import _SPAM_WORDS as SW, _EXCLAIM_RE, _ALL_CAPS_WORD
        spam_hits = SW.findall(full)
        excl = bool(_EXCLAIM_RE.search(full))
        caps = _ALL_CAPS_WORD.findall(full)
    except Exception:
        spam_hits = re.findall(
            r"\b(free!!!|act now|limited time|urgent|click here|buy now|guarantee|100%\s*free|winner|congratulations)\b",
            full,
            re.I,
        )
        excl = bool(re.search(r"!{2,}", full))
        caps = re.findall(r"\b[A-Z]{5,}\b", full)

    spam_penalty = 0
    if spam_hits:
        spam_penalty += min(12, 4 * len(set(x.lower() for x in spam_hits)))
        issues.append("Spam-prone wording detected")
        suggestions.append("Remove hype words (free, act now, limited time, guarantee)")
    if excl:
        spam_penalty += 4
        issues.append("Multiple exclamation marks")
        suggestions.append("Use at most one exclamation mark")
    if len(caps) >= 3:
        spam_penalty += 4
        issues.append("Too many ALL-CAPS words")
        suggestions.append("Avoid shouting in ALL CAPS")
    spam_points = max(0, 20 - spam_penalty)
    points += spam_points
    if spam_points >= 16:
        strengths.append("Low spam risk")
    spam_level = "low" if spam_penalty <= 4 else ("medium" if spam_penalty <= 10 else "high")

    # --- CTA (15) ---
    cta = bool(
        re.search(
            r"\b(reply|call|chat|meet|schedule|book|open to|would you|can we|15[- ]?min|quick call)\b",
            body,
            re.I,
        )
    )
    if cta:
        points += 15
        strengths.append("Clear soft CTA")
    else:
        issues.append("CTA is weak or missing")
        suggestions.append("End with one soft ask (e.g. open to a 15-minute chat?)")

    # --- Clarity / professionalism (10) ---
    if body and not re.search(r"<[^>]+>", body):
        points += 5
    if goal and any(w.lower() in body.lower() for w in re.findall(r"[A-Za-z]{4,}", goal)[:4]):
        points += 5
        strengths.append("Body aligns with campaign goal")
    else:
        points += 2
        suggestions.append("Tie one sentence clearly to the campaign goal")

    # --- Closing (10) for email ---
    if ch == "email":
        if re.search(r"\b(thanks|thank you|regards|best|looking forward)\b", body, re.I):
            points += 10
            strengths.append("Polite close")
        else:
            points += 3
            suggestions.append("Add a short professional sign-off")
    else:
        points += 10

    score = int(max(0, min(100, points)))
    grade = (
        "Excellent" if score >= 90 else
        "Good" if score >= 75 else
        "Needs Improvement" if score >= 60 else
        "Poor"
    )

    # Engagement estimates from score band (not fabricated extremes)
    if score >= 90:
        metrics = {"open_rate": "28-40%", "click_rate": "8-15%", "reply_rate": "8-14%"}
    elif score >= 75:
        metrics = {"open_rate": "22-32%", "click_rate": "5-10%", "reply_rate": "4-9%"}
    elif score >= 60:
        metrics = {"open_rate": "15-25%", "click_rate": "3-7%", "reply_rate": "2-5%"}
    else:
        metrics = {"open_rate": "8-15%", "click_rate": "1-4%", "reply_rate": "1-3%"}

    ch_score = score if ch == "email" else (score if ch in ("whatsapp", "sms") else 0)
    channel_reviews = {
        "email": {"score": score if ch == "email" else 0, "feedback": strengths[:3] if ch == "email" else ["Channel not scored"]},
        "whatsapp": {"score": score if ch == "whatsapp" else 0, "feedback": strengths[:3] if ch == "whatsapp" else ["Channel not scored"]},
        "sms": {"score": score if ch == "sms" else 0, "feedback": strengths[:3] if ch == "sms" else ["Channel not scored"]},
    }

    return {
        "campaign_score": score,
        "grade": grade,
        "summary": f"Production score {score}/100 based on personalization, spam risk, CTA, length, and clarity.",
        "estimated_metrics": metrics,
        "strengths": strengths,
        "issues": issues,
        "recommendations": suggestions,
        "improvement_suggestions": suggestions,
        "channel_reviews": channel_reviews,
        "spam_risk": {"level": spam_level, "reasons": [i for i in issues if "spam" in i.lower() or "CAPS" in i or "exclamation" in i.lower()]},
        "cta_review": "CTA present" if cta else "Add one soft CTA",
        "personalization_review": (
            "Name + company tokens present" if has_name and has_company
            else "Add {{Name}} and {{Company}}"
        ),
        "grammar_review": "Scored on structure and spam signals (not full grammar AI)",
        "consistency_review": "Single-channel draft score",
        "final_recommendation": (
            "Ready to send after a quick human pass" if score >= 90
            else "Apply the listed improvements or click Improve to 90+"
        ),
        "inbox_tips": suggestions[:4] or ["Keep one CTA", "Use personalization tokens"],
        "review_source": "production_rules",
        "score_breakdown": {
            "personalization": 20 if has_name and has_company else (12 if has_name or has_company else 0),
            "spam_safety": spam_points,
            "cta": 15 if cta else 0,
            "length_structure": min(25, points),
        },
    }


def improve_message(
    *,
    channel: str = "email",
    subject: str = "",
    body: str = "",
    goal: str = "",
    tone: str = "professional",
    current_score: int | None = None,
    issues: list | None = None,
    recommendations: list | None = None,
) -> dict[str, Any]:
    """Rewrite copy to satisfy the production checklist (score should rise)."""
    channel = (channel or "email").lower()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()

    checklist = [
        "Include Hi {{Name}}, and mention {{Company}} in the first paragraph",
        "Subject 8-55 chars, specific, no hype",
        "Body 50-110 words (email) / under 60 words (WhatsApp) / under 160 chars (SMS)",
        "One soft CTA with a question (e.g. open to a 15-minute chat?)",
        "No spam words: free, act now, limited time, guarantee, click here, !!!",
        "No ALL CAPS shouting",
        "Professional sign-off (Best regards / Thanks)",
        "One concrete benefit tied to the goal",
    ]

    if api_key:
        system = (
            "You are a B2B copy editor. Rewrite the message so it PASSES this checklist "
            "and will score 90+ on a rules-based outreach scorer. "
            "Return ONLY JSON: subject, body, changes_made (string array). "
            "You MUST include literal placeholders {{Name}} and {{Company}} in the body. "
            "Do not invent fake urgency or spam phrases."
        )
        user_payload = {
            "channel": channel,
            "goal": goal,
            "tone": tone,
            "current_score": current_score,
            "issues": issues or [],
            "recommendations": recommendations or [],
            "checklist": checklist,
            "subject": subject,
            "body": body,
        }
        parsed = _openai_json(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            api_key,
            base_url,
            temperature=0.35,
        )
        if parsed and (parsed.get("body") or parsed.get("subject")):
            subj = (parsed.get("subject") or subject or "") if channel == "email" else ""
            bod = parsed.get("body") or body or ""
            # Enforce tokens if model forgot them
            if channel == "email" and "{{Name}}" not in bod and "{{name}}" not in bod.lower():
                bod = "Hi {{Name}},\n\n" + bod.lstrip()
            if channel == "email" and "{{Company}}" not in bod and "{{company}}" not in bod.lower():
                bod = bod.replace("your team", "{{Company}}'s team", 1)
                if "{{Company}}" not in bod and "{{company}}" not in bod.lower():
                    bod = bod + "\n\nThis could help teams at {{Company}}."
            return {
                "channel": channel,
                "subject": subj,
                "body": bod,
                "source": "openai_improve",
                "changes_made": parsed.get("changes_made") or ["Rewrote to pass 90+ checklist"],
                "goal": goal,
                "tone": tone,
            }

    # Local deterministic improve (no API or API failed)
    bod = (body or "").strip()
    subj = (subject or "").strip()
    changes = []
    if channel == "email":
        if not subj or len(subj) < 8:
            subj = (goal or "Quick introduction")[:55]
            changes.append("Filled subject")
        if len(subj) > 55:
            subj = subj[:52] + "…"
            changes.append("Shortened subject")
        if not re.search(r"\{\{\s*name\s*\}\}", bod, re.I):
            bod = "Hi {{Name}},\n\n" + bod
            changes.append("Added {{Name}} greeting")
        if not re.search(r"\{\{\s*company\s*\}\}", bod, re.I):
            bod += "\n\nI thought this might be relevant for {{Company}}."
            changes.append("Added {{Company}} mention")
        if not re.search(r"\b(reply|chat|call|open to|15[- ]?min)\b", bod, re.I):
            bod += "\n\nWould you be open to a brief 15-minute chat next week?"
            changes.append("Added soft CTA")
        if not re.search(r"\b(regards|thanks|best|looking forward)\b", bod, re.I):
            bod += "\n\nBest regards"
            changes.append("Added sign-off")
        # strip spammy bits
        for w in ("!!!", "ACT NOW", "LIMITED TIME", "CLICK HERE"):
            if w in bod or w in subj:
                bod = bod.replace(w, "")
                subj = subj.replace(w, "")
                changes.append(f"Removed {w}")
    else:
        if not re.search(r"\{\{\s*name\s*\}\}", bod, re.I):
            bod = "Hi {{Name}}, " + bod
            changes.append("Added {{Name}}")
        if len(bod) > 160 and channel == "sms":
            bod = bod[:157] + "..."
            changes.append("Trimmed SMS length")

    return {
        "channel": channel,
        "subject": subj if channel == "email" else "",
        "body": bod,
        "source": "rules_improve",
        "changes_made": changes or ["Applied local checklist fixes"],
        "goal": goal,
        "tone": tone,
    }


def score_generated_content(
    *,
    channel: str,
    subject: str,
    body: str,
    email_enabled: bool = False,
    whatsapp_enabled: bool = False,
    sms_enabled: bool = False,
    goal: str = "",
) -> dict:
    """Production score: rules first (stable), optional AI note does not override checklist."""
    ch = (channel or "email").lower()
    rules = score_copy_rules(channel=ch, subject=subject, body=body, goal=goal)

    # Optional AI commentary — never replace the numeric rules score (keeps Improve→score honest)
    try:
        ai = ai_review_campaign(
            name="AI draft",
            description="Generated message score",
            goal=goal or "",
            email_enabled=ch == "email",
            whatsapp_enabled=ch == "whatsapp",
            sms_enabled=ch == "sms",
            email_subject=subject if ch == "email" else "",
            email_body=body if ch == "email" else "",
            whatsapp_body=body if ch == "whatsapp" else "",
            sms_body=body if ch == "sms" else "",
        )
    except Exception:
        ai = None

    if ai and isinstance(ai, dict):
        # Keep rules score; merge qualitative tips
        for key in ("summary", "strengths"):
            if ai.get(key) and key == "strengths":
                merged = list(rules.get("strengths") or [])
                for s in ai.get("strengths") or []:
                    if s not in merged:
                        merged.append(s)
                rules["strengths"] = merged[:8]
        # Prefer rules suggestions; append unique AI recommendations
        tips = list(rules.get("improvement_suggestions") or [])
        for r in (ai.get("recommendations") or ai.get("improvement_suggestions") or []):
            if r not in tips:
                tips.append(r)
        rules["improvement_suggestions"] = tips[:8]
        rules["recommendations"] = tips[:8]
        rules["review_source"] = "production_rules+ai_tips"
    print(f"[ai_content] production score={rules.get('campaign_score')} grade={rules.get('grade')}")
    return rules




def ensure_score_90(
    *,
    channel: str,
    subject: str,
    body: str,
    goal: str = "",
    tone: str = "professional",
    max_passes: int = 2,
) -> tuple[dict, dict]:
    """Generate path: score, and auto-improve until >= 90 or passes exhausted.

    Returns (draft_dict, score_dict).
    """
    ch = (channel or "email").lower()
    draft = {
        "channel": ch,
        "subject": subject or "",
        "body": body or "",
        "goal": goal,
        "tone": tone,
        "source": "ensure_90",
    }
    score = score_generated_content(
        channel=ch,
        subject=draft["subject"],
        body=draft["body"],
        email_enabled=ch == "email",
        whatsapp_enabled=ch == "whatsapp",
        sms_enabled=ch == "sms",
        goal=goal,
    )
    passes = 0
    while int(score.get("campaign_score") or 0) < 90 and passes < max_passes:
        passes += 1
        improved = improve_message(
            channel=ch,
            subject=draft["subject"],
            body=draft["body"],
            goal=goal,
            tone=tone,
            current_score=int(score.get("campaign_score") or 0),
            issues=list(score.get("issues") or []),
            recommendations=list(score.get("improvement_suggestions") or score.get("recommendations") or []),
        )
        draft["subject"] = improved.get("subject") or draft["subject"]
        draft["body"] = improved.get("body") or draft["body"]
        draft["source"] = improved.get("source") or draft["source"]
        draft["changes_made"] = improved.get("changes_made") or []
        score = score_generated_content(
            channel=ch,
            subject=draft["subject"],
            body=draft["body"],
            email_enabled=ch == "email",
            whatsapp_enabled=ch == "whatsapp",
            sms_enabled=ch == "sms",
            goal=goal,
        )
        print(f"[ai_content] ensure_90 pass={passes} score={score.get('campaign_score')}")

    # Final local enforce if still < 90
    if int(score.get("campaign_score") or 0) < 90:
        improved = improve_message(
            channel=ch,
            subject=draft["subject"],
            body=draft["body"],
            goal=goal,
            tone=tone,
            current_score=int(score.get("campaign_score") or 0),
            issues=list(score.get("issues") or []),
            recommendations=list(score.get("improvement_suggestions") or []),
        )
        draft["subject"] = improved.get("subject") or draft["subject"]
        draft["body"] = improved.get("body") or draft["body"]
        score = score_generated_content(
            channel=ch,
            subject=draft["subject"],
            body=draft["body"],
            email_enabled=ch == "email",
            whatsapp_enabled=ch == "whatsapp",
            sms_enabled=ch == "sms",
            goal=goal,
        )
    draft["inbox_tips"] = list(score.get("inbox_tips") or [])
    return draft, score


