"""Pure content-transform helpers for real engagement tracking (P1.1/P1.2)
and the unsubscribe footer (P1.8): building the open-tracking pixel,
click-redirect and unsubscribe URLs, and rewriting a message's rendered
content to use them. No DB/HTTP here -- see app/routers/tracking_pixel.py
and app/routers/unsubscribe.py for the routes these URLs point at, and
app/worker.py for where these are applied on the send path.
"""
import html as _html
import re
import struct
import urllib.parse
import zlib

from .config import settings

URL_RE = re.compile(r'https?://[^\s<>"]+')

# Trailing characters trimmed off a matched URL before it's treated as the
# real link -- otherwise "...see https://example.com/promo." captures the
# sentence-ending period as part of the URL, breaking the click redirect.
_TRAILING_PUNCT = ".,;:!?)]}'\""


def _split_trailing_punct(raw: str) -> tuple[str, str]:
    end = len(raw)
    while end > 0 and raw[end - 1] in _TRAILING_PUNCT:
        end -= 1
    return raw[:end], raw[end:]


def _png_chunk(ctype: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", zlib.crc32(ctype + data))


def _make_transparent_pixel_png() -> bytes:
    """Built rather than hand-copied as a literal -- a single wrong hex digit
    in a copied PNG byte string is easy to miss and hard to spot-check."""
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)  # 1x1, 8-bit RGBA
    raw = b"\x00" + b"\x00\x00\x00\x00"  # filter byte 0 + fully-transparent RGBA pixel
    idat = zlib.compress(raw, 9)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


# 1x1 transparent PNG, served with no-cache headers by the open-tracking route.
TRANSPARENT_PIXEL_PNG = _make_transparent_pixel_png()


def _base_url() -> str:
    return settings.public_base_url.rstrip("/")


def open_pixel_url(token: str) -> str:
    return f"{_base_url()}/track/open/{token}.png"


def click_url(token: str, original_url: str) -> str:
    return f"{_base_url()}/track/click/{token}?url={urllib.parse.quote(original_url, safe='')}"


def unsubscribe_url(token: str) -> str:
    # Reuses the same per-message tracking_token as the open pixel and click
    # redirects above -- already unguessable (secrets.token_urlsafe) and
    # unique per Message row, so it doubles as the unsubscribe token without
    # a second, parallel signing scheme (see app/routers/unsubscribe.py).
    return f"{_base_url()}/unsubscribe?token={token}"


def extract_urls(text: str) -> set[str]:
    """Every http(s) URL appearing in `text` -- used both to know what to
    rewrite at send time and, on the click-redirect route, to recompute the
    same set as an allowlist for the requested destination."""
    return {_split_trailing_punct(m)[0] for m in URL_RE.findall(text or "")}


def rewrite_links_plain(text: str, token: str) -> str:
    """SMS/WhatsApp path: bare URLs replaced in place with the click-redirect
    URL text itself (no markup available in plain-text content)."""
    def repl(m):
        url, trailing = _split_trailing_punct(m.group(0))
        return click_url(token, url) + trailing
    return URL_RE.sub(repl, text or "")


def to_html_with_tracking(body_text: str, token: str) -> str:
    """Plain-text campaign body -> HTML for the real email send path:
    escapes the text, keeps line breaks, turns bare URLs into clickable
    click-redirect anchors (rather than leaving them as escaped text and
    relying on the mail client's own auto-linkification), appends an
    unsubscribe footer (P1.8 -- CAN-SPAM/GDPR require one on every
    commercial email), and appends the 1x1 open-tracking pixel.
    """
    text = body_text or ""
    parts: list[str] = []
    last = 0
    for m in URL_RE.finditer(text):
        parts.append(_html.escape(text[last:m.start()]))
        url, trailing = _split_trailing_punct(m.group(0))
        href = _html.escape(click_url(token, url), quote=True)
        parts.append(f'<a href="{href}">{_html.escape(url)}</a>{_html.escape(trailing)}')
        last = m.end()
    parts.append(_html.escape(text[last:]))
    html_body = "".join(parts).replace("\n", "<br>")
    unsub = _html.escape(unsubscribe_url(token), quote=True)
    footer = (
        '<p style="margin-top:24px;font-size:11px;color:#888888;">'
        f'<a href="{unsub}" style="color:#888888;">Unsubscribe</a> from future emails.</p>'
    )
    pixel = _html.escape(open_pixel_url(token), quote=True)
    return f'{html_body}{footer}<img src="{pixel}" width="1" height="1" alt="" style="display:none">'
