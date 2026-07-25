from fakes import FakeStatus, FakeTelegramClient

from src.services.sender import TelegramSender
from src.core.models import Post, PostMeta, MediaItem


def _post(media, meta=None):
    return Post(
        meta=meta or PostMeta(caption_html="cap", duration=5, width=10, height=20),
        media=media,
    )


async def test_single_video_returns_file_id_with_progress():
    c = FakeTelegramClient()
    post = _post([MediaItem("video", "v.mp4", "t.jpg")])
    res = await TelegramSender().send_post(c, 1, post, FakeStatus())
    assert res.file_id == "FID123"
    kind, kw = c.calls[0]
    assert kind == "video"
    assert kw["thumb"] == "t.jpg" and kw["caption"] == "cap"
    assert kw["progress"] is not None


async def test_every_single_video_gets_an_upload_bar():
    """Instagram reels went through here with progress=None before."""
    c = FakeTelegramClient()
    status = FakeStatus()
    post = _post([MediaItem("video", "reel.mp4")], meta=PostMeta(platform="instagram"))
    await TelegramSender().send_post(c, 1, post, status)
    assert c.calls[0][1]["progress"] is not None
    assert status.texts == ["Uploading to Telegram..."]


async def test_single_photo_no_file_id():
    c = FakeTelegramClient()
    post = _post([MediaItem("image", "i.jpg")])
    res = await TelegramSender().send_post(c, 1, post, FakeStatus())
    assert res.file_id is None
    assert c.calls[0][0] == "photo"


async def test_media_group_chunks_and_caption_on_first_only():
    c = FakeTelegramClient()
    media = [MediaItem("image", f"{i}.jpg") for i in range(12)]
    post = _post(media)
    await TelegramSender().send_post(c, 1, post, FakeStatus())
    groups = [kw for kind, kw in c.calls if kind == "group"]
    assert len(groups) == 2                       # 10 + 2
    assert len(groups[0]["media"]) == 10 and len(groups[1]["media"]) == 2
    assert groups[0]["media"][0].caption == "cap"  # caption on first item...
    assert groups[0]["media"][1].caption in ("", None)  # ...only
    assert groups[1]["media"][0].caption in ("", None)


async def test_media_group_video_thumb_attached():
    c = FakeTelegramClient()
    media = [MediaItem("video", "a.mp4", "a_thumb.jpg"), MediaItem("image", "b.jpg")]
    post = _post(media)
    await TelegramSender().send_post(c, 1, post, FakeStatus())
    group = [kw for kind, kw in c.calls if kind == "group"][0]
    assert group["media"][0].thumb == "a_thumb.jpg"


async def test_media_group_reports_item_count_from_the_media():
    c = FakeTelegramClient()
    status = FakeStatus()
    post = _post([MediaItem("image", f"{i}.jpg") for i in range(3)])
    await TelegramSender().send_post(c, 1, post, status)
    assert status.texts == ["Uploading 3 items to Telegram..."]


async def test_empty_post_sends_nothing():
    c = FakeTelegramClient()
    res = await TelegramSender().send_post(c, 1, _post([]), FakeStatus())
    assert res.file_id is None and c.calls == []
