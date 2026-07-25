import json

import pytest

from src.services import instagram_client as ig
from src.services.instagram_client import (
    InstagramClient, is_instagram_url, extract_shortcode, shortcode_to_pk,
    parse_gql_media, fixer_meta, offload_url, offload_base_from,
)


class FakeResponse:
    def __init__(self, status_code=200, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json = json_data
        self.content = text.encode() if isinstance(text, str) else (text or b"")

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"http {self.status_code}")


class FakeHttp:
    def __init__(self, responses=None, proxy=None):
        self.responses = responses or {}   # substring -> FakeResponse
        self._proxy = proxy
        self.calls = []

    def _proxies(self):
        return {"http": self._proxy, "https": self._proxy} if self._proxy else None

    def _match(self, url):
        for key, resp in self.responses.items():
            if key in url:
                return resp
        return FakeResponse(404, "")

    def get(self, url, headers=None, allow_redirects=True, timeout=25):
        self.calls.append(("get", url, headers))
        return self._match(url)

    def post(self, url, data=None, headers=None, timeout=25):
        self.calls.append(("post", url, headers))
        return self._match(url)

    def download(self, url, dest, headers=None, timeout=120):
        self.calls.append(("download", url, headers))
        open(dest, "wb").write(b"data")
        return dest


def make_embed_html(sm):
    ctx = json.dumps({"gql_data": {"shortcode_media": sm}})
    return '<html><script>{"contextJSON":' + json.dumps(ctx) + '}</script></html>'


# --- pure helpers ------------------------------------------------------------

@pytest.mark.parametrize("url,code", [
    ("https://www.instagram.com/reel/DZ9sTMZMX7I/?igsh=x", "DZ9sTMZMX7I"),
    ("https://instagram.com/p/ABC123def/", "ABC123def"),
    ("https://www.instagram.com/reels/XYZ/", "XYZ"),
    ("https://www.instagram.com/tv/TTT/", "TTT"),
    ("https://www.instagram.com/someuser/p/COD-e_1/", "COD-e_1"),
    ("https://youtu.be/x", None),
])
def test_extract_shortcode(url, code):
    assert extract_shortcode(url) == code


def test_is_instagram_url():
    assert is_instagram_url("https://www.instagram.com/reel/X/")
    assert not is_instagram_url("https://youtu.be/x")


def test_shortcode_to_pk_known_vector():
    assert shortcode_to_pk("DZ9sTMZMX7I") == 3926489283161063112


def test_parse_gql_single_video():
    sm = {"is_video": True, "video_url": "https://cdn/v.mp4", "display_url": "https://cdn/p.jpg",
          "edge_media_to_caption": {"edges": [{"node": {"text": "hello"}}]}}
    out = parse_gql_media(sm)
    assert out["caption"] == "hello"
    assert out["media"] == [{"type": "video", "url": "https://cdn/v.mp4"}]


def test_parse_gql_carousel_mixed():
    sm = {"edge_sidecar_to_children": {"edges": [
        {"node": {"is_video": False, "display_url": "https://cdn/1.jpg"}},
        {"node": {"is_video": True, "video_url": "https://cdn/2.mp4", "display_url": "https://cdn/2.jpg"}},
    ]}, "edge_media_to_caption": {"edges": [{"node": {"text": "cap"}}]}}
    out = parse_gql_media(sm)
    assert out["caption"] == "cap"
    assert out["media"] == [
        {"type": "image", "url": "https://cdn/1.jpg"},
        {"type": "video", "url": "https://cdn/2.mp4"},
    ]


def test_parse_gql_image_only_no_caption():
    sm = {"is_video": False, "display_url": "https://cdn/i.jpg",
          "edge_media_to_caption": {"edges": []}}
    out = parse_gql_media(sm)
    assert out["caption"] == ""
    assert out["media"] == [{"type": "image", "url": "https://cdn/i.jpg"}]


def test_fixer_meta_and_offload_url():
    html = '<meta property="og:video" content="https://oginstagram.com/offload/ABC/1">'
    assert fixer_meta(html, "og:video") == "https://oginstagram.com/offload/ABC/1"
    assert fixer_meta(html, "og:image") == ""
    assert offload_url("ABC", 3, "https://h/offload") == "https://h/offload/ABC/3"


# --- client methods with fake http ------------------------------------------

