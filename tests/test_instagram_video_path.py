"""The yt-dlp-first path of InstagramPlatform (single videos / reels).

Single videos come from yt-dlp's own Instagram extractor; the embed + fixer chain
in InstagramClient stays as the fallback for everything else. These tests pin both
halves: that a single video never touches the client, and that a carousel, a photo
post, a yt-dlp failure and a missing yt-dlp client all still reach it.
"""

import os

import pytest

from fakes import FakeStatus
from src.platforms.instagram import InstagramPlatform

URL = "https://www.instagram.com/reel/Dd31Mm0q30z/"

VIDEO_INFO = {
    "id": "Dd31Mm0q30z",
    "title": "reel title",
    "description": "reel caption",
    "vcodec": "avc1.640028",
    "ext": "mp4",
    "width": 1080,
    "height": 1920,
    "duration": 11,
}


class FakeYtdlp:
    """Stand-in for YtDlpClient: canned metadata and download results."""

    def __init__(self, info=None, error=None, download_error=None):
        self.info, self.error, self.download_error = info, error, download_error
        self.extract_calls = []
        self.download_calls = []

    async def extract_info(self, url, extractor_args=None):
        self.extract_calls.append(url)
        return self.info, self.error

    async def download(self, url, work_dir, extractor_args=None, progress_hook=None):
        self.download_calls.append(url)
        if self.download_error:
            return None, None, self.download_error
        path = os.path.join(work_dir, "out.mp4")
        with open(path, "wb") as fh:
            fh.write(b"video")
        return path, self.info, None


class FakeVideo:
    def __init__(self):
        self.probed = []

    async def process(self, path):
        return path

    async def make_thumbnail(self, path):
        return path + ".jpg"

    async def probe_dimensions(self, path):
        self.probed.append(path)
        return 1080, 1920

    async def probe_duration(self, path):
        return 12


class FakeIgClient:
    """The embed + fixer fallback: one image is enough to prove it was used."""

    def __init__(self):
        self.fetched = []
        self.downloaded = []

    async def fetch(self, url):
        self.fetched.append(url)
        return {"shortcode": "Dd31Mm0q30z", "caption": "from the embed",
                "media": [{"type": "image", "url": "http://cdn/1.jpg"}]}

    async def download_file(self, url, dest, on_progress=None):
        self.downloaded.append(url)
        with open(dest, "wb") as fh:
            fh.write(b"bytes")
        return dest


async def _fetch(ytdlp, tmp_path):
    ig = FakeIgClient()
    video = FakeVideo()
    platform = InstagramPlatform(ig, video, ytdlp)
    meta = await platform.probe(URL)
    post = await platform.fetch(URL, meta, FakeStatus(), str(tmp_path))
    return post, ig, video


async def test_single_video_goes_through_ytdlp(tmp_path):
    ytdlp = FakeYtdlp(info=VIDEO_INFO)
    post, ig, video = await _fetch(ytdlp, tmp_path)

    assert ytdlp.extract_calls == [URL]
    assert ytdlp.download_calls == [URL]
    assert ig.fetched == []                      # the fixer chain was never touched
    assert [m.kind for m in post.media] == ["video"]
    assert post.meta.video_id == "Dd31Mm0q30z"
    assert post.meta.width == 1080 and post.meta.height == 1920
    # duration comes from the downloaded file, not from yt-dlp's metadata
    assert post.meta.duration == 12
    assert "reel caption" in post.meta.caption_html
    assert video.probed == []                    # dimensions came from yt-dlp


async def test_dimensions_are_probed_when_ytdlp_reports_none(tmp_path):
    info = {k: v for k, v in VIDEO_INFO.items() if k not in ("width", "height")}
    post, ig, video = await _fetch(FakeYtdlp(info=info), tmp_path)

    # a video sent as 0x0 renders as a squashed strip
    assert post.meta.width == 1080 and post.meta.height == 1920
    assert len(video.probed) == 1
    assert ig.fetched == []


@pytest.mark.parametrize("info", [
    {**VIDEO_INFO, "entries": [{"id": "1"}, {"id": "2"}]},   # carousel
    {**VIDEO_INFO, "vcodec": "none"},                        # photo post
    {**VIDEO_INFO, "ext": "jpg"},
])
async def test_non_video_posts_fall_back_to_the_client(info, tmp_path):
    post, ig, video = await _fetch(FakeYtdlp(info=info), tmp_path)

    assert ig.fetched == [URL]
    assert [m.kind for m in post.media] == ["image"]
    assert "from the embed" in post.meta.caption_html


async def test_ytdlp_failure_falls_back_to_the_client(tmp_path):
    ytdlp = FakeYtdlp(info=VIDEO_INFO, download_error="HTTP Error 429")
    post, ig, video = await _fetch(ytdlp, tmp_path)

    assert ytdlp.download_calls == [URL]         # it was tried first
    assert ig.fetched == [URL]                   # then the chain got its turn
    assert [m.kind for m in post.media] == ["image"]


async def test_extract_failure_falls_back_to_the_client(tmp_path):
    post, ig, video = await _fetch(FakeYtdlp(info=None, error="Unable to extract"), tmp_path)

    assert ig.fetched == [URL]


async def test_platform_without_ytdlp_uses_the_client(tmp_path):
    # Existing wiring/tests construct it with two arguments.
    post, ig, video = await _fetch(None, tmp_path)

    assert ig.fetched == [URL]
    assert [m.kind for m in post.media] == ["image"]
