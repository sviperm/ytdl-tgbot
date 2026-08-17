"""Pyrogram message handlers (auto-registered by the plugin root).

Thin: they enforce the whitelist, pick which links in a message are worth acting
on, and delegate everything else to the DownloadOrchestrator in the container.
"""

from pyrogram import Client, filters
from pyrogram.types import Message

from src.config import Config
from src.container import container
from src.utils.logger import logger
from src.utils.urls import extract_urls


def _hidden_urls(message):
    """Hrefs of hyperlinks whose URL is not in the text — only text_link has one."""
    entities = message.entities or message.caption_entities or []
    return [entity.url for entity in entities if getattr(entity, "url", None)]


def _targets(urls):
    """Which links to download: the media ones, or a lone link at face value.

    A post also holds a source article and a channel link, and acting on those
    would mean an error message per unrelated link.
    """
    media = [url for url in urls if container.registry.is_media_link(url)]
    if media:
        return media
    return urls[:1] if len(urls) == 1 else []


@Client.on_message(filters.command("start"))
async def start_handler(client, message):
    await message.reply_text("Send me a video link from YouTube, VK, Vimeo, etc.")


@Client.on_message((filters.text | filters.caption) & filters.private)
async def video_link_handler(client: Client, message: Message):
    # from_user is None for some message kinds (e.g. anonymous senders), and an
    # unidentifiable sender can never be on the whitelist.
    user_id = message.from_user.id if message.from_user else None
    if Config.WHITE_LIST and user_id not in Config.WHITE_LIST:
        logger.warning(f"Unauthorized access attempt by user {user_id}")
        await message.reply_text("Sorry, you are not authorized to use this bot.")
        return

    # A forwarded post carrying its own media arrives as a caption, not text.
    urls = extract_urls(message.text or message.caption, _hidden_urls(message))
    targets = _targets(urls)
    if not targets:
        return

    logger.info(f"New request from user {user_id}: {targets} (of {len(urls)} link(s))")
    for url in targets:
        await container.orchestrator.handle_url(client, message, url)
