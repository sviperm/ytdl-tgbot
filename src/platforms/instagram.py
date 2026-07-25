import os

from src.platforms.base import Platform
from src.core.models import MediaItem, PostMeta, Post
from src.core.errors import FetchError
from src.config import Config
from src.utils.captions import build_ig_caption
from src.utils.logger import logger
from src.services.instagram_client import is_instagram_url, extract_shortcode


class InstagramPlatform(Platform):
    name = "instagram"
    initial_status = "Fetching Instagram post..."

    def __init__(self, ig_client, video):
        self.ig = ig_client
        self.video = video

    def matches(self, url):
        return is_instagram_url(url)

    async def probe(self, url):
        # Pure: Instagram posts are never cached, so no network here.
        return PostMeta(video_id=extract_shortcode(url), platform="instagram", supports_cache=False)

    async def fetch(self, url, meta, status):
        post = await self.ig.fetch(url)
        if not post or not post.get("media"):
            raise FetchError()

        shortcode = post["shortcode"]
        meta.video_id = shortcode
        meta.title = shortcode
        meta.caption_html = build_ig_caption(post.get("caption") or "", url)

        items = post["media"]
        await status.set(f"Downloading {len(items)} item(s)...")
        media = []
        for i, item in enumerate(items):
            ext = ".mp4" if item["type"] == "video" else ".jpg"
            dest = os.path.join(Config.DOWNLOAD_DIR, f"{shortcode}_{i}{ext}")
            try:
                await self.ig.download_file(item["url"], dest)
            except Exception as e:
                # Skip a single failed item rather than failing the whole post.
                logger.warning(f"Instagram item {i} ({item['url']}) download failed: {e}")
                continue
            if item["type"] == "video":
                dest = await self.video.process(dest)  # H.264 for iOS + faststart
                thumb = await self.video.make_thumbnail(dest)
                media.append(MediaItem("video", dest, thumb))
            else:
                media.append(MediaItem("image", dest))

        if not media:
            raise FetchError()
        return Post(meta=meta, media=media, use_upload_progress=False, upload_status_text="Uploading...")
