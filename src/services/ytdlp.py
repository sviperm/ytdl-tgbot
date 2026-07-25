"""Thin async wrapper around yt-dlp used by the yt-dlp platforms."""

import os
import shutil
import asyncio

import yt_dlp

from src.config import Config
from src.utils.logger import logger

# Prefer H.264 (avc1) + AAC: the only codecs iOS/Telegram play everywhere
# (VP9/AV1 freeze on iOS). Anything else is transcoded after download.
# Capped at 1080p on the long edge so vertical/shorts keep full resolution.
# `<=?` keeps formats whose dimensions are unknown (e.g. some non-YouTube sites).
FORMAT = (
    'bestvideo[vcodec^=avc1][width<=?1920][height<=?1920]+bestaudio[acodec^=mp4a]/'
    'bestvideo[vcodec^=avc1][width<=?1920][height<=?1920]+bestaudio/'
    'bestvideo[width<=?1920][height<=?1920][ext=mp4]+bestaudio[ext=m4a]/'
    'bestvideo[width<=?1920][height<=?1920]+bestaudio/'
    'best[width<=?1920][height<=?1920]/best'
)


class YtDlpClient:
    """Runs blocking yt-dlp calls off the event loop; cookies are picked up live."""

    def __init__(self):
        if not shutil.which("ffmpeg"):
            logger.error("FFmpeg not found! High-quality downloads will fail. Please install ffmpeg.")
        # Last extraction error, so callers can craft a useful reply.
        self.last_extract_error = None

    def _opts(self, extractor_args=None):
        opts = {
            "format": FORMAT,
            "outtmpl": os.path.join(Config.DOWNLOAD_DIR, "%(id)s.%(ext)s"),
            # Pick up data/cookies.txt live, so it can be added/refreshed without a restart.
            "cookiefile": self._cookiefile(),
            # Download DASH/HLS fragments in parallel — smoother, faster throughput
            # (no-op for single-file formats).
            "concurrent_fragment_downloads": 4,
            # Fetch in 10 MB ranged chunks so YouTube killing a long connection
            # ("N bytes read, M more expected") retries just that chunk instead of
            # failing the whole download; also smooths the throttled speed.
            "http_chunk_size": 10 * 1024 * 1024,
            "retries": 10,
            "fragment_retries": 10,
            "continuedl": True,
        }
        if extractor_args:
            opts["extractor_args"] = extractor_args
        return opts

    @staticmethod
    def _cookiefile():
        """Return the cookies path only if it holds real cookie data.

        A missing, empty, or comment-only file (e.g. a stray placeholder) is
        ignored — yt-dlp hard-errors on a non-Netscape file, which would break
        every download even when cookies aren't wanted.
        """
        path = Config.COOKIES_FILE
        if not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    stripped = line.strip()
                    # '#HttpOnly_' lines are real cookies despite the leading '#'.
                    if stripped and (not stripped.startswith("#") or stripped.startswith("#HttpOnly_")):
                        return path
        except OSError:
            return None
        return None

    async def extract_info(self, url, extractor_args=None):
        return await asyncio.to_thread(self._extract_info, url, extractor_args)

    def _extract_info(self, url, extractor_args):
        self.last_extract_error = None
        with yt_dlp.YoutubeDL(self._opts(extractor_args)) as ydl:
            try:
                logger.info(f"Extracting metadata for: {url}")
                return ydl.extract_info(url, download=False)
            except Exception as e:
                self.last_extract_error = str(e)
                logger.error(f"Error during metadata extraction for {url}: {e}")
                return None

    async def download(self, url, extractor_args=None, progress_hook=None):
        return await asyncio.to_thread(self._download, url, extractor_args, progress_hook)

    def _download(self, url, extractor_args, progress_hook=None):
        opts = self._opts(extractor_args)
        if progress_hook:
            opts["progress_hooks"] = [progress_hook]
        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                logger.info(f"Starting actual download for: {url}")
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                # A merged file's extension may differ from prepare_filename's guess.
                if not os.path.exists(filename):
                    base = os.path.splitext(filename)[0]
                    for f in os.listdir(Config.DOWNLOAD_DIR):
                        if f.startswith(os.path.basename(base)):
                            filename = os.path.join(Config.DOWNLOAD_DIR, f)
                            break
                if os.path.exists(filename):
                    logger.info(f"File downloaded successfully to: {filename}")
                else:
                    logger.error(f"Download reported success but file not found: {filename}")
                return filename, info
            except Exception as e:
                logger.error(f"Error during download for {url}: {e}")
                return None, None
