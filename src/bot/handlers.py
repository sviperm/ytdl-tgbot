import os
import time
import html
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message
from src.downloader.ytdl import Downloader
from src.database.models import Database
from src.config import Config
from src.utils.logger import logger

downloader = Downloader()
db = Database()


def build_caption(title, url):
    """Caption with the title as a clickable link back to the source video."""
    safe_title = html.escape(title or "Video")
    safe_url = html.escape(url, quote=True)
    return f'<a href="{safe_url}">{safe_title}</a>'

# Track the last update time globally for this upload
last_update_time = 0

async def progress(current, total, message, start_time):
    global last_update_time
    now = time.time()
    
    # Only update every 4 seconds to avoid flood wait
    if now - last_update_time < 4 and current < total:
        return
        
    last_update_time = now
    
    diff = now - start_time
    if diff <= 0:
        return
    
    percentage = current * 100 / total
    speed = current / diff
    elapsed_time = round(diff)
    eta = round((total - current) / speed) if speed > 0 else 0
    
    progress_str = f"[{'#' * int(percentage/10)}{'.' * (10 - int(percentage/10))}] {percentage:.2f}%"
    
    try:
        await message.edit_text(
            f"Uploading...\n\n{progress_str}\n"
            f"Size: {current/1024/1024:.2f} / {total/1024/1024:.2f} MB\n"
            f"Speed: {speed/1024/1024:.2f} MB/s\n"
            f"ETA: {eta}s"
        )
    except Exception:
        # Ignore errors during progress updates (e.g. message not modified or flood wait)
        pass

@Client.on_message(filters.command("start"))
async def start_handler(client, message):
    await message.reply_text("Send me a video link from YouTube, VK, Vimeo, etc.")

@Client.on_message(filters.text & filters.private)
async def video_link_handler(client: Client, message: Message):
    # Whitelist check
    if Config.WHITE_LIST and message.from_user.id not in Config.WHITE_LIST:
        logger.warning(f"Unauthorized access attempt by user {message.from_user.id}")
        await message.reply_text("Sorry, you are not authorized to use this bot.")
        return

    url = message.text
    if not (url.startswith("http://") or url.startswith("https://")):
        return

    logger.info(f"New request from user {message.from_user.id}: {url}")
    status_message = await message.reply_text("Extracting info...")
    
    info = await downloader.extract_info(url)
    if not info:
        logger.error(f"Failed to extract info for URL: {url}")
        await status_message.edit_text("Failed to extract video info. Are you sure the link is valid?")
        return

    video_id = info.get('id')
    platform = info.get('extractor')
    title = info.get('title')
    duration = int(info.get('duration', 0))
    width = int(info.get('width', 0))
    height = int(info.get('height', 0))

    logger.info(f"Extracted: {title} ({platform}) - {width}x{height} - Duration: {duration}s")

    # Check database
    cached_file_id = await db.get_video(video_id)
    if cached_file_id:
        logger.info(f"Cache hit for video {video_id}. Sending cached file.")
        await status_message.edit_text("Video found in cache! Sending...")
        try:
            await client.send_video(
                chat_id=message.chat.id,
                video=cached_file_id,
                caption=build_caption(title, url),
                parse_mode=ParseMode.HTML,
                duration=duration,
                width=width,
                height=height,
                supports_streaming=True
            )
            logger.info(f"Cached video {video_id} sent successfully to user {message.from_user.id}")
            await status_message.delete()
            return
        except Exception as e:
            logger.warning(f"Failed to send cached video {video_id}: {str(e)}. Redownloading...")
            await status_message.edit_text("Cache invalid. Redownloading...")

    await status_message.edit_text(f"Downloading: {title}")
    logger.info(f"Starting download: {title} ({url})")
    file_path, info = await downloader.download(url)
    
    if not file_path or not os.path.exists(file_path):
        logger.error(f"Download failed for URL: {url}")
        await status_message.edit_text("Download failed.")
        return

    # Update width/height if info changed after download
    if info:
        width = int(info.get('width', width))
        height = int(info.get('height', height))
        duration = int(info.get('duration', duration))

    file_size = os.path.getsize(file_path) / (1024 * 1024)
    logger.info(f"Download finished: {file_path} ({file_size:.2f} MB)")

    # Generate a thumbnail so the preview is baked into the file_id (and survives caching)
    thumb_path = await downloader.make_thumbnail(file_path)

    await status_message.edit_text("Uploading to Telegram...")
    global last_update_time
    last_update_time = 0
    start_time = time.time()

    logger.info(f"Starting upload to Telegram: {title} ({file_size:.2f} MB)")
    try:
        sent_video = await client.send_video(
            chat_id=message.chat.id,
            video=file_path,
            caption=build_caption(title, url),
            parse_mode=ParseMode.HTML,
            thumb=thumb_path,
            duration=duration,
            width=width,
            height=height,
            supports_streaming=True,
            progress=progress,
            progress_args=(status_message, start_time)
        )

        await db.add_video(video_id, platform, sent_video.video.file_id, title)
        logger.info(f"Upload successful: {title} (ID: {sent_video.video.file_id})")
        await status_message.delete()
    except Exception as e:
        logger.error(f"Upload failed for {title}: {str(e)}")
        await status_message.edit_text(f"Upload failed: {str(e)}")
    finally:
        for path in (file_path, thumb_path):
            if path and os.path.exists(path):
                os.remove(path)
                logger.info(f"Cleaned up local file: {path}")
