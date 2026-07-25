"""Progress reporters for downloading (yt-dlp) and uploading (Pyrogram)."""

import time
import asyncio


def _bar(pct):
    filled = int(pct / 10)
    return f"[{'#' * filled}{'.' * (10 - filled)}] {pct:.1f}%"


def format_download_progress(d, title):
    """Render a yt-dlp progress-hook dict, or None if not actively downloading."""
    if d.get("status") != "downloading":
        return None
    downloaded = d.get("downloaded_bytes") or 0
    total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
    speed = d.get("speed") or 0
    eta = d.get("eta") or 0
    if total:
        bar = _bar(downloaded * 100 / total)
        size = f"{downloaded / 1024 / 1024:.1f} / {total / 1024 / 1024:.1f} MB"
    else:
        bar = "[..........]"
        size = f"{downloaded / 1024 / 1024:.1f} MB"
    return (
        f"Downloading: {title}\n\n{bar}\n"
        f"Size: {size}\nSpeed: {speed / 1024 / 1024:.2f} MB/s\nETA: {int(eta)}s"
    )


class DownloadProgress:
    """Bridges yt-dlp's sync progress hook (worker thread) to the async status
    message on the main event loop, throttled to avoid Telegram flood waits."""

    def __init__(self, status, loop, title, min_interval=3.0):
        self._status = status
        self._loop = loop
        self._title = title
        self._min_interval = min_interval
        self._last = 0.0

    def hook(self, d):
        if d.get("status") != "downloading":
            return
        now = time.time()
        if now - self._last < self._min_interval:
            return  # throttle: yt-dlp calls this many times per second
        text = format_download_progress(d, self._title)
        if text is None:
            return
        self._last = now
        self._emit(text)

    def _emit(self, text):
        try:
            asyncio.run_coroutine_threadsafe(self._status.set(text), self._loop)
        except Exception:
            pass  # loop closed / edit failed — progress is best-effort


class UploadProgress:
    def __init__(self, status, min_interval=4.0):
        self._status = status
        self._min_interval = min_interval
        self._last = 0.0
        self._start = time.time()

    async def update(self, current, total):
        """Pyrogram progress callback (a bound coroutine method)."""
        now = time.time()
        if now - self._last < self._min_interval and current < total:
            return  # throttle to avoid flood wait
        self._last = now
        diff = now - self._start
        if diff <= 0:
            return
        pct = current * 100 / total
        speed = current / diff
        eta = round((total - current) / speed) if speed > 0 else 0
        bar = f"[{'#' * int(pct / 10)}{'.' * (10 - int(pct / 10))}] {pct:.2f}%"
        await self._status.set(
            f"Uploading...\n\n{bar}\n"
            f"Size: {current / 1024 / 1024:.2f} / {total / 1024 / 1024:.2f} MB\n"
            f"Speed: {speed / 1024 / 1024:.2f} MB/s\n"
            f"ETA: {eta}s"
        )
