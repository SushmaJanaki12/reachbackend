"""Domain-typo heuristic shared by checks.py (flags the issue) and fixes.py
(the AI-enrichment fallback for cases this misses). Kept separate from both
to avoid a circular import between them.
"""
TYPO_DOMAINS = {
    "gmial.com": "gmail.com", "gmai.com": "gmail.com", "gnail.com": "gmail.com",
    "gmail.co": "gmail.com", "gamil.com": "gmail.com", "gmali.com": "gmail.com",
    "yahooo.com": "yahoo.com", "yaho.com": "yahoo.com", "yahho.com": "yahoo.com",
    "hotmial.com": "hotmail.com", "hotmal.com": "hotmail.com", "hotmai.com": "hotmail.com",
    "outlok.com": "outlook.com", "outllook.com": "outlook.com", "outlook.co": "outlook.com",
    "iclould.com": "icloud.com", "icoud.com": "icloud.com",
}
MAJOR_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "aol.com"]


def _edit_distance_1(a: str, b: str) -> bool:
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    return any(longer[:i] + longer[i + 1:] == shorter for i in range(len(longer)))


def detect_typo(email: str) -> str | None:
    if "@" not in email:
        return None
    local, domain = email.rsplit("@", 1)
    domain = domain.lower()
    if domain in TYPO_DOMAINS:
        return f"{local}@{TYPO_DOMAINS[domain]}"
    for major in MAJOR_DOMAINS:
        if domain != major and _edit_distance_1(domain, major):
            return f"{local}@{major}"
    return None
