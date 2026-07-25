"""Pyrogram message handlers (auto-registered by the plugin root).

Thin: they enforce the whitelist / URL guard and delegate everything else to the
DownloadOrchestrator built in the container.
"""

from pyrogram import Client, filters
from pyrogram.types import Message

from src.config import Config
from src.container import container
from src.utils.logger import logger
from src.utils.urls import is_http_url


@Client.on_message(filters.command("start"))
async def start_handler(client, message):
    await message.reply_text("Send me a video link from YouTube, VK, Vimeo, etc.")


@Client.on_message(filters.text & filters.private)
async def video_link_handler(client: Client, message: Message):
    # from_user is None for some message kinds (e.g. anonymous senders), and an
    # unidentifiable sender can never be on the whitelist.
    user_id = message.from_user.id if message.from_user else None
    if Config.WHITE_LIST and user_id not in Config.WHITE_LIST:
        logger.warning(f"Unauthorized access attempt by user {user_id}")
        await message.reply_text("Sorry, you are not authorized to use this bot.")
        return

    url = message.text
    if not is_http_url(url):
        return

    logger.info(f"New request from user {user_id}: {url}")
    await container.orchestrator.handle_url(client, message, url)
