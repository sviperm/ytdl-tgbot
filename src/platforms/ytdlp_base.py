"""Shared yt-dlp platform behaviour (probe + download + process)."""

import os
import asyncio

from src.platforms.base import Platform
from src.core.models import MediaItem, PostMeta, Post
from src.core.errors import ExtractError, AuthRequiredError, DownloadError
from src.services.progress import DownloadProgress
from src.utils.captions import build_caption

# yt-dlp error substrings that mean "login required" rather than "bad link".
_AUTH_MARKERS = (
    "empty media response", "login required", "requires authentication",
    "cookies", "requested content is not available", "rate-limit",
    "sign in", "private",
)


class YtDlpPlatform(Platform):
    """Generic yt-dlp platform; also the catch-all fallback."""

    name = "generic"
    initial_status = "Extracting info..."

    def __init__(self, ytdlp, video):
        self.ytdlp = ytdlp
        self.video = video

    # Hooks overridden by subclasses
    def normalize_url(self, url):
        return url

    @property
    def extractor_args(self):
        return None

    def matches(self, url):
        return bool(url) and url.startswith(("http://", "https://"))

    async def probe(self, url):
        info = await self.ytdlp.extract_info(self.normalize_url(url), self.extractor_args)
        if not info:
            err = (self.ytdlp.last_extract_error or "").lower()
            if any(m in err for m in _AUTH_MARKERS):
                raise AuthRequiredError()
            raise ExtractError()
        return PostMeta(
            video_id=info.get("id"),
            platform=info.get("extractor"),
            title=info.get("title"),
            caption_html=build_caption(info.get("title"), url),
            duration=int(info.get("duration") or 0),
            width=int(info.get("width") or 0),
            height=int(info.get("height") or 0),
            supports_cache=True,
        )

    async def fetch(self, url, meta, status):
        await status.set(f"Downloading: {meta.title}")
        # Live download progress bar (yt-dlp hook -> status message).
        progress = DownloadProgress(status, asyncio.get_running_loop(), meta.title)
        path, info = await self.ytdlp.download(
            self.normalize_url(url), self.extractor_args, progress_hook=progress.hook,
        )
        if not path or not os.path.exists(path):
            raise DownloadError()
        if info:  # post-download info may have more accurate values
            meta.width = int(info.get("width") or meta.width)
            meta.height = int(info.get("height") or meta.height)
            meta.duration = int(info.get("duration") or meta.duration)

        await status.set("Processing video...")
        path = await self.video.process(path)
        probed = await self.video.probe_duration(path)
        if probed:
            meta.duration = probed
        thumb = await self.video.make_thumbnail(path)
        return Post(
            meta=meta,
            media=[MediaItem("video", path, thumb)],
            use_upload_progress=True,
            upload_status_text="Uploading to Telegram...",
        )
