from types import SimpleNamespace

from src.bot.orchestrator import DownloadOrchestrator
from src.core.models import Post, PostMeta, MediaItem
from src.core.errors import AuthRequiredError
from src.services.sender import SendResult


class FakeStatusMsg:
    def __init__(self, text):
        self.edits = [text]
        self.deleted = False

    async def edit_text(self, text):
        self.edits.append(text)

    async def delete(self):
        self.deleted = True


class FakeMessage:
    def __init__(self):
        self.chat = SimpleNamespace(id=42)
        self.status = None

    async def reply_text(self, text):
        self.status = FakeStatusMsg(text)
        return self.status


class FakeRegistry:
    def __init__(self, platform):
        self._platform = platform

    def resolve(self, url):
        return self._platform


class FakePlatform:
    name = "fake"
    initial_status = "Extracting info..."

    def __init__(self, meta, post=None, probe_error=None):
        self._meta = meta
        self._post = post
        self._err = probe_error
        self.fetched = False

    def matches(self, url):
        return True

    async def probe(self, url):
        if self._err:
            raise self._err
        return self._meta

    async def fetch(self, url, meta, status):
        self.fetched = True
        return self._post


class FakeDB:
    def __init__(self, existing=None):
        self.store = existing or {}
        self.added = []
        self.get_calls = []

    async def get_video(self, video_id):
        self.get_calls.append(video_id)
        return self.store.get(video_id)

    async def add_video(self, video_id, platform, file_id, title):
        self.added.append((video_id, file_id))


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


async def test_cache_hit_sends_cached_and_skips_fetch():
    meta = _meta()
    plat = FakePlatform(meta, post=None)
    db = FakeDB(existing={"v1": "CACHEDFID"})
    sender = FakeSender()
    orch = DownloadOrchestrator(FakeRegistry(plat), sender, db)
    msg = FakeMessage()
    await orch.handle_url(object(), msg, "url")
    assert sender.cached == ["CACHEDFID"]
    assert plat.fetched is False
    assert msg.status.deleted


async def test_cache_miss_fetches_sends_and_caches():
    meta = _meta()
    post = Post(meta=meta, media=[MediaItem("video", "x.mp4")], use_upload_progress=True)
    plat = FakePlatform(meta, post=post)
    db = FakeDB()
    sender = FakeSender(file_id="NEWFID")
    orch = DownloadOrchestrator(FakeRegistry(plat), sender, db)
    await orch.handle_url(object(), FakeMessage(), "url")
    assert plat.fetched is True
    assert sender.posts == [post]
    assert db.added == [("v1", "NEWFID")]


async def test_instagram_not_cached():
    meta = _meta(video_id="sc", platform="instagram", supports_cache=False)
    post = Post(meta=meta, media=[MediaItem("video", "x.mp4")])
    plat = FakePlatform(meta, post=post)
    db = FakeDB()
    orch = DownloadOrchestrator(FakeRegistry(plat), FakeSender(), db)
    await orch.handle_url(object(), FakeMessage(), "url")
    assert db.get_calls == []      # no cache lookup
    assert db.added == []          # not cached


async def test_auth_error_shows_user_message_and_no_fetch():
    plat = FakePlatform(None, probe_error=AuthRequiredError())
    orch = DownloadOrchestrator(FakeRegistry(plat), FakeSender(), FakeDB())
    msg = FakeMessage()
    await orch.handle_url(object(), msg, "url")
    assert plat.fetched is False
    assert msg.status.edits[-1] == AuthRequiredError().user_message


async def test_cleanup_removes_temp_files(tmp_path):
    f = tmp_path / "x.mp4"
    f.write_bytes(b"data")
    meta = _meta()
    post = Post(meta=meta, media=[MediaItem("video", str(f), None)])
    plat = FakePlatform(meta, post=post)
    orch = DownloadOrchestrator(FakeRegistry(plat), FakeSender(), FakeDB())
    await orch.handle_url(object(), FakeMessage(), "url")
    assert not f.exists()
