"""No-login Instagram post fetching (single or carousel, photos + videos).

Instagram blocks anonymous yt-dlp/gallery-dl. This client fetches public posts
without cookies or an account. Method chain (first with media wins):

- If IG_PROXY_URL is set: mobile GraphQL -> web GraphQL -> api/v1 (direct, best
  quality; only work from an unblocked IP).
- Always: "fixer" (embed page for caption+structure; video bytes from a public
  InstaFix offload host that serves from its own unblocked IP).
- Last resort: embed only (images + caption, no video).

Returns {"shortcode", "caption", "media": [{"type": "video"|"image", "url"}]}.
"""

import os
import re
import json
import asyncio

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
_BOT_UA = "TelegramBot (like TwitterBot)"
_GQL_URL = "https://www.instagram.com/graphql/query/"

# doc_ids and fixer hosts change over time; override via env without a code change.
_GQL_MOBILE_DOC_ID = os.getenv("IG_MOBILE_DOC_ID", "8845758582119845")
_GQL_WEB_DOC_ID = os.getenv("IG_WEB_DOC_ID", "25531498899829322")
_FIXER_URL = os.getenv("IG_FIXER_URL", "https://www.instagram7.com").rstrip("/")
# Fallback offload base; the real one is derived per-request from the fixer's
# og:video (services move the offload host around). Defaults to the fixer host.
_OFFLOAD_BASE = os.getenv("IG_OFFLOAD_BASE", f"{_FIXER_URL}/offload").rstrip("/")


# --- pure helpers (no network) -----------------------------------------------

def is_instagram_url(url):
    return bool(url and _IG_URL_RE.match(url))


def extract_shortcode(url):
    m = _SHORTCODE_RE.search(url or "")
    return m.group(1) if m else None


def shortcode_to_pk(code):
    """Instagram shortcodes are base64 of the media pk (first 11 chars)."""
    pk = 0
    for ch in code[:11]:
        if ch not in _B64:
            break
        pk = pk * 64 + _B64.index(ch)
    return pk


def parse_gql_media(sm):
    """Extract caption + media from a GraphQL/embed `shortcode_media` node."""
    caption = _caption_of(sm)
    media = []
    for n in _nodes_of(sm):
        if n.get("is_video") and n.get("video_url"):
            media.append({"type": "video", "url": n["video_url"]})
        elif n.get("display_url"):
            media.append({"type": "image", "url": n["display_url"]})
    return {"caption": caption, "media": media}


def _caption_of(sm):
    try:
        return sm["edge_media_to_caption"]["edges"][0]["node"]["text"]
    except Exception:
        return ""


def _nodes_of(sm):
    sidecar = sm.get("edge_sidecar_to_children")
    return [e["node"] for e in sidecar["edges"]] if sidecar else [sm]


def _media_from_api_node(node):
    if node.get("video_versions"):
        return {"type": "video", "url": node["video_versions"][0]["url"]}
    candidates = (node.get("image_versions2") or {}).get("candidates") or []
    if candidates:
        return {"type": "image", "url": candidates[0]["url"]}
    return None


def fixer_meta(html, prop):
    m = re.search(
        r'<meta[^>]+(?:property|name)="' + re.escape(prop) + r'"[^>]+content="([^"]*)"',
        html,
    )
    return m.group(1) if m else ""


def offload_url(shortcode, index, base=None):
    return f"{base or _OFFLOAD_BASE}/{shortcode}/{index}"


def offload_base_from(og_video, shortcode):
    """Derive the offload base (https://host/offload) from a fixer og:video URL."""
    if not og_video:
        return None
    url = og_video.split("?")[0].rstrip("/")
    m = re.search(r"^(.*)/" + re.escape(shortcode) + r"/\d+$", url)
    return m.group(1) if m else None


