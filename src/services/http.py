"""curl_cffi HTTP client with browser impersonation and optional proxy.

Injected into InstagramClient so tests can fake it (no network).
"""

import os

from curl_cffi import requests as cffi_requests

from src.config import Config


class HttpClient:
    def __init__(self, proxy=None):
        # None (not "") means "take whatever is configured" — src.container builds
        # this with no arguments, so the Config default is the production path.
        self._proxy = proxy if proxy is not None else Config.IG_PROXY_URL

    @property
    def has_proxy(self):
        """Whether requests go through a proxy (callers branch on this instead of
        reaching into the proxy dict)."""
        return bool(self._proxy)

    def _proxies(self):
        return {"http": self._proxy, "https": self._proxy} if self._proxy else None

    def get(self, url, headers=None, allow_redirects=True, timeout=25):
        return cffi_requests.get(
            url, headers=headers, impersonate="chrome", timeout=timeout,
            allow_redirects=allow_redirects, proxies=self._proxies(),
        )

    def post(self, url, data=None, headers=None, timeout=25):
        return cffi_requests.post(
            url, data=data, headers=headers, impersonate="chrome",
            timeout=timeout, proxies=self._proxies(),
        )

    def download(self, url, dest, headers=None, timeout=120, on_progress=None):
        """Stream `url` into `dest`, calling on_progress(downloaded, total) per chunk.

        Streaming rather than buffering matters: a 300MB video would otherwise sit
        in RSS in full before the first byte hits disk. `total` is 0 when the server
        sends no Content-Length.
        """
        try:
            # An explicit Session: the module-level helpers close their session on
            # return, which would kill the body before it can be iterated.
            with cffi_requests.Session() as session:
                r = session.get(
                    url, headers=headers, impersonate="chrome", timeout=timeout,
                    proxies=self._proxies(), stream=True,
                )
                r.raise_for_status()
                total = _content_length(r)
                downloaded = 0
                with open(dest, "wb") as f:
                    for chunk in r.iter_content():
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        if on_progress:
                            on_progress(downloaded, total)
        except BaseException:
            # Never leave a truncated file behind: the caller (and the cache) would
            # happily treat it as a complete download.
            if os.path.exists(dest):
                try:
                    os.remove(dest)
                except OSError:
                    pass
            raise
        return dest


def _content_length(response):
    try:
        return int((response.headers or {}).get("Content-Length") or 0)
    except (TypeError, ValueError):
        return 0
