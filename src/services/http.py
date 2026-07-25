"""curl_cffi HTTP client with browser impersonation and optional proxy.

Injected into InstagramClient so tests can fake it (no network).
"""

import os

from curl_cffi import requests as cffi_requests


class HttpClient:
    def __init__(self, proxy=None):
        self._proxy = proxy

    def _proxies(self):
        proxy = self._proxy or os.getenv("IG_PROXY_URL", "").strip()
        return {"http": proxy, "https": proxy} if proxy else None

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

    def download(self, url, dest, headers=None, timeout=120):
        r = self.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        with open(dest, "wb") as f:
            f.write(r.content)
        return dest