class InstagramClient:
    def __init__(self, http):
        self.http = http

    # --- direct Instagram endpoints (need an unblocked IP / proxy) ----------

    def _api_headers(self, shortcode):
        return {
            "User-Agent": _UA, "X-IG-App-ID": _APP_ID, "X-ASBD-ID": "129477",
            "X-IG-WWW-Claim": "0", "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://www.instagram.com/p/{shortcode}/",
            "Origin": "https://www.instagram.com",
        }

    def _gql_post(self, data, headers, label):
        r = self.http.post(_GQL_URL, data=data, headers=headers)
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
        return parse_gql_media(sm)

    def _fetch_via_gql_mobile(self, shortcode):
        data = {
            "variables": json.dumps({"shortcode": shortcode}),
            "doc_id": _GQL_MOBILE_DOC_ID, "server_timestamps": "true",
        }
        headers = {
            "User-Agent": _MOBILE_UA, "X-IG-App-ID": _APP_ID, "X-ASBD-ID": "129477",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://www.instagram.com/p/{shortcode}/",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        return self._gql_post(data, headers, "mobile GraphQL")

    def _fetch_via_gql_web(self, shortcode):
        data = {
            "av": "0", "__d": "www", "__user": "0", "__a": "1", "__comet_req": "7",
            "fb_api_caller_class": "RelayModern",
            "fb_api_req_friendly_name": "PolarisPostActionLoadPostQueryQuery",
            "variables": json.dumps({
                "shortcode": shortcode, "fetch_tagged_user_count": None,
                "hoisted_comment_id": None, "hoisted_reply_id": None,
            }),
            "server_timestamps": "true", "doc_id": _GQL_WEB_DOC_ID,
        }
        headers = {
            "User-Agent": _UA, "X-IG-App-ID": _APP_ID, "X-ASBD-ID": "129477",
            "X-FB-Friendly-Name": "PolarisPostActionLoadPostQueryQuery",
            "Origin": "https://www.instagram.com",
            "Referer": f"https://www.instagram.com/p/{shortcode}/",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        return self._gql_post(data, headers, "web GraphQL")

    def _fetch_via_api(self, shortcode):
        pk = shortcode_to_pk(shortcode)
        url = f"https://www.instagram.com/api/v1/media/{pk}/info/"
        r = self.http.get(url, headers=self._api_headers(shortcode), allow_redirects=False)
        if r.status_code != 200:
            logger.info(f"Instagram api/v1 -> {r.status_code} for {shortcode} (likely login-gated)")
            return None
        items = r.json().get("items") or []
        if not items:
            return None
        item = items[0]
        caption = ((item.get("caption") or {}).get("text") or "")
        media = []
        nodes = item.get("carousel_media") or [item]
        for node in nodes:
            mm = _media_from_api_node(node)
            if mm:
                media.append(mm)
        return {"caption": caption, "media": media}

    # --- embed + fixer (work even when the IP is blocked) --------------------

    def _embed_shortcode_media(self, shortcode):
        url = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
        r = self.http.get(url, headers={"User-Agent": _UA})
        if r.status_code != 200:
            return None
        m = re.search(r'"contextJSON":"((?:[^"\\]|\\.)*)"', r.text)
        if not m:
            return None
        try:
            return json.loads(json.loads('"' + m.group(1) + '"'))["gql_data"]["shortcode_media"]
        except Exception:
            return None

    def _fetch_via_embed(self, shortcode):
        sm = self._embed_shortcode_media(shortcode)
        return parse_gql_media(sm) if sm else None

    def _fixer_og_video(self, shortcode):
        """Prime the fixer (crawler UA) and return its og:video URL (or "")."""
        try:
            r = self.http.get(f"{_FIXER_URL}/p/{shortcode}/", headers={"User-Agent": _BOT_UA}, timeout=20)
            if r.status_code == 200:
                return fixer_meta(r.text, "og:video")
        except Exception as e:
            logger.warning(f"Instagram fixer prime failed for {shortcode}: {e}")
        return ""

    def _fetch_via_fixer_single(self, shortcode):
        try:
            r = self.http.get(f"{_FIXER_URL}/p/{shortcode}/", headers={"User-Agent": _BOT_UA}, timeout=20)
        except Exception as e:
            logger.warning(f"Instagram fixer single fetch failed for {shortcode}: {e}")
            return None
        if r.status_code != 200:
            return None
        video = fixer_meta(r.text, "og:video")
        image = fixer_meta(r.text, "og:image").split("?")[0]  # drop ?thumbnail=1
        title = fixer_meta(r.text, "og:title")
        if video:
            return {"caption": title, "media": [{"type": "video", "url": video}]}
        if image:
            return {"caption": title, "media": [{"type": "image", "url": image}]}
        return None

    def _fetch_via_fixer(self, shortcode):
        """Structure + caption from the embed page; video bytes from the fixer's
        offload host. Photos come straight from the CDN display_url."""
        sm = self._embed_shortcode_media(shortcode)
        if not sm:
            return self._fetch_via_fixer_single(shortcode)
        caption = _caption_of(sm)
        nodes = _nodes_of(sm)
        offload_base = _OFFLOAD_BASE
        if any(n.get("is_video") for n in nodes):
            # Prime the fixer and derive the current offload host from its og:video.
            base = offload_base_from(self._fixer_og_video(shortcode), shortcode)
            if base:
                offload_base = base
        media = []
        for i, n in enumerate(nodes, start=1):
            if n.get("is_video"):
                media.append({"type": "video", "url": offload_url(shortcode, i, offload_base)})
            elif n.get("display_url"):
                media.append({"type": "image", "url": n["display_url"]})
        if not media:
            return self._fetch_via_fixer_single(shortcode)
        return {"caption": caption, "media": media}

    # --- orchestration -------------------------------------------------------

    def _fetch(self, url):
        shortcode = extract_shortcode(url)
        if not shortcode:
            logger.warning(f"Could not extract Instagram shortcode from {url}")
            return None
        methods = []
        if self.http._proxies():
            methods += [
                ("mobile GraphQL", self._fetch_via_gql_mobile),
                ("web GraphQL", self._fetch_via_gql_web),
                ("api/v1", self._fetch_via_api),
            ]
        methods += [
            ("fixer", self._fetch_via_fixer),
            ("embed", self._fetch_via_embed),
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

    async def fetch(self, url):
        return await asyncio.to_thread(self._fetch, url)

    def _download_file(self, url, dest):
        # The offload host serves media only to crawler UAs (host-agnostic: match path).
        ua = _BOT_UA if "/offload/" in url else _UA
        return self.http.download(url, dest, headers={"User-Agent": ua})

    async def download_file(self, url, dest):
        return await asyncio.to_thread(self._download_file, url, dest)
