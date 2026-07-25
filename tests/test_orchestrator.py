import os
import asyncio
from pathlib import Path

from fakes import FakeChatMessage

from src.bot.orchestrator import DownloadOrchestrator
from src.core.models import Post, PostMeta, MediaItem
from src.core.errors import AuthRequiredError
from src.services.sender import SendResult


class FakeRegistry:
    def __init__(self, platform):
        self._platform = platform

    def resolve(self, url):
        return self._platform


class FakePlatform:
    name = "fake"
    initial_status = "Extracting info..."

    def __init__(self, meta, post=None, probe_error=None, fetch_error=None, on_fetch=None):
        self._meta = meta
        self._post = post
        self._err = probe_error
        self._fetch_err = fetch_error
        self._on_fetch = on_fetch
        self.fetched = False
        self.work_dirs = []

    def matches(self, url):
        return True

    async def probe(self, url):
        if self._err:
            raise self._err
        return self._meta

    async def fetch(self, url, meta, status, work_dir):
        self.fetched = True
        self.work_dirs.append(work_dir)
        if self._on_fetch:
            await self._on_fetch(work_dir)
        if self._fetch_err:
            raise self._fetch_err
        return self._post


class FakeDB:
    def __init__(self, existing=None):
        self.store = existing or {}
        self.added = []
        self.get_calls = []

    async def get_file_id(self, platform, video_id):
        self.get_calls.append((platform, video_id))
        return self.store.get((platform, video_id))

    async def add_file_id(self, platform, video_id, file_id, title):
        self.added.append((platform, video_id, file_id, title))


class FakeSender:
    def __init__(self, file_id="FID"):
        self.cached = []
        self.posts = []
        self._file_id = file_id

    async def send_cached_video(self, client, chat_id, file_id, meta):
        self.cached.append(file_id)

    async def send_post(self, client, chat_id, post, status):
        self.posts.append(post)
        return SendResult(file_id=self._file_id)


def _meta(**kw):
    base = dict(video_id="v1", platform="youtube", title="T", caption_html="c", supports_cache=True)
    base.update(kw)
    return PostMeta(**base)


def _orch(platform, sender=None, db=None, max_concurrent=None):
    return DownloadOrchestrator(
        FakeRegistry(platform), sender or FakeSender(), db or FakeDB(), max_concurrent,
    )


async def test_cache_hit_sends_cached_and_skips_fetch(tmp_dirs):
    meta = _meta()
    plat = FakePlatform(meta, post=None)
    db = FakeDB(existing={("youtube", "v1"): "CACHEDFID"})
    sender = FakeSender()
    msg = FakeChatMessage()
    await _orch(plat, sender, db).handle_url(object(), msg, "url")
    assert sender.cached == ["CACHEDFID"]
    assert plat.fetched is False
    assert msg.status.deleted


async def test_cache_hit_creates_no_work_dir(tmp_dirs):
    from src.config import Config
    meta = _meta()
    db = FakeDB(existing={("youtube", "v1"): "CACHEDFID"})
    await _orch(FakePlatform(meta), FakeSender(), db).handle_url(object(), FakeChatMessage(), "url")
    assert os.listdir(Config.DOWNLOAD_DIR) == []


async def test_cache_miss_fetches_sends_and_caches(tmp_dirs):
    meta = _meta()
    post = Post(meta=meta, media=[MediaItem("video", "x.mp4")])
    plat = FakePlatform(meta, post=post)
    db = FakeDB()
    await _orch(plat, FakeSender(file_id="NEWFID"), db).handle_url(object(), FakeChatMessage(), "url")
    assert plat.fetched is True
    assert db.added == [("youtube", "v1", "NEWFID", "T")]


async def test_caches_the_final_meta_not_the_probe_result(tmp_dirs):
    """fetch() may refine the metadata (Instagram fills in the shortcode/title)."""
    probed = _meta(video_id=None, title=None)
    post = Post(meta=_meta(video_id="final", title="Final"), media=[MediaItem("video", "x.mp4")])
    db = FakeDB()
    await _orch(FakePlatform(probed, post=post), FakeSender("F"), db).handle_url(
        object(), FakeChatMessage(), "url")
    assert db.added == [("youtube", "final", "F", "Final")]


