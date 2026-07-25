"""Telegram HTML caption builders."""

import html

from src.utils.urls import clean_url

# Telegram caption limit is 1024 chars; keep the post body well under it.
_MAX_BODY = 900


def _source_link(url, text):
    """Anchor back to the source, with tracking params stripped from the href."""
    return f'<a href="{html.escape(clean_url(url), quote=True)}">{html.escape(text)}</a>'


def build_caption(title, url):
    """Caption with the title as a clickable link back to the source video."""
    return _source_link(url, title or "Video")


def build_ig_caption(caption_text, url):
    """Media-group caption: the post's text, then a source link below it."""
    link = _source_link(url, "Instagram")
    if not caption_text:
        return link
    body = caption_text[:_MAX_BODY].rstrip()
    if len(caption_text) > _MAX_BODY:
        body += "…"
    return f"{html.escape(body)}\n\n{link}"
