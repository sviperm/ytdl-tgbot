import asyncio
from pyrogram.client import Client
from src.config import Config
from src.database.models import Database

from src.utils.logger import logger

# Initialize database
db = Database()


async def main():
    await db.initialize()

    app = Client(
        "ytdl_bot",
        api_id=Config.API_ID,
        api_hash=Config.API_HASH,
        bot_token=Config.BOT_TOKEN,
        plugins=dict(root="src.bot")
    )

    logger.info("Bot is starting...")
    await app.start()
    logger.info("Bot is running!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
