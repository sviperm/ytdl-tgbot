import os
import asyncio
from dataclasses import replace

from src.platforms.base import Platform
from src.platforms.ytdlp_base import YtDlpPlatform
from src.core.models import MediaItem, PostMeta, Post
from src.core.errors import FetchError, PlatformError, UnsupportedLinkError
from src.services.progress import FileDownloadProgress
from src.utils.captions import build_ig_caption
from src.utils.logger import logger
from src.services.instagram_client import is_instagram_url, extract_shortcode


def _is_single_video(info):
    """True when yt-dlp resolved the post to one plain video stream.

    A carousel is a playlist (``entries``) and a photo post has no video stream at
    all; neither is taken this way, because the client never needed a third-party
    host for their bytes (photos come from the CDN display_url).
    """
    return (not info.get("entries")
            and info.get("vcodec") not in (None, "none")
            and info.get("ext") in ("mp4", "webm", "mkv"))


class InstagramPlatform(Platform):
    name = "instagram"
    initial_status = "Fetching Instagram post..."

    def __init__(self, ig_client, video, ytdlp=None):
        self.ig = ig_client
        self.video = video
        # Single videos and reels come from yt-dlp's own Instagram extractor, which
        # reads the post's DASH manifest straight from Instagram. The embed + fixer
        # chain in InstagramClient stays as the fallback: those public hosts rot
        # without notice (a dead instagram7.com was silently breaking every video),
        # and it is still the only path that orders carousels and reads a photo
        # post's caption. Download + transcode are identical to any other yt-dlp
        # platform, so that work is delegated rather than duplicated.
        self.ytdlp = ytdlp
        self._ytdlp_platform = YtDlpPlatform(ytdlp, video) if ytdlp else None

    def matches(self, url):
        return is_instagram_url(url)

    def is_media_link(self, url):
        return bool(extract_shortcode(url))

    async def probe(self, url):
        # Pure: Instagram posts are never cached, so no network here.
        shortcode = extract_shortcode(url)
        if not shortcode:
            # A profile or story link: no post id, so there is nothing to fetch.
            # Neither can be listed without a login, so it fails here, once.
            raise UnsupportedLinkError(
                message=f"no post id in {url}",
                user_message=("🔗 This is an Instagram profile or story link, not a post. "
                              "Send a link to a specific post or reel "
                              "(instagram.com/p/... or /reel/...)."),
            )
        return PostMeta(video_id=shortcode, platform="instagram", supports_cache=False)

    async def fetch(self, url, meta, status, work_dir):
        post = await self._fetch_video(url, meta, status, work_dir)
        return post or await self._fetch_via_client(url, meta, status, work_dir)

    async def _fetch_video(self, url, meta, status, work_dir):
        """One video post via yt-dlp; None means "not this path, use the client"."""
        if not self.ytdlp or not self._ytdlp_platform:
            return None
        info, error = await self.ytdlp.extract_info(url)
        if not info or not _is_single_video(info):
            logger.info(f"Instagram {url}: no yt-dlp video path "
                        f"({error or 'not a single video'}) — using the embed chain")
            return None
        try:
            post = await self._ytdlp_platform.fetch(
                url,
                replace(
                    meta,
                    title=info.get("title") or meta.video_id,
                    caption_html=build_ig_caption(info.get("description") or "", url),
                ),
                status,
                work_dir,
            )
        except PlatformError as e:
            # yt-dlp failing is not fatal: the client's chain gets a turn, exactly
            # as it did before this path existed.
            logger.warning(f"Instagram yt-dlp download failed for {url}: {e} "
                           "— using the embed chain")
            return None
        if post.meta.width and post.meta.height:
            return post
        # Dimensions are probed off the file when yt-dlp reports none: a video sent
        # as 0x0 renders as a squashed strip.
        width, height = await self.video.probe_dimensions(post.media[0].path)
        return Post(meta=replace(post.meta, width=width, height=height), media=post.media)

    async def _fetch_via_client(self, url, meta, status, work_dir):
        post = await self.ig.fetch(url)
        if not post or not post.get("media"):
            raise FetchError()

        shortcode = post["shortcode"]
        items = post["media"]
        loop = asyncio.get_running_loop()
        media = []
        # Instagram's fetch chain reports no dimensions or duration, and a video
        # sent as 0x0 renders as a squashed strip. They are probed off the file
        # instead; only a single-item post uses them, so the first video wins.
        width = height = duration = 0
        for i, item in enumerate(items):
            ext = ".mp4" if item["type"] == "video" else ".jpg"
            dest = os.path.join(work_dir, f"{shortcode}_{i}{ext}")
            # Byte-level bar per item; the header keeps the carousel position visible.
            progress = FileDownloadProgress(
                status, loop, f"Downloading {i + 1}/{len(items)}",
            )
            try:
                await self.ig.download_file(item["url"], dest, on_progress=progress)
            except Exception as e:
                # Skip a single failed item rather than failing the whole post.
                logger.warning(f"Instagram item {i} ({item['url']}) download failed: {e}")
                continue
            if item["type"] == "video":
                await status.set(f"Processing {i + 1}/{len(items)}...")
                dest = await self.video.process(dest)  # H.264 for iOS + faststart
                thumb = await self.video.make_thumbnail(dest)
                if not width:
                    width, height = await self.video.probe_dimensions(dest)
                    duration = await self.video.probe_duration(dest)
                media.append(MediaItem("video", dest, thumb))
            else:
                media.append(MediaItem("image", dest))

        if not media:
            raise FetchError()
        return Post(
            meta=replace(
                meta,
                video_id=shortcode,
                title=shortcode,
                caption_html=build_ig_caption(post.get("caption") or "", url),
                width=width,
                height=height,
                duration=duration,
            ),
            media=media,
        )
