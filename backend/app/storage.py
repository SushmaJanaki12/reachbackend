"""Local public file storage for uploaded images (project logos, etc).

Files are written under UPLOAD_DIR, which app.main mounts at /uploads, and
the URL handed back is built from settings.public_base_url -- the same host
Gmail/Outlook's image proxies fetch from, not whatever origin the browser
happens to be on. In non-local environments PUBLIC_BASE_URL must be set to
the real public hostname or these URLs will be unreachable from recipients'
mail clients (see config.py).
"""
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from .config import settings

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_ALLOWED_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
_MAX_IMAGE_BYTES = 5 * 1024 * 1024


async def save_image_upload(file: UploadFile) -> str:
    """Persist an uploaded image and return its publicly reachable URL."""
    ext = _ALLOWED_IMAGE_TYPES.get((file.content_type or "").lower())
    if not ext:
        raise HTTPException(status_code=400, detail="Unsupported image type — use PNG, JPEG, GIF or WEBP")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(data) > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Image too large (max 5MB)")

    filename = f"{uuid.uuid4().hex}{ext}"
    (UPLOAD_DIR / filename).write_bytes(data)
    return f"{settings.public_base_url.rstrip('/')}/uploads/{filename}"


def delete_upload_if_local(url: str | None) -> None:
    """Best-effort cleanup of a file this app previously wrote, when replaced."""
    prefix = f"{settings.public_base_url.rstrip('/')}/uploads/"
    if not url or not url.startswith(prefix):
        return
    filename = url[len(prefix):]
    if not filename or "/" in filename:
        return
    path = UPLOAD_DIR / filename
    if path.is_file():
        path.unlink(missing_ok=True)


# ---- campaign email attachments ----
# Product decision, not just an engineering default -- confirm with whoever
# owns the PRD before shipping. 10MB is generous for real use, well under
# most SMTP providers' caps (20-25MB), but far above Graph's own direct-send
# limit (see GRAPH_MAX_TOTAL_ATTACHMENT_BYTES in app/mailer.py) -- a campaign
# whose send resolves to Graph can still get rejected there even though it
# passed this cap. Enforced once here, at upload time, rather than per-tier,
# since the resolver doesn't know in advance which tier a given send will use.
MAX_CAMPAIGN_ATTACHMENTS_BYTES = 10 * 1024 * 1024

# Standard-practice blocklist for outbound bulk email attachments. Mirrors no
# existing allow/deny-list in this app (recipient dataset import only checks
# .csv/.xlsx by extension) -- this is a new list, kept narrow to common
# executable/script types rather than trying to enumerate everything.
BLOCKED_ATTACHMENT_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".com", ".js", ".vbs", ".vbe", ".ws", ".wsf",
    ".scr", ".msi", ".msp", ".jar", ".sh", ".ps1", ".psm1", ".pif", ".lnk",
}


async def save_campaign_attachment(file: UploadFile, existing_total_bytes: int) -> tuple[str, int, str]:
    """Persist an uploaded campaign attachment. Returns (storage_path,
    size_bytes, content_type). Raises HTTPException for a disallowed
    extension or a total size (existing + this file) over the cap -- both
    checked before anything is written to disk."""
    filename = file.filename or "attachment"
    ext = Path(filename).suffix.lower()
    if ext in BLOCKED_ATTACHMENT_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Attachments of type {ext} are not allowed")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if existing_total_bytes + len(data) > MAX_CAMPAIGN_ATTACHMENTS_BYTES:
        cap_mb = MAX_CAMPAIGN_ATTACHMENTS_BYTES // (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"Attachments exceed the {cap_mb}MB total limit per campaign")

    storage_path = f"{uuid.uuid4().hex}{ext}"
    (UPLOAD_DIR / storage_path).write_bytes(data)
    content_type = file.content_type or "application/octet-stream"
    return storage_path, len(data), content_type


def read_campaign_attachment(storage_path: str) -> bytes:
    return (UPLOAD_DIR / storage_path).read_bytes()


def duplicate_campaign_attachment(storage_path: str) -> tuple[str, int]:
    """Copies an existing attachment file under a new name, for campaign
    duplication (POST /campaigns/{id}/duplicate). The clone must not share a
    storage_path with its source -- deleting either campaign's attachment
    would otherwise delete the file out from under the other. Returns
    (new_storage_path, size_bytes)."""
    data = (UPLOAD_DIR / storage_path).read_bytes()
    new_path = f"{uuid.uuid4().hex}{Path(storage_path).suffix}"
    (UPLOAD_DIR / new_path).write_bytes(data)
    return new_path, len(data)


def delete_campaign_attachment(storage_path: str) -> None:
    path = UPLOAD_DIR / storage_path
    if path.is_file():
        path.unlink(missing_ok=True)
