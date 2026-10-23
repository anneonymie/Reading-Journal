"""Storing uploaded images as plain files named by their content hash."""
import hashlib
import io
import os
from pathlib import Path

from PIL import Image, UnidentifiedImageError

# Pillow format name -> (mime type, file extension)
ALLOWED = {
    "PNG": ("image/png", "png"),
    "JPEG": ("image/jpeg", "jpg"),
    "GIF": ("image/gif", "gif"),
    "WEBP": ("image/webp", "webp"),
}
MAX_BYTES = 30 * 1024 * 1024


class ImageError(ValueError):
    pass


def store_image(conn, data_dir, upload):
    """Save an uploaded file and return its image id, or None if no file was given.

    The same file uploaded twice is stored once and returns the existing id.
    """
    if upload is None or not upload.filename:
        return None
    raw = upload.read(MAX_BYTES + 1)
    if not raw:
        return None
    name = upload.filename
    if len(raw) > MAX_BYTES:
        raise ImageError(f"{name} is larger than 30 MB.")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(raw)) as img:
            fmt = img.format
            width, height = img.size
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError):
        raise ImageError(f"{name} isn't an image the journal can read. Use PNG, JPEG, GIF or WebP.")
    if fmt not in ALLOWED:
        raise ImageError(f"{name} is a {fmt} image. Use PNG, JPEG, GIF or WebP.")

    sha = hashlib.sha256(raw).hexdigest()
    row = conn.execute("SELECT id FROM image WHERE sha256 = ?", (sha,)).fetchone()
    if row:
        return row["id"]

    mime, ext = ALLOWED[fmt]
    rel = f"images/{sha[:2]}/{sha}.{ext}"
    path = Path(data_dir) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(raw)
        os.replace(tmp, path)
    cur = conn.execute(
        "INSERT INTO image(file_path, sha256, mime_type, width, height, original_name) VALUES (?,?,?,?,?,?)",
        (rel, sha, mime, width, height, name[:200]),
    )
    return cur.lastrowid
