from types import SimpleNamespace

from src.services.sender import TelegramSender
from src.core.models import Post, PostMeta, MediaItem


class FakeClient:
    def __init__(self):
        self.calls = []

    async def send_video(self, **kw):
        self.calls.append(("video", kw))
        return SimpleNamespace(video=SimpleNamespace(file_id="FID123"))

    async def send_photo(self, **kw):
        self.calls.append(("photo", kw))

    async def send_media_group(self, **kw):
        self.calls.append(("group", kw))


class FakeStatus:
    async def set(self, text):
        pass


def _post(media, meta=None, use_progress=False):
    return Post(
        meta=meta or PostMeta(caption_html="cap", duration=5, width=10, height=20),
        media=media, use_upload_progress=use_progress,
    )


async def test_single_video_returns_file_id_with_progress():
    c = FakeClient()
    post = _post([MediaItem("video", "v.mp4", "t.jpg")], use_progress=True)
    res = await TelegramSender().send_post(c, 1, post, FakeStatus())
    assert res.file_id == "FID123"
    kind, kw = c.calls[0]
    assert kind == "video"
    assert kw["thumb"] == "t.jpg" and kw["caption"] == "cap"
    assert kw["progress"] is not None


async def test_single_video_no_progress_when_flag_false():
    c = FakeClient()
    post = _post([MediaItem("video", "v.mp4")], use_progress=False)
    await TelegramSender().send_post(c, 1, post, FakeStatus())
    assert c.calls[0][1]["progress"] is None


async def test_single_photo_no_file_id():
    c = FakeClient()
    post = _post([MediaItem("image", "i.jpg")])
    res = await TelegramSender().send_post(c, 1, post, FakeStatus())
    assert res.file_id is None
    assert c.calls[0][0] == "photo"


async def test_media_group_chunks_and_caption_on_first_only():
    c = FakeClient()
    media = [MediaItem("image", f"{i}.jpg") for i in range(12)]
    post = _post(media)
    await TelegramSender().send_post(c, 1, post, FakeStatus())
    groups = [kw for kind, kw in c.calls if kind == "group"]
    assert len(groups) == 2                       # 10 + 2
    assert len(groups[0]["media"]) == 10 and len(groups[1]["media"]) == 2
    assert groups[0]["media"][0].caption == "cap"  # caption on first item...
    assert groups[1]["media"][0].caption in ("", None)  # ...only


async def test_media_group_video_thumb_attached():
    c = FakeClient()
    media = [MediaItem("video", "a.mp4", "a_thumb.jpg"), MediaItem("image", "b.jpg")]
    post = _post(media)
    await TelegramSender().send_post(c, 1, post, FakeStatus())
    group = [kw for kind, kw in c.calls if kind == "group"][0]
    assert group["media"][0].thumb == "a_thumb.jpg"