def test_embed_shortcode_media_round_trip():
    sm = {"is_video": True, "video_url": "https://cdn/v.mp4",
          "edge_media_to_caption": {"edges": [{"node": {"text": "hi"}}]}}
    http = FakeHttp({"embed/captioned": FakeResponse(200, make_embed_html(sm))})
    client = InstagramClient(http)
    parsed = client._embed_shortcode_media("CODE")
    assert parsed["video_url"] == "https://cdn/v.mp4"


def test_fetch_via_fixer_uses_offload_for_video_and_display_for_image():
    sm = {"edge_sidecar_to_children": {"edges": [
        {"node": {"is_video": False, "display_url": "https://cdn/1.jpg"}},
        {"node": {"is_video": True, "video_url": "https://cdn/orig.mp4", "display_url": "https://cdn/2.jpg"}},
    ]}, "edge_media_to_caption": {"edges": [{"node": {"text": "c"}}]}}
    http = FakeHttp({"embed/captioned": FakeResponse(200, make_embed_html(sm))})
    client = InstagramClient(http)
    out = client._fetch_via_fixer("CODE")
    assert out["caption"] == "c"
    # image via CDN display_url; video via the offload host (not the raw video_url)
    assert out["media"][0] == {"type": "image", "url": "https://cdn/1.jpg"}
    assert out["media"][1] == {"type": "video", "url": offload_url("CODE", 2)}


def test_offload_base_from():
    assert offload_base_from("https://www.instagram7.com/offload/ABC/1", "ABC") == \
        "https://www.instagram7.com/offload"
    assert offload_base_from("https://h/offload/ABC/2?x=1", "ABC") == "https://h/offload"
    assert offload_base_from("", "ABC") is None
    assert offload_base_from("https://h/other", "ABC") is None


def test_fetch_via_fixer_derives_offload_host_from_og_video():
    sm = {"is_video": True, "video_url": "x",
          "edge_media_to_caption": {"edges": [{"node": {"text": "c"}}]}}
    fixer_html = '<meta property="og:video" content="https://newhost.example/offload/CODE/1">'
    http = FakeHttp({
        "instagram.com/p/CODE/embed/captioned": FakeResponse(200, make_embed_html(sm)),
        "instagram7.com/p/CODE": FakeResponse(200, fixer_html),
    })
    client = InstagramClient(http)
    out = client._fetch_via_fixer("CODE")
    # video URL uses the host the fixer actually advertises, not the hardcoded default
    assert out["media"][0] == {"type": "video", "url": "https://newhost.example/offload/CODE/1"}


def test_fetch_via_api_carousel():
    api_json = {"items": [{
        "caption": {"text": "apicap"},
        "carousel_media": [
            {"image_versions2": {"candidates": [{"url": "https://cdn/a.jpg"}]}},
            {"video_versions": [{"url": "https://cdn/b.mp4"}]},
        ],
    }]}
    http = FakeHttp({"api/v1/media": FakeResponse(200, json_data=api_json)})
    client = InstagramClient(http)
    out = client._fetch_via_api("CODE")
    assert out["caption"] == "apicap"
    assert out["media"] == [
        {"type": "image", "url": "https://cdn/a.jpg"},
        {"type": "video", "url": "https://cdn/b.mp4"},
    ]


def test_fetch_chain_no_proxy_uses_fixer(monkeypatch):
    sm = {"is_video": True, "video_url": "x",
          "edge_media_to_caption": {"edges": [{"node": {"text": "t"}}]}}
    http = FakeHttp({"embed/captioned": FakeResponse(200, make_embed_html(sm))}, proxy=None)
    client = InstagramClient(http)
    out = client._fetch("https://www.instagram.com/reel/CODE/")
    assert out["shortcode"] == "CODE"
    assert out["media"][0]["type"] == "video"
    # no proxy -> direct GraphQL/api endpoints are NOT attempted
    assert not any("graphql" in url for _, url, *_ in http.calls)


def test_download_file_uses_crawler_ua_for_offload(tmp_path):
    http = FakeHttp()
    client = InstagramClient(http)
    dest = str(tmp_path / "v.mp4")
    client._download_file(offload_url("CODE", 1), dest)
    client._download_file("https://scontent.cdninstagram.com/i.jpg", str(tmp_path / "i.jpg"))
    offload_headers = http.calls[0][2]
    cdn_headers = http.calls[1][2]
    assert offload_headers["User-Agent"] == ig._BOT_UA
    assert cdn_headers["User-Agent"] == ig._UA
