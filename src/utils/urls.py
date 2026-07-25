"""URL helpers."""

from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

# Query params that are pure tracking; stripped from source links in captions.
_TRACKING_PARAMS = {
    "igsh", "igshid", "img_index", "si", "feature",
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
}


def is_http_url(url):
    """Guard before anything is handed to a platform: only http(s) links qualify."""
    return isinstance(url, str) and url.startswith(("http://", "https://"))


def clean_url(url):
    """Drop tracking query params (igsh, img_index, utm_*, ...) from a URL."""
    parts = urlsplit(url)
    kept = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))
