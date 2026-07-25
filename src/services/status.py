"""Thin wrapper over the Pyrogram status message.

Status updates are cosmetic, so failures never propagate — but they are logged,
so a genuinely broken chat (bot blocked, message gone) is still visible in the
log instead of being indistinguishable from the expected editing noise.
"""

from pyrogram.errors import FloodWait, MessageNotModified

from src.utils.logger import logger

# Editing the same text or hitting a rate limit is routine; not worth a warning.
_EXPECTED = (MessageNotModified, FloodWait)


class StatusReporter:
    def __init__(self, message):
        self._message = message

    async def set(self, text):
        try:
            await self._message.edit_text(text)
        except _EXPECTED as e:
            logger.debug(f"Status edit skipped: {type(e).__name__}")
        except Exception as e:
            logger.warning(f"Status edit failed: {type(e).__name__}: {e}")

    async def done(self):
        try:
            await self._message.delete()
        except _EXPECTED as e:
            logger.debug(f"Status delete skipped: {type(e).__name__}")
        except Exception as e:
            logger.warning(f"Status delete failed: {type(e).__name__}: {e}")
