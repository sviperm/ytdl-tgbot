"""No-login Instagram post fetching.

Instagram now blocks anonymous access via yt-dlp/gallery-dl. This module fetches
public posts (single or carousel, photos + videos) *without* cookies or an account:

1. Primary: the internal `api/v1/media/<pk>/info` endpoint with the public web
   `X-IG-App-ID`. Returns full media (video_versions, carousel_media) + caption.
   This typically works from residential IPs; datacenter IPs may get redirected
   to the login page (302), in which case we fall back to (2).
2. Fallback: the public `embed/captioned` page, which exposes images + caption
   without login but NOT video URLs.

Returns a dict: {"shortcode": str, "caption": str, "media": [{"type", "url"}]}.
"""

import os
import re
import json
import asyncio

from curl_cffi import requests as cffi_requests

from src.utils.logger import logger

_IG_URL_RE = re.compile(r'https?://(?:www\.)?instagram\.com/', re.I)
_SHORTCODE_RE = re.compile(
    r'instagram\.com/(?:[^/]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)', re.I
)
_APP_ID = "936619743392459"  # public Instagram web app id (not account-specific)
_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
_MOBILE_UA = ("Instagram 273.0.0.16.70 (iPhone15,2; iOS 17_5_1; en_US; en-US; "
              "scale=3.00; 1290x2796; 470085518)")
# GraphQL doc_ids change over time; override via env without a code change.
_GQL_MOBILE_DOC_ID = os.getenv("IG_MOBILE_DOC_ID", "8845758582119845")
_GQL_WEB_DOC_ID = os.getenv("IG_WEB_DOC_ID", "25531498899829322")
_GQL_URL = "https://www.instagram.com/graphql/query/"

# Public "embed fixer" service (InstaFix-based). When the server IP is blocked by
# Instagram, it serves the media from its own (unblocked) infrastructure. Only
# reached with a crawler User-Agent. Hosts are env-overridable (they rebrand).
_BOT_UA = "TelegramBot (like TwitterBot)"
_FIXER_URL = os.getenv("IG_FIXER_URL", "https://www.instagram7.com").rstrip("/")
_OFFLOAD_BASE = os.getenv("IG_OFFLOAD_BASE", "https://oginstagram.com/offload").rstrip("/")


def _proxies():
    """Optional proxy for IG requests (helps when the server IP is flagged)."""
    p = os.getenv("IG_PROXY_URL", "").strip()
    return {"http": p, "https": p} if p else None


def is_instagram_url(url):
    return bool(url and _IG_URL_RE.match(url))


def extract_shortcode(url):
    m = _SHORTCODE_RE.search(url or "")
    return m.group(1) if m else None


def _shortcode_to_pk(code):
    """Instagram shortcodes are base64 of the media pk (first 11 chars)."""
    pk = 0
    for ch in code[:11]:
        if ch not in _B64:
            break
        pk = pk * 64 + _B64.index(ch)
    return pk


def _api_headers(shortcode):
    return {
        "User-Agent": _UA,
        "X-IG-App-ID": _APP_ID,
        "X-ASBD-ID": "129477",
        "X-IG-WWW-Claim": "0",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"https://www.instagram.com/p/{shortcode}/",
        "Origin": "https://www.instagram.com",
    }


def _media_from_api_node(node):
    if node.get("video_versions"):
        return {"type": "video", "url": node["video_versions"][0]["url"]}
    candidates = (node.get("image_versions2") or {}).get("candidates") or []
    if candidates:
        return {"type": "image", "url": candidates[0]["url"]}
    return None


def _parse_gql_media(sm):
    """Extract caption + media from a GraphQL/embed `shortcode_media` node."""
    caption = ""
    try:
        caption = sm["edge_media_to_caption"]["edges"][0]["node"]["text"]
    except Exception:
        pass
    media = []
    sidecar = sm.get("edge_sidecar_to_children")
    nodes = [e["node"] for e in sidecar["edges"]] if sidecar else [sm]
    for n in nodes:
        if n.get("is_video") and n.get("video_url"):
            media.append({"type": "video", "url": n["video_url"]})
        elif n.get("display_url"):
            media.append({"type": "image", "url": n["display_url"]})
    return {"caption": caption, "media": media}


