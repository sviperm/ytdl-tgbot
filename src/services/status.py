"""Thin wrapper over the Pyrogram status message (swallows edit/delete errors)."""


class StatusReporter:
    def __init__(self, message):
        self._message = message

    async def set(self, text):
        try:
            await self._message.edit_text(text)
        except Exception:
            pass  # e.g. "message not modified" / flood wait

    async def done(self):
        try:
            await self._message.delete()
        except Exception:
            pass