async def test_instagram_not_cached(tmp_dirs):
    meta = _meta(video_id="sc", platform="instagram", supports_cache=False)
    post = Post(meta=meta, media=[MediaItem("video", "x.mp4")])
    db = FakeDB()
    await _orch(FakePlatform(meta, post=post), FakeSender(), db).handle_url(
        object(), FakeChatMessage(), "url")
    assert db.get_calls == []      # no cache lookup
    assert db.added == []          # not cached


async def test_auth_error_shows_user_message_and_no_fetch(tmp_dirs):
    plat = FakePlatform(None, probe_error=AuthRequiredError())
    msg = FakeChatMessage()
    await _orch(plat).handle_url(object(), msg, "url")
    assert plat.fetched is False
    assert msg.status.edits[-1] == AuthRequiredError().user_message


async def test_unexpected_error_hides_the_exception_text(tmp_dirs):
    boom = RuntimeError("/home/secret/downloads/leak.mp4 refused by http://10.0.0.1:4416")
    plat = FakePlatform(_meta(supports_cache=False), fetch_error=boom)
    msg = FakeChatMessage()
    await _orch(plat).handle_url(object(), msg, "url")
    last = msg.status.edits[-1]
    assert "secret" not in last and "10.0.0.1" not in last
    assert last == "Something went wrong while handling this link. Please try again."


async def test_work_dir_is_removed_after_a_successful_send(tmp_dirs):
    from src.config import Config

    async def write_file(work_dir):
        Path(work_dir, "v.mp4").write_bytes(b"data")

    meta = _meta()
    plat = FakePlatform(meta, post=Post(meta=meta, media=[MediaItem("video", "v.mp4")]),
                        on_fetch=write_file)
    await _orch(plat).handle_url(object(), FakeChatMessage(), "url")
    assert not os.path.exists(plat.work_dirs[0])
    assert os.listdir(Config.DOWNLOAD_DIR) == []


async def test_work_dir_is_removed_when_fetch_raises_after_writing(tmp_dirs):
    """The P0 leak: files written before the failure used to stay forever."""
    from src.config import Config
    written = {}

    async def write_then_fail(work_dir):
        path = Path(work_dir, "half.part")
        path.write_bytes(b"partial")
        written["path"] = str(path)

    plat = FakePlatform(_meta(), fetch_error=RuntimeError("thumbnail step blew up"),
                        on_fetch=write_then_fail)
    await _orch(plat).handle_url(object(), FakeChatMessage(), "url")
    assert not os.path.exists(written["path"])
    assert not os.path.exists(plat.work_dirs[0])
    assert os.listdir(Config.DOWNLOAD_DIR) == []


async def test_concurrent_requests_get_distinct_work_dirs(tmp_dirs):
    seen = []

    async def record(work_dir):
        seen.append(work_dir)
        await asyncio.sleep(0)  # let the other request interleave

    meta = _meta(supports_cache=False)
    plat = FakePlatform(meta, post=Post(meta=meta, media=[MediaItem("video", "x.mp4")]),
                        on_fetch=record)
    orch = _orch(plat, max_concurrent=2)
    await asyncio.gather(
        orch.handle_url(object(), FakeChatMessage(), "url"),
        orch.handle_url(object(), FakeChatMessage(), "url"),
    )
    assert len(seen) == 2 and seen[0] != seen[1]


async def test_semaphore_serializes_beyond_the_limit(tmp_dirs):
    running = 0
    peak = 0

    async def slow(work_dir):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1

    meta = _meta(supports_cache=False)
    plat = FakePlatform(meta, post=Post(meta=meta, media=[MediaItem("video", "x.mp4")]),
                        on_fetch=slow)
    orch = _orch(plat, max_concurrent=2)
    messages = [FakeChatMessage() for _ in range(5)]
    await asyncio.gather(*(orch.handle_url(object(), m, "url") for m in messages))
    assert peak == 2
    # whoever waited was told so
    assert any("Queued" in edit for m in messages for edit in m.status.edits)


async def test_no_queue_message_when_a_slot_is_free(tmp_dirs):
    meta = _meta(supports_cache=False)
    plat = FakePlatform(meta, post=Post(meta=meta, media=[MediaItem("video", "x.mp4")]))
    msg = FakeChatMessage()
    await _orch(plat, max_concurrent=1).handle_url(object(), msg, "url")
    assert not any("Queued" in edit for edit in msg.status.edits)