def _gql_post(data, headers, label):
    r = cffi_requests.post(
        _GQL_URL, data=data, headers=headers, impersonate="chrome",
        timeout=25, proxies=_proxies(),
    )
    if r.status_code != 200:
        logger.info(f"Instagram {label} -> {r.status_code}")
        return None
    try:
        payload = r.json()
    except Exception:
        return None
    sm = (payload.get("data") or {}).get("xdt_shortcode_media") \
        or (payload.get("data") or {}).get("shortcode_media")
    if not sm:
        logger.info(f"Instagram {label}: no shortcode_media ({str(payload.get('errors'))[:80]})")
        return None
    return _parse_gql_media(sm)


def _fetch_via_gql_mobile(shortcode):
    data = {
        "variables": json.dumps({"shortcode": shortcode}),
        "doc_id": _GQL_MOBILE_DOC_ID,
        "server_timestamps": "true",
    }
    headers = {
        "User-Agent": _MOBILE_UA,
        "X-IG-App-ID": _APP_ID,
        "X-ASBD-ID": "129477",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"https://www.instagram.com/p/{shortcode}/",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    return _gql_post(data, headers, "mobile GraphQL")


def _fetch_via_gql_web(shortcode):
    data = {
        "av": "0", "__d": "www", "__user": "0", "__a": "1", "__comet_req": "7",
        "fb_api_caller_class": "RelayModern",
        "fb_api_req_friendly_name": "PolarisPostActionLoadPostQueryQuery",
        "variables": json.dumps({
            "shortcode": shortcode, "fetch_tagged_user_count": None,
            "hoisted_comment_id": None, "hoisted_reply_id": None,
        }),
        "server_timestamps": "true",
        "doc_id": _GQL_WEB_DOC_ID,
    }
    headers = {
        "User-Agent": _UA,
        "X-IG-App-ID": _APP_ID,
        "X-ASBD-ID": "129477",
        "X-FB-Friendly-Name": "PolarisPostActionLoadPostQueryQuery",
        "Origin": "https://www.instagram.com",
        "Referer": f"https://www.instagram.com/p/{shortcode}/",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    return _gql_post(data, headers, "web GraphQL")


def _fetch_via_api(shortcode):
    pk = _shortcode_to_pk(shortcode)
    url = f"https://www.instagram.com/api/v1/media/{pk}/info/"
    r = cffi_requests.get(
        url, headers=_api_headers(shortcode), impersonate="chrome",
        timeout=25, allow_redirects=False, proxies=_proxies(),
    )
    if r.status_code != 200:
        logger.info(
            f"Instagram api/v1 -> {r.status_code} for {shortcode} "
            f"(likely login-gated from this IP); falling back to embed"
        )
        return None
    items = r.json().get("items") or []
    if not items:
        return None
    item = items[0]
    caption = ((item.get("caption") or {}).get("text") or "")
    media = []
    if item.get("carousel_media"):
        for node in item["carousel_media"]:
            mm = _media_from_api_node(node)
            if mm:
                media.append(mm)
    else:
        mm = _media_from_api_node(item)
        if mm:
            media.append(mm)
    return {"caption": caption, "media": media}


def _embed_shortcode_media(shortcode):
    """Return the raw `shortcode_media` dict from the public embed page (works
    from most IPs). Gives caption + carousel structure, but NOT video URLs."""
    url = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
    r = cffi_requests.get(url, headers={"User-Agent": _UA}, impersonate="chrome",
                          timeout=25, proxies=_proxies())
    if r.status_code != 200:
        return None
    m = re.search(r'"contextJSON":"((?:[^"\\]|\\.)*)"', r.text)
    if not m:
        return None
    try:
        return json.loads(json.loads('"' + m.group(1) + '"'))["gql_data"]["shortcode_media"]
    except Exception:
        return None


def _fetch_via_embed(shortcode):
    """Embed only: images + caption (video items skipped — no anonymous URL)."""
    sm = _embed_shortcode_media(shortcode)
    return _parse_gql_media(sm) if sm else None


def _prime_fixer(shortcode):
    """Hit the fixer page (crawler UA) so it scrapes and caches the media."""
    try:
        cffi_requests.get(f"{_FIXER_URL}/p/{shortcode}/", headers={"User-Agent": _BOT_UA},
                          impersonate="chrome", timeout=20)
    except Exception as e:
        logger.warning(f"Instagram fixer prime failed for {shortcode}: {e}")


def _fixer_meta(html, prop):
    m = re.search(
        r'<meta[^>]+(?:property|name)="' + re.escape(prop) + r'"[^>]+content="([^"]*)"',
        html,
    )
    return m.group(1) if m else ""


def _fetch_via_fixer_single(shortcode):
    """Fallback: fixer page gives one item (og:video/og:image) + author title."""
    try:
        r = cffi_requests.get(f"{_FIXER_URL}/p/{shortcode}/", headers={"User-Agent": _BOT_UA},
                              impersonate="chrome", timeout=20)
    except Exception as e:
        logger.warning(f"Instagram fixer single fetch failed for {shortcode}: {e}")
        return None
    if r.status_code != 200:
        return None
    video = _fixer_meta(r.text, "og:video")
    image = _fixer_meta(r.text, "og:image").split("?")[0]  # drop ?thumbnail=1
    title = _fixer_meta(r.text, "og:title")
    if video:
        return {"caption": title, "media": [{"type": "video", "url": video}]}
    if image:
        return {"caption": title, "media": [{"type": "image", "url": image}]}
    return None


def _fetch_via_fixer(shortcode):
    """Structure + caption from the embed page (our IP); video bytes from the
    fixer's offload host (its unblocked IP). Photos come straight from the CDN."""
    sm = _embed_shortcode_media(shortcode)
    if not sm:
        return _fetch_via_fixer_single(shortcode)
    caption = ""
    try:
        caption = sm["edge_media_to_caption"]["edges"][0]["node"]["text"]
    except Exception:
        pass
    sidecar = sm.get("edge_sidecar_to_children")
    nodes = [e["node"] for e in sidecar["edges"]] if sidecar else [sm]
    if any(n.get("is_video") for n in nodes):
        _prime_fixer(shortcode)
    media = []
    for i, n in enumerate(nodes, start=1):
        if n.get("is_video"):
            media.append({"type": "video", "url": f"{_OFFLOAD_BASE}/{shortcode}/{i}"})
        elif n.get("display_url"):
            media.append({"type": "image", "url": n["display_url"]})
    if not media:
        return _fetch_via_fixer_single(shortcode)
    return {"caption": caption, "media": media}


def _fetch(url):
    shortcode = extract_shortcode(url)
    if not shortcode:
        logger.warning(f"Could not extract Instagram shortcode from {url}")
        return None

    # Try methods in order; first one returning media wins.
    # Direct Instagram endpoints (GraphQL/api) only work from an unblocked IP, so
    # they're attempted first ONLY when a proxy is configured (otherwise they just
    # spam Instagram and worsen the IP block). The default path is the "fixer"
    # (embed for structure/caption + offload host for video bytes), which works
    # even when the server IP is blocked. `embed` alone is the final fallback.
    methods = []
    if _proxies():
        methods += [
            ("mobile GraphQL", _fetch_via_gql_mobile),
            ("web GraphQL", _fetch_via_gql_web),
            ("api/v1", _fetch_via_api),
        ]
    methods += [
        ("fixer", _fetch_via_fixer),
        ("embed", _fetch_via_embed),
    ]
    for label, fn in methods:
        try:
            result = fn(shortcode)
        except Exception as e:
            logger.warning(f"Instagram {label} failed for {shortcode}: {e}")
            continue
        if result and result.get("media"):
            logger.info(f"Instagram {shortcode}: fetched via {label} ({len(result['media'])} item(s))")
            result["shortcode"] = shortcode
            return result
    return None


async def fetch(url):
    return await asyncio.to_thread(_fetch, url)


def _download_file(url, dest):
    # The offload host serves media only to crawler UAs.
    ua = _BOT_UA if url.startswith(_OFFLOAD_BASE) else _UA
    r = cffi_requests.get(url, headers={"User-Agent": ua}, impersonate="chrome",
                          timeout=120, proxies=_proxies())
    r.raise_for_status()
    with open(dest, "wb") as f:
        f.write(r.content)
    return dest


async def download_file(url, dest):
    return await asyncio.to_thread(_download_file, url, dest)
