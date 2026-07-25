"""Routes a URL to its platform, handles caching, sending, and cleanup."""

import os

from src.core.errors import PlatformError, FetchError
from src.services.status import StatusReporter
from src.utils.logger import logger


class DownloadOrchestrator:
    def __init__(self, registry, sender, db):
        self.registry = registry
        self.sender = sender
        self.db = db

    async def handle_url(self, client, message, url):
        platform = self.registry.resolve(url)
        if platform is None:
            return
        status = StatusReporter(await message.reply_text(platform.initial_status))
        post = None
        try:
            meta = await platform.probe(url)

            if meta.supports_cache and meta.video_id:
                file_id = await self.db.get_video(meta.video_id)
                if file_id:
                    logger.info(f"Cache hit for {meta.video_id}. Sending cached file.")
                    await status.set("Video found in cache! Sending...")
                    try:
                        await self.sender.send_cached_video(client, message.chat.id, file_id, meta)
                        await status.done()
                        return
                    except Exception as e:
                        logger.warning(f"Failed to send cached video {meta.video_id}: {e}. Redownloading...")
                        await status.set("Cache invalid. Redownloading...")

            post = await platform.fetch(url, meta, status)
            if not post.media:
                raise FetchError(user_message="Failed to extract video info. Are you sure the link is valid?")

            await status.set(post.upload_status_text)
            result = await self.sender.send_post(client, message.chat.id, post, status)

            if meta.supports_cache and meta.video_id and result.file_id:
                await self.db.add_video(meta.video_id, meta.platform, result.file_id, meta.title)
                logger.info(f"Upload successful and cached: {meta.title} ({result.file_id})")
            await status.done()
        except PlatformError as e:
            logger.error(f"{platform.name} error for {url}: {e}")
            await status.set(e.user_message)
        except Exception as e:
            logger.error(f"Unexpected error handling {url}: {e}")
            await status.set(f"Failed: {e}")
        finally:
            if post:
                for path in post.all_paths():
                    if path and os.path.exists(path):
                        os.remove(path)
                        logger.info(f"Cleaned up local file: {path}")
