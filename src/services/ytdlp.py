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

# yt-dlp error substrings that mean "login required" rather than "bad link".
_AUTH_MARKERS = (
    "empty media response", "login required", "requires authentication",
    "cookies", "requested content is not available", "rate-limit",
    "sign in", "private",
)


def is_auth_error(message):
    """True when a yt-dlp failure reads like a login wall rather than a bad URL."""
    lowered = (message or "").lower()
    return any(marker in lowered for marker in _AUTH_MARKERS)


# Failures that mean "the signed media URL went stale", not "this video is broken".
_STALE_URL_MARKERS = ("http error 403", "forbidden", "unable to download video data")


def _is_retryable_download_error(message):
    lowered = (message or "").lower()
    return any(marker in lowered for marker in _STALE_URL_MARKERS)


class YtDlpClient:
    """Runs blocking yt-dlp calls off the event loop; cookies are picked up live.

    Stateless on purpose: one instance is shared by every platform and every
    concurrent request, so a failure reason is returned to its own caller instead
    of being parked on the client where a second request would read it.
    """

    def __init__(self):
        if not shutil.which("ffmpeg"):
            logger.error("FFmpeg not found! High-quality downloads will fail. Please install ffmpeg.")

    def _opts(self, extractor_args=None, out_dir=None):
        opts = {
            "format": FORMAT,
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
        if out_dir:
            # Extraction writes nothing, so only a download needs an output path.
            opts["outtmpl"] = os.path.join(out_dir, "%(id)s.%(ext)s")
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
        """Return ``(info, error)``: exactly one of the two is set."""
        return await asyncio.to_thread(self._extract_info, url, extractor_args)

    def _extract_info(self, url, extractor_args):
        with yt_dlp.YoutubeDL(self._opts(extractor_args)) as ydl:
            try:
                logger.info(f"Extracting metadata for: {url}")
                return ydl.extract_info(url, download=False), None
            except Exception as e:
                logger.error(f"Error during metadata extraction for {url}: {e}")
                return None, str(e)

    async def download(self, url, out_dir, extractor_args=None, progress_hook=None):
        """Download into ``out_dir``; returns ``(path, info, error)``."""
        return await asyncio.to_thread(self._download, url, out_dir, extractor_args, progress_hook)

    def _download(self, url, out_dir, extractor_args=None, progress_hook=None):
        """Download, retrying once on an expired/rejected media URL.

        YouTube hands out signed media URLs and answers 403 when one is used a
        moment too late or under bursty access. yt-dlp's own ``retries`` re-requests
        the *same* URL, which stays 403 — only extracting again yields freshly
        signed ones, so a second attempt with a new YoutubeDL is what recovers.
        """
        last_error = None
        for attempt in (1, 2):
            path, info, error = self._download_once(url, out_dir, extractor_args, progress_hook)
            if path:
                return path, info, error
            last_error = error
            if not _is_retryable_download_error(error):
                break
            if attempt == 1:
                logger.warning(f"Retrying {url} with a fresh extraction after: {error}")
        return None, None, last_error

    def _download_once(self, url, out_dir, extractor_args=None, progress_hook=None):
        # Costs a second extraction (network + PO token + latency) on top of the
        # one probe() already did. process_ie_result() would reuse the first
        # result, but it can't be verified without live YouTube, so the duplicate
        # request stays a conscious trade-off.
        opts = self._opts(extractor_args, out_dir)
        if progress_hook:
            opts["progress_hooks"] = [progress_hook]
        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                logger.info(f"Starting actual download for: {url}")
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                # A merged file's extension may differ from prepare_filename's guess.
                # The scan is safe only because out_dir belongs to this request —
                # in a shared directory it would happily match another download's
                # fragments or thumbnail.
                if not os.path.exists(filename):
                    base = os.path.splitext(filename)[0]
                    for f in os.listdir(out_dir):
                        if f.startswith(os.path.basename(base)):
                            filename = os.path.join(out_dir, f)
                            break
                if os.path.exists(filename):
                    logger.info(f"File downloaded successfully to: {filename}")
                    return filename, info, None
                logger.error(f"Download reported success but file not found: {filename}")
                return filename, info, "download produced no output file"
            except Exception as e:
                logger.error(f"Error during download for {url}: {e}")
                return None, None, str(e)
