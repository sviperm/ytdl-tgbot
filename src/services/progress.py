"""Progress reporters for downloading (yt-dlp) and uploading (Pyrogram)."""

import time
import asyncio


def _mb(n):
    return n / 1024 / 1024


def _bar(pct):
    filled = int(pct / 10)
    return f"[{'#' * filled}{'.' * (10 - filled)}] {pct:.1f}%"


def _block(header, done, total, speed, eta):
    """The shared bar/Size/Speed/ETA body; `total` is 0 when the size is unknown."""
    if total:
        bar = _bar(done * 100 / total)
        size = f"{_mb(done):.1f} / {_mb(total):.1f} MB"
    else:
        bar = "[..........]"
        size = f"{_mb(done):.1f} MB"
    return (
        f"{header}\n\n{bar}\n"
        f"Size: {size}\nSpeed: {_mb(speed):.2f} MB/s\nETA: {int(eta)}s"
    )


def format_download_progress(d, title):
    """Render a yt-dlp progress-hook dict, or None if not actively downloading."""
    if d.get("status") != "downloading":
        return None
    return _block(
        f"Downloading: {title}",
        d.get("downloaded_bytes") or 0,
        d.get("total_bytes") or d.get("total_bytes_estimate") or 0,
        d.get("speed") or 0,
        d.get("eta") or 0,
    )


class _ThreadedProgress:
    """Shared plumbing for download hooks that fire on a worker thread.

    Both downloaders run blocking code via asyncio.to_thread (yt-dlp's hook,
    curl_cffi's chunk callback), so the status edit has to be handed back to the
    bot's loop — and throttled, because both fire many times per second.
    """

    def __init__(self, status, loop, min_interval):
        self._status = status
        self._loop = loop
        self._min_interval = min_interval
        self._last = 0.0

    def _send(self, text):
        now = time.time()
        if now - self._last < self._min_interval:
            return
        self._last = now
        self._emit(text)

    def _emit(self, text):
        try:
            asyncio.run_coroutine_threadsafe(self._status.set(text), self._loop)
        except Exception:
            pass  # loop closed / edit failed — progress is best-effort


class DownloadProgress(_ThreadedProgress):
    """yt-dlp progress hook -> status message."""

    def __init__(self, status, loop, title, min_interval=3.0):
        super().__init__(status, loop, min_interval)
        self._title = title

    def hook(self, d):
        text = format_download_progress(d, self._title)
        if text is None:
            return  # not an active download (a finished/error tick)
        self._send(text)


class FileDownloadProgress(_ThreadedProgress):
    """Plain HTTP byte progress (Instagram) -> status message.

    Callable so it can be passed straight as the ``on_progress`` hook. yt-dlp
    reports speed/ETA itself; here they are derived from the elapsed time.
    """

    def __init__(self, status, loop, header, min_interval=3.0):
        super().__init__(status, loop, min_interval)
        self._header = header
        self._start = time.time()

    def __call__(self, downloaded, total):
        elapsed = time.time() - self._start
        speed = downloaded / elapsed if elapsed > 0 else 0
        eta = (total - downloaded) / speed if speed > 0 and total else 0
        self._send(_block(self._header, downloaded, total, speed, eta))


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
        speed = current / diff
        eta = round((total - current) / speed) if speed > 0 else 0
        await self._status.set(_block("Uploading...", current, total, speed, eta))
