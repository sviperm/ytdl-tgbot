"""Routes a URL to its platform, handles caching, sending, and cleanup."""

import os
import shutil
import asyncio
from uuid import uuid4

from src.config import Config
from src.core.errors import PlatformError, FetchError
from src.services.status import StatusReporter
from src.utils.logger import logger

# Raw exception text can carry local paths and internal URLs, so the user gets a
# fixed line and the detail goes to the log.
_UNEXPECTED_MESSAGE = "Something went wrong while handling this link. Please try again."


class DownloadOrchestrator:
    def __init__(self, registry, sender, db, max_concurrent=None):
        self.registry = registry
        self.sender = sender
        self.db = db
        # One semaphore for the whole bot (the container builds one orchestrator):
        # downloading and transcoding are CPU/disk bound, so N parallel requests
        # would mean N ffmpeg runs fighting over a small VPS.
        self._downloads = asyncio.Semaphore(max_concurrent or Config.MAX_CONCURRENT_DOWNLOADS)

    async def handle_url(self, client, message, url):
        platform = self.registry.resolve(url)
        if platform is None:
            return
        status = StatusReporter(await message.reply_text(platform.initial_status))
        work_dir = None
        try:
            meta = await platform.probe(url)

            if meta.supports_cache and meta.video_id:
                file_id = await self.db.get_file_id(meta.platform, meta.video_id)
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

            # Created only now, so a cache hit never touches the disk. Everything
            # this request writes lives in here and dies with it below — including
            # partial files from a fetch that raised halfway through.
            work_dir = os.path.join(Config.DOWNLOAD_DIR, uuid4().hex[:12])
            os.makedirs(work_dir, exist_ok=True)

            post = await self._fetch(platform, url, meta, status, work_dir)
            if not post.media:
                raise FetchError(user_message="Failed to extract video info. Are you sure the link is valid?")

            # fetch() refines the metadata it was given, so caption/duration/cache
            # key all come from the post now, not from the probe result above.
            final = post.meta
            result = await self.sender.send_post(client, message.chat.id, post, status)

            if final.supports_cache and final.video_id and result.file_id:
                await self.db.add_file_id(final.platform, final.video_id, result.file_id, final.title)
                logger.info(f"Upload successful and cached: {final.title} ({result.file_id})")
            await status.done()
        except PlatformError as e:
            logger.error(f"{platform.name} error for {url}: {e}")
            await status.set(e.user_message)
        except Exception:
            logger.exception(f"Unexpected error handling {url}")
            await status.set(_UNEXPECTED_MESSAGE)
        finally:
            if work_dir:
                shutil.rmtree(work_dir, ignore_errors=True)
                logger.info(f"Cleaned up work dir: {work_dir}")

    async def _fetch(self, platform, url, meta, status, work_dir):
        """Download + process under the concurrency cap.

        The Telegram upload is deliberately left outside: it is network bound, and
        holding a slot through it would idle the CPU budget.
        """
        if self._downloads.locked():
            await status.set("Queued: waiting for a free download slot...")
        async with self._downloads:
            return await platform.fetch(url, meta, status, work_dir)
