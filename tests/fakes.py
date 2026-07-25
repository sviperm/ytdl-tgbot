"""Canonical test doubles for the suite.

tests/ has no __init__.py, so pytest puts this directory on sys.path and these
are imported as `from fakes import FakeStatus, ...`.
"""

from types import SimpleNamespace


class FakeStatus:
    """Stand-in for StatusReporter."""

    def __init__(self):
        self.texts = []
        self.done_called = False

    async def set(self, text):
        self.texts.append(text)

    async def done(self):
        self.done_called = True


class FakeStatusMessage:
    """Stand-in for the Pyrogram message that StatusReporter edits in place."""

    def __init__(self, text=""):
        self.text = text
        self.edits = [text]
        self.deleted = False

    async def edit_text(self, text, *args, **kwargs):
        self.text = text
        self.edits.append(text)

    async def delete(self):
        self.deleted = True


class FakeChatMessage:
    """Stand-in for the incoming Pyrogram message a handler receives."""

    def __init__(self, text="", user_id=1, chat_id=42):
        self.text = text
        self.chat = SimpleNamespace(id=chat_id)
        self.from_user = SimpleNamespace(id=user_id)
        self.status = None
        self.replies = []

    async def reply_text(self, text):
        self.replies.append(text)
        self.status = FakeStatusMessage(text)
        return self.status


class FakeTelegramClient:
    """Stand-in for the Pyrogram Client's send_* API."""

    def __init__(self):
        self.calls = []

    async def send_video(self, **kw):
        self.calls.append(("video", kw))
        return SimpleNamespace(video=SimpleNamespace(file_id="FID123"))

    async def send_photo(self, **kw):
        self.calls.append(("photo", kw))

    async def send_media_group(self, **kw):
        self.calls.append(("group", kw))
