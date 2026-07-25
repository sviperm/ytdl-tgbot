from types import SimpleNamespace

import pytest

from fakes import FakeChatMessage

from src.bot import handlers
from src.config import Config


class FakeOrchestrator:
    def __init__(self):
        self.calls = []

    async def handle_url(self, client, message, url):
        self.calls.append((client, message, url))


@pytest.fixture
def orchestrator(monkeypatch):
    """Swap the module-level container for one with a recording orchestrator."""
    fake = FakeOrchestrator()
    monkeypatch.setattr(handlers, "container", SimpleNamespace(orchestrator=fake))
    return fake


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
