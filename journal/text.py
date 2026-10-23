"""Markdown rendering and small formatting helpers."""
from datetime import datetime, timezone

from markdown_it import MarkdownIt
from markupsafe import Markup

# Raw HTML in Markdown is shown as text, never run. Single line breaks are kept, like Discord.
_md = MarkdownIt("commonmark", {"html": False, "breaks": True, "linkify": False}).enable(
    ["strikethrough", "table"]
)


def render_markdown(text):
    if not text:
        return Markup("")
    return Markup(_md.render(text))


def fmt_num(value):
    """22.0 -> '22', 22.5 -> '22.5'."""
    if value is None:
        return ""
    value = float(value)
    return str(int(value)) if value.is_integer() else f"{value:g}"


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value):
    """Accept the exact stored format and return it, or None if it doesn't match."""
    if not isinstance(value, str) or len(value) != 20:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
    # Round-trip so single-digit months etc. can't slip through
    return value if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") == value else None