async def test_unknown_url_is_ignored(tmp_dirs):
    msg = FakeChatMessage()
    await _orch(None).handle_url(object(), msg, "url")
    assert msg.status is None


# --- integration: real platforms over one shared yt-dlp client ----------------

class SharedYtDlp:
    """One client instance, as the container builds it, for two live requests.

    It also parks the failure on itself the way the old client did, so a platform
    that reads shared state after an await fails this test.
    """

    async def extract_info(self, url, extractor_args=None):
        error = "Sign in to confirm your age" if "auth" in url else "Unsupported URL: nope"
        self.last_extract_error = error
        await asyncio.sleep(0)  # yield: the other request overwrites the field here
        return None, error


async def test_interleaved_probe_errors_dont_bleed_between_requests(tmp_dirs):
    from src.platforms.generic import GenericPlatform
    from src.core.errors import ExtractError

    plat = GenericPlatform(SharedYtDlp(), None)
    orch = _orch(plat, max_concurrent=2)
    gated, broken = FakeChatMessage(), FakeChatMessage()
    await asyncio.gather(
        orch.handle_url(object(), gated, "https://x.test/auth"),
        orch.handle_url(object(), broken, "https://x.test/nope"),
    )
    assert gated.status.edits[-1] == AuthRequiredError().user_message
    assert broken.status.edits[-1] == ExtractError().user_message


class FakeIgClient:
    def __init__(self, media):
        self._media = media
        self.progress_hooks = []

    async def fetch(self, url):
        return {"shortcode": "SC", "caption": "hello", "media": self._media}

    async def download_file(self, url, dest, on_progress=None):
        self.progress_hooks.append(on_progress)
        Path(dest).write_bytes(b"bytes")
        if on_progress:
            on_progress(5, 5)  # fires from a worker thread in production
        return dest


class FakeVideoProcessor:
    async def process(self, path):
        return path

    async def make_thumbnail(self, path):
        return path + "_thumb.jpg"

    async def probe_duration(self, path):
        return 7

    async def probe_dimensions(self, path):
        return 720, 1280   # a reel: portrait


async def _run_instagram(media, tmp_dirs):
    from fakes import FakeTelegramClient
    from src.platforms.instagram import InstagramPlatform
    from src.services.sender import TelegramSender

    ig = FakeIgClient(media)
    plat = InstagramPlatform(ig, FakeVideoProcessor())
    orch = DownloadOrchestrator(FakeRegistry(plat), TelegramSender(), FakeDB(), 2)
    client = FakeTelegramClient()
    await orch.handle_url(client, FakeChatMessage(), "https://www.instagram.com/p/SC/")
    return ig, client


async def test_instagram_carousel_sends_as_a_media_group(tmp_dirs):
    ig, client = await _run_instagram([
        {"type": "image", "url": "http://cdn/1.jpg"},
        {"type": "video", "url": "http://cdn/2.mp4"},
        {"type": "image", "url": "http://cdn/3.jpg"},
    ], tmp_dirs)
    kinds = [kind for kind, _ in client.calls]
    assert kinds == ["group"]
    group = client.calls[0][1]["media"]
    assert len(group) == 3
    assert group[0].caption.startswith("hello")
    # every item was downloaded with a live progress hook
    assert len(ig.progress_hooks) == 3 and all(ig.progress_hooks)


async def test_single_instagram_video_gets_an_upload_bar(tmp_dirs):
    ig, client = await _run_instagram([{"type": "video", "url": "http://cdn/reel.mp4"}], tmp_dirs)
    kind, kw = client.calls[0]
    assert kind == "video"
    assert kw["progress"] is not None      # used to be None for Instagram
    assert ig.progress_hooks[0] is not None


async def test_instagram_video_dimensions_are_probed_off_the_file(tmp_dirs):
    """Instagram's fetch chain reports no dimensions, so they come from ffprobe.

    Sent as 0x0, Telegram renders a vertical reel as a squashed strip.
    """
    _, client = await _run_instagram([{"type": "video", "url": "http://cdn/reel.mp4"}], tmp_dirs)
    _, kw = client.calls[0]
    assert (kw["width"], kw["height"]) == (720, 1280)
    assert kw["duration"] == 7
