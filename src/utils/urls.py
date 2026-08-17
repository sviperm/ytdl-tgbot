"""URL helpers."""

import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

# Query params that are pure tracking; stripped from source links in captions.
_TRACKING_PARAMS = {
    "igsh", "igshid", "img_index", "si", "feature",
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
}

_URL_RE = re.compile(r"https?://[^\s<>\"'`|\\]+", re.I)
# Punctuation that ends a sentence or a markdown wrapper, not a URL.
_TRAILING = ".,;:!?*_~\"'»)]}"
_CLOSERS = {")": "(", "]": "[", "}": "{"}


def is_http_url(url):
    """Guard before anything is handed to a platform: only http(s) links qualify."""
    return isinstance(url, str) and url.startswith(("http://", "https://"))


def _trim(url):
    while url and url[-1] in _TRAILING:
        opener = _CLOSERS.get(url[-1])
        # A bracket with an opener is part of the URL, without one it is markdown's.
        if opener and url.count(url[-1]) <= url.count(opener):
            break
        url = url[:-1]
    return url


def extract_urls(text, extra=None):
    """Every http(s) link in a message, in order, deduplicated.

    ``extra`` carries links that are not in the text at all (hidden hyperlinks).
    """
    found = [_trim(m.group()) for m in _URL_RE.finditer(text or "")]
    found += [u for u in (extra or []) if is_http_url(u)]
    seen, urls = set(), []
    for url in found:
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def clean_url(url):
    """Drop tracking query params (igsh, img_index, utm_*, ...) from a URL."""
    parts = urlsplit(url)
    kept = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))
