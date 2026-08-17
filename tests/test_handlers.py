from types import SimpleNamespace

import pytest

from fakes import FakeChatMessage

from src.bot import handlers
from src.config import Config


def _registry():
    from src.platforms.registry import PlatformRegistry
    from src.platforms.instagram import InstagramPlatform
    from src.platforms.pornhub import PornHubPlatform
    from src.platforms.youtube import YouTubePlatform
    from src.platforms.generic import GenericPlatform
    return PlatformRegistry([
        InstagramPlatform(None, None), PornHubPlatform(None, None),
        YouTubePlatform(None, None), GenericPlatform(None, None),
    ])


class FakeOrchestrator:
    def __init__(self):
        self.calls = []

    async def handle_url(self, client, message, url):
        self.calls.append((client, message, url))


@pytest.fixture
def orchestrator(monkeypatch):
    """Recording orchestrator + the real registry (deps unused by is_media_link).

    The whitelist starts open; the tests about it set their own.
    """
    monkeypatch.setattr(Config, "WHITE_LIST", [])
    fake = FakeOrchestrator()
    monkeypatch.setattr(handlers, "container",
                        SimpleNamespace(orchestrator=fake, registry=_registry()))
    return fake


def _urls(orchestrator):
    return [url for _, _, url in orchestrator.calls]


async def test_whitelisted_user_reaches_orchestrator(orchestrator, monkeypatch):
    monkeypatch.setattr(Config, "WHITE_LIST", [7])
    msg = FakeChatMessage("https://youtu.be/x", user_id=7)
    await handlers.video_link_handler("client", msg)
    assert orchestrator.calls == [("client", msg, "https://youtu.be/x")]
    assert msg.replies == []


async def test_non_whitelisted_user_is_refused(orchestrator, monkeypatch):
    monkeypatch.setattr(Config, "WHITE_LIST", [7])
    msg = FakeChatMessage("https://youtu.be/x", user_id=99)
    await handlers.video_link_handler("client", msg)
    assert orchestrator.calls == []
    assert msg.replies == ["Sorry, you are not authorized to use this bot."]


async def test_empty_whitelist_allows_everyone(orchestrator, monkeypatch):
    monkeypatch.setattr(Config, "WHITE_LIST", [])
    msg = FakeChatMessage("https://youtu.be/x", user_id=12345)
    await handlers.video_link_handler("client", msg)
    assert len(orchestrator.calls) == 1


async def test_missing_from_user_is_refused_not_crashed(orchestrator, monkeypatch):
    monkeypatch.setattr(Config, "WHITE_LIST", [7])
    msg = FakeChatMessage("https://youtu.be/x")
    msg.from_user = None
    await handlers.video_link_handler("client", msg)
    assert orchestrator.calls == []
    assert msg.replies == ["Sorry, you are not authorized to use this bot."]


async def test_missing_from_user_passes_with_empty_whitelist(orchestrator, monkeypatch):
    monkeypatch.setattr(Config, "WHITE_LIST", [])
    msg = FakeChatMessage("https://youtu.be/x")
    msg.from_user = None
    await handlers.video_link_handler("client", msg)
    assert len(orchestrator.calls) == 1


async def test_non_http_text_is_ignored_silently(orchestrator, monkeypatch):
    monkeypatch.setattr(Config, "WHITE_LIST", [])
    msg = FakeChatMessage("just chatting")
    await handlers.video_link_handler("client", msg)
    assert orchestrator.calls == []
    assert msg.replies == []


# --- links inside a forwarded post --------------------------------------------

async def test_link_at_the_end_of_a_forwarded_post(orchestrator):
    msg = FakeChatMessage(
        "Миллиардеры никогда не работали? Чем живёт Олег Тиньков "
        "#кирбирева #экономика #работа #зарплата - YouTube "
        "https://m.youtube.com/shorts/xOs8qxm2KOI"
    )
    await handlers.video_link_handler("client", msg)
    assert _urls(orchestrator) == ["https://m.youtube.com/shorts/xOs8qxm2KOI"]


async def test_every_media_link_in_a_post_is_downloaded(orchestrator):
    await handlers.video_link_handler("client", FakeChatMessage(
        "подборка: https://youtu.be/one, потом https://vk.com/video-1_2 и всё"))
    assert _urls(orchestrator) == ["https://youtu.be/one", "https://vk.com/video-1_2"]


async def test_non_media_links_in_a_post_are_skipped(orchestrator):
    """The channel link and the source article must not each produce an error."""
    await handlers.video_link_handler("client", FakeChatMessage(
        "Разбор: https://www.rbc.ru/news/12345 видео https://youtu.be/x "
        "подпишись https://t.me/channelname"))
    assert _urls(orchestrator) == ["https://youtu.be/x"]


async def test_a_hidden_markdown_hyperlink_is_followed(orchestrator):
    msg = FakeChatMessage("смотреть тут", entities=[
        SimpleNamespace(url=None), SimpleNamespace(url="https://youtu.be/hidden"),
    ])
    await handlers.video_link_handler("client", msg)
    assert _urls(orchestrator) == ["https://youtu.be/hidden"]


async def test_a_link_in_a_caption_is_followed(orchestrator):
    """A forwarded post carrying its own photo/video arrives as a caption."""
    msg = FakeChatMessage(text=None, caption="кружок дня https://youtu.be/incaption")
    await handlers.video_link_handler("client", msg)
    assert _urls(orchestrator) == ["https://youtu.be/incaption"]


async def test_a_lone_unknown_link_is_still_attempted(orchestrator):
    """Today's behaviour for a pasted link: an exotic site gets its chance."""
    await handlers.video_link_handler("client", FakeChatMessage("https://exotic.test/clip/1"))
    assert _urls(orchestrator) == ["https://exotic.test/clip/1"]


async def test_a_post_full_of_unknown_links_is_ignored(orchestrator):
    await handlers.video_link_handler("client", FakeChatMessage(
        "читайте https://www.rbc.ru/news/1 и https://telegra.ph/Post-01-01"))
    assert orchestrator.calls == []
