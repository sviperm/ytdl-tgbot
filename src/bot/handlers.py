"""Pyrogram message handlers (auto-registered by the plugin root).

Thin: they enforce the whitelist / URL guard and delegate everything else to the
DownloadOrchestrator built in the container.
"""

from pyrogram import Client, filters
from pyrogram.types import Message

from src.config import Config
from src.container import container
from src.utils.logger import logger


@Client.on_message(filters.command("start"))
async def start_handler(client, message):
    await message.reply_text("Send me a video link from YouTube, VK, Vimeo, etc.")


@Client.on_message(filters.text & filters.private)
async def video_link_handler(client: Client, message: Message):
    if Config.WHITE_LIST and message.from_user.id not in Config.WHITE_LIST:
        logger.warning(f"Unauthorized access attempt by user {message.from_user.id}")
        await message.reply_text("Sorry, you are not authorized to use this bot.")
        return

    url = message.text
    if not (url.startswith("http://") or url.startswith("https://")):
        return

    logger.info(f"New request from user {message.from_user.id}: {url}")
    await container.orchestrator.handle_url(client, message, url)
