import re

PLACEHOLDER = re.compile(r"\{\{\s*([\w ]+?)\s*\}\}")


def render_template(template: str, data: dict, missing: list | None = None) -> str:
    """Substitute {{Key}} placeholders (case-insensitive) from data.

    If `missing` is passed, unresolved placeholders are blanked out (rather than
    left as literal `{{Key}}` text) and their names are appended to `missing` --
    used on the send path so a stray/unknown placeholder never reaches the
    recipient. Without `missing`, unresolved placeholders are left untouched,
    which is friendlier while an admin is still drafting content.
    """
    def repl(m):
        key = m.group(1).strip()
        for k, v in data.items():
            if k.lower() == key.lower():
                return str(v)
        if missing is not None:
            missing.append(key)
            return ""
        return m.group(0)
    return PLACEHOLDER.sub(repl, template or "")


def valid_email(e: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", e or ""))


def valid_mobile(m: str) -> bool:
    digits = re.sub(r"\D", "", m or "")
    return len(digits) >= 8
