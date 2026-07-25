from fakes import FakeStatus

from src.services.progress import (
    UploadProgress, DownloadProgress, FileDownloadProgress, format_download_progress,
)


async def test_throttle_and_final(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr("src.services.progress.time.time", lambda: clock["t"])

    status = FakeStatus()
    clock["t"] = 1000.0
    up = UploadProgress(status)          # _start = 1000

    clock["t"] = 1002.0
    await up.update(50, 100)             # not throttled, diff 2 -> emits
    assert len(status.texts) == 1

    clock["t"] = 1003.0
    await up.update(60, 100)             # within 4s and current<total -> throttled
    assert len(status.texts) == 1

    clock["t"] = 1004.0
    await up.update(100, 100)            # current==total -> always emits
    assert len(status.texts) == 2


async def test_instances_are_independent(monkeypatch):
    clock = {"t": 500.0}
    monkeypatch.setattr("src.services.progress.time.time", lambda: clock["t"])
    a = UploadProgress(FakeStatus())
    b = UploadProgress(FakeStatus())
    assert a._last == 0.0 and b._last == 0.0
    clock["t"] = 510.0
    await a.update(1, 100)
    assert a._last == 510.0 and b._last == 0.0  # b unaffected


async def test_upload_text_shares_the_download_block_format(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr("src.services.progress.time.time", lambda: clock["t"])
    status = FakeStatus()
    up = UploadProgress(status)
    clock["t"] = 10.0                    # 50 MB in 10s -> 5 MB/s, 10s left
    await up.update(50 * 1024 * 1024, 100 * 1024 * 1024)
    text = status.texts[0]
    assert text.startswith("Uploading...\n\n[#####.....] 50.0%")
    assert "Size: 50.0 / 100.0 MB" in text
    assert "Speed: 5.00 MB/s" in text
    assert "ETA: 10s" in text


def test_format_download_progress():
    assert format_download_progress({"status": "finished"}, "T") is None
    text = format_download_progress(
        {"status": "downloading", "downloaded_bytes": 50 * 1024 * 1024,
         "total_bytes": 100 * 1024 * 1024, "speed": 5 * 1024 * 1024, "eta": 10},
        "My Video",
    )
    assert "Downloading: My Video" in text
    assert "50.0%" in text
    assert "5.00 MB/s" in text
    assert "ETA: 10s" in text
    # unknown total -> estimate branch, no crash
    est = format_download_progress(
        {"status": "downloading", "downloaded_bytes": 1024, "total_bytes_estimate": 0}, "T"
    )
    assert "Downloading: T" in est


def test_download_progress_hook_throttles(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr("src.services.progress.time.time", lambda: clock["t"])
    dp = DownloadProgress(status=None, loop=None, title="T", min_interval=3.0)
    emitted = []
    monkeypatch.setattr(dp, "_emit", emitted.append)

    d = {"status": "downloading", "downloaded_bytes": 10, "total_bytes": 100}
    clock["t"] = 100.0
    dp.hook(d)                      # first -> emits
    clock["t"] = 101.0
    dp.hook(d)                      # within 3s -> throttled
    clock["t"] = 104.0
    dp.hook(d)                      # after 3s -> emits
    dp.hook({"status": "finished"})  # non-downloading -> ignored
    assert len(emitted) == 2


def test_file_download_progress_shows_item_counter_and_bar(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr("src.services.progress.time.time", lambda: clock["t"])
    fp = FileDownloadProgress(status=None, loop=None, header="Downloading 2/5")
    emitted = []
    monkeypatch.setattr(fp, "_emit", emitted.append)

    clock["t"] = 10.0                 # 50 MB in 10s -> 5 MB/s, 50 MB left -> 10s
    fp(50 * 1024 * 1024, 100 * 1024 * 1024)
    assert emitted[0].startswith("Downloading 2/5\n\n[#####.....] 50.0%")
    assert "Speed: 5.00 MB/s" in emitted[0]
    assert "ETA: 10s" in emitted[0]


def test_file_download_progress_throttles_and_survives_unknown_total(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr("src.services.progress.time.time", lambda: clock["t"])
    fp = FileDownloadProgress(status=None, loop=None, header="Downloading 1/1")
    emitted = []
    monkeypatch.setattr(fp, "_emit", emitted.append)

    clock["t"] = 10.0
    fp(1024, 0)                       # no Content-Length -> indeterminate bar
    clock["t"] = 11.0
    fp(2048, 0)                       # within 3s -> throttled
    clock["t"] = 14.0
    fp(4096, 0)
    assert len(emitted) == 2
    assert "[..........]" in emitted[0]


def test_file_download_progress_emit_never_raises_without_a_loop():
    """The hook runs on a worker thread; a dead loop must not kill the download."""
    FileDownloadProgress(status=None, loop=None, header="h")(1, 2)
