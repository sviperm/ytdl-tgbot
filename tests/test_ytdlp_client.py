import os

from src.services.ytdlp import YtDlpClient, FORMAT


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
        return {"id": "vid1", "extractor": "youtube", "title": "T"}

    def prepare_filename(self, info):
        return os.path.join(self.opts["outtmpl"].rsplit("/", 1)[0], "vid1.mp4")


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


def test_extract_info_records_error(tmp_dirs, monkeypatch):
    monkeypatch.setattr("src.services.ytdlp.yt_dlp.YoutubeDL", FakeYDL)
    client = YtDlpClient()
    assert client._extract_info("boom", None) is None
    assert "empty media response" in client.last_extract_error


def test_download_id_prefix_scan_fallback(tmp_dirs, monkeypatch):
    from src.config import Config
    monkeypatch.setattr("src.services.ytdlp.yt_dlp.YoutubeDL", FakeYDL)
    # prepare_filename returns vid1.mp4 but the real merged file is vid1.mkv
    real = os.path.join(Config.DOWNLOAD_DIR, "vid1.mkv")
    open(real, "wb").write(b"data")
    client = YtDlpClient()
    path, info = client._download("http://x", None)
    assert path == real
    assert info["id"] == "vid1"
