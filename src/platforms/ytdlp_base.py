"""Shared yt-dlp platform behaviour (probe + download + process)."""

import os
import asyncio
from dataclasses import replace

from src.platforms.base import Platform
from src.core.models import MediaItem, PostMeta, Post
from src.core.errors import ExtractError, AuthRequiredError, DownloadError
from src.services.ytdlp import is_auth_error
from src.services.progress import DownloadProgress
from src.utils.captions import build_caption
from src.utils.urls import is_http_url


class YtDlpPlatform(Platform):
    """Abstract yt-dlp platform: subclasses narrow matches()/normalize_url().

    Not registrable on its own — GenericPlatform is the concrete catch-all.
    """

    name = "ytdlp"
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
        return is_http_url(url)

    async def probe(self, url):
        # Metadata only; fetch() extracts a second time to download. See the note
        # in YtDlpClient._download for why that duplication is tolerated.
        info, error = await self.ytdlp.extract_info(self.normalize_url(url), self.extractor_args)
        if not info:
            if is_auth_error(error):
                raise AuthRequiredError()
            raise ExtractError(message=f"metadata extraction failed: {error}")
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

    async def fetch(self, url, meta, status, work_dir):
        await status.set(f"Downloading: {meta.title}")
        # Live download progress bar (yt-dlp hook -> status message).
        progress = DownloadProgress(status, asyncio.get_running_loop(), meta.title)
        path, info, error = await self.ytdlp.download(
            self.normalize_url(url), work_dir, self.extractor_args, progress_hook=progress.hook,
        )
        if not path or not os.path.exists(path):
            raise DownloadError(message=f"download failed for {url}: {error or 'no output file'}")

        width, height, duration = meta.width, meta.height, meta.duration
        if info:  # post-download info may have more accurate values
            width = int(info.get("width") or width)
            height = int(info.get("height") or height)
            duration = int(info.get("duration") or duration)

        await status.set("Processing video...")
        path = await self.video.process(path)
        probed = await self.video.probe_duration(path)
        if probed:
            duration = probed
        thumb = await self.video.make_thumbnail(path)
        return Post(
            meta=replace(meta, width=width, height=height, duration=duration),
            media=[MediaItem("video", path, thumb)],
        )
