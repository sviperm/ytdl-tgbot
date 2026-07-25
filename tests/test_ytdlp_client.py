import os
from pathlib import Path

from src.services.ytdlp import YtDlpClient, FORMAT, is_auth_error


class FakeYDL:
    """Fake yt_dlp.YoutubeDL context manager."""

    instances = []

    def __init__(self, opts):
        self.opts = opts
        FakeYDL.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=False):
        if url == "boom":
            raise RuntimeError("empty media response")
        if url == "nope":
            raise RuntimeError("Unsupported URL")
        return {"id": "vid1", "extractor": "youtube", "title": "T"}

    def prepare_filename(self, info):
        return os.path.join(os.path.dirname(self.opts["outtmpl"]), "vid1.mp4")


def test_cookiefile_toggles_on_valid_file(tmp_dirs, monkeypatch):
    from src.config import Config
    client = YtDlpClient()
    # no cookies file
    assert client._opts()["cookiefile"] is None
    # a real Netscape cookie line -> picked up live
    open(Config.COOKIES_FILE, "w").write(
        "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tPREF\tval\n"
    )
    assert client._opts()["cookiefile"] == Config.COOKIES_FILE
    assert client._opts()["format"] == FORMAT


def test_malformed_or_empty_cookiefile_is_ignored(tmp_dirs):
    from src.config import Config
    client = YtDlpClient()
    # comment-only / placeholder file -> ignored (this was the stray test leftover)
    open(Config.COOKIES_FILE, "w").write("# cookies")
    assert client._opts()["cookiefile"] is None
    # empty file -> ignored
    open(Config.COOKIES_FILE, "w").write("")
    assert client._opts()["cookiefile"] is None
    # #HttpOnly_ lines are real cookies despite the leading '#'
    open(Config.COOKIES_FILE, "w").write("#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t0\tX\tY\n")
    assert client._opts()["cookiefile"] == Config.COOKIES_FILE


def test_extractor_args_merged_only_when_given(tmp_dirs):
    client = YtDlpClient()
    assert "extractor_args" not in client._opts()
    args = {"youtubepot-bgutilhttp": {"base_url": ["http://x:4416"]}}
    assert client._opts(args)["extractor_args"] == args


def test_outtmpl_only_set_for_a_download(tmp_dirs, tmp_path):
    client = YtDlpClient()
    # extraction writes nothing, so it gets no output template at all
    assert "outtmpl" not in client._opts()
    opts = client._opts(None, str(tmp_path / "job"))
    assert opts["outtmpl"] == os.path.join(str(tmp_path / "job"), "%(id)s.%(ext)s")


def test_extract_info_returns_error_instead_of_storing_it(tmp_dirs, monkeypatch):
    monkeypatch.setattr("src.services.ytdlp.yt_dlp.YoutubeDL", FakeYDL)
    client = YtDlpClient()
    info, error = client._extract_info("boom", None)
    assert info is None
    assert "empty media response" in error
    # nothing about the failure is left on the shared client
    assert not hasattr(client, "last_extract_error")
    info, error = client._extract_info("http://ok", None)
    assert info["id"] == "vid1" and error is None


def test_is_auth_error_heuristic():
    assert is_auth_error("ERROR: Empty media response")
    assert is_auth_error("Sign in to confirm your age")
    assert is_auth_error("This video is private")
    assert not is_auth_error("Unsupported URL: http://x")
    assert not is_auth_error(None)


def test_download_id_prefix_scan_fallback(tmp_dirs, monkeypatch, tmp_path):
    monkeypatch.setattr("src.services.ytdlp.yt_dlp.YoutubeDL", FakeYDL)
    work = tmp_path / "job"
    work.mkdir()
    # prepare_filename returns vid1.mp4 but the real merged file is vid1.mkv
    real = str(work / "vid1.mkv")
    (work / "vid1.mkv").write_bytes(b"data")
    client = YtDlpClient()
    path, info, error = client._download("http://x", str(work))
    assert path == real
    assert info["id"] == "vid1"
    assert error is None


def test_download_scan_never_looks_outside_its_work_dir(tmp_dirs, monkeypatch, tmp_path):
    from src.config import Config
    monkeypatch.setattr("src.services.ytdlp.yt_dlp.YoutubeDL", FakeYDL)
    # another request's leftovers with the same id must not be picked up
    Path(Config.DOWNLOAD_DIR, "vid1.f140.m4a").write_bytes(b"x")
    work = tmp_path / "job"
    work.mkdir()
    client = YtDlpClient()
    path, info, error = client._download("http://x", str(work))
    assert path == str(work / "vid1.mp4")  # nothing matched, guessed name kept
    assert error == "download produced no output file"


def test_download_surfaces_the_failure_reason(tmp_dirs, monkeypatch, tmp_path):
    monkeypatch.setattr("src.services.ytdlp.yt_dlp.YoutubeDL", FakeYDL)
    path, info, error = YtDlpClient()._download("nope", str(tmp_path))
    assert path is None and info is None
    assert "Unsupported URL" in error


def test_download_retries_once_on_a_stale_media_url(tmp_dirs, monkeypatch):
    """A 403 means the signed URL went stale, so a fresh extraction must be tried."""
    from src.config import Config
    client = YtDlpClient()
    calls = []

    def fake_once(url, out_dir, extractor_args=None, progress_hook=None):
        calls.append(url)
        if len(calls) == 1:
            return None, None, "ERROR: unable to download video data: HTTP Error 403: Forbidden"
        return os.path.join(out_dir, "vid1.mp4"), {"id": "vid1"}, None

    monkeypatch.setattr(client, "_download_once", fake_once)
    path, info, error = client._download("http://x", Config.DOWNLOAD_DIR)
    assert len(calls) == 2, "a 403 must trigger exactly one retry"
    assert path.endswith("vid1.mp4") and error is None


def test_download_does_not_retry_a_real_failure(tmp_dirs, monkeypatch):
    from src.config import Config
    client = YtDlpClient()
    calls = []

    def fake_once(url, out_dir, extractor_args=None, progress_hook=None):
        calls.append(url)
        return None, None, "ERROR: Video unavailable"

    monkeypatch.setattr(client, "_download_once", fake_once)
    path, _, error = client._download("http://x", Config.DOWNLOAD_DIR)
    # Retrying a genuinely dead video just doubles the wait before the user hears back.
    assert len(calls) == 1
    assert path is None and "unavailable" in error


def test_download_gives_up_after_the_retry(tmp_dirs, monkeypatch):
    from src.config import Config
    client = YtDlpClient()
    calls = []

    def fake_once(url, out_dir, extractor_args=None, progress_hook=None):
        calls.append(url)
        return None, None, "HTTP Error 403: Forbidden"

    monkeypatch.setattr(client, "_download_once", fake_once)
    path, _, error = client._download("http://x", Config.DOWNLOAD_DIR)
    assert len(calls) == 2, "one retry, not an endless loop"
    assert path is None and "403" in error
