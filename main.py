import asyncio
import os
import shutil

# Pyrogram 2.0.106 calls asyncio.get_event_loop() at import time. Python 3.14 removed
# the implicit creation of a loop in the main thread, so ensure one exists first.
# This must stay before any import that pulls in pyrogram (incl. src.container).
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from pyrogram.client import Client

from src.config import Config
from src.container import container
from src.utils.logger import logger


def sweep_downloads():
    """Drop anything left in DOWNLOAD_DIR from a previous run.

    Each request works in its own subdirectory that the orchestrator removes when
    it finishes, so at startup the directory should be empty. Whatever is still
    here was orphaned by a SIGKILL mid-download (or by an older version) and would
    otherwise sit on disk forever. Safe because the same bot token can't run twice.
    """
    leftovers = os.listdir(Config.DOWNLOAD_DIR)
    for name in leftovers:
        path = os.path.join(Config.DOWNLOAD_DIR, name)
        try:
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
        except OSError as e:
            logger.warning(f"Could not remove leftover download {path}: {e}")
    if leftovers:
        logger.info(f"Swept {len(leftovers)} leftover download(s) from a previous run")


async def main():
    Config.validate()
    Config.ensure_dirs()
    sweep_downloads()
    await container.db.initialize()

    app = Client(
        "ytdl_bot",
        api_id=Config.API_ID,
        api_hash=Config.API_HASH,
        bot_token=Config.BOT_TOKEN,
        workdir=Config.DATA_DIR,  # keep the .session file in the writable, mounted data dir
        plugins=dict(root="src.bot"),
    )

    logger.info("Bot is starting...")
    await app.start()
    logger.info("Bot is running!")
    try:
        await asyncio.Event().wait()
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        # Ctrl-C / SIGTERM: close the MTProto session cleanly instead of dropping it.
        await app.stop()
        logger.info("Bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
