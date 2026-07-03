import os
import time
import html
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message, InputMediaPhoto, InputMediaVideo
from src.downloader.ytdl import Downloader
from src.downloader import instagram
from src.database.models import Database
from src.config import Config
from src.utils.logger import logger

downloader = Downloader()
db = Database()


# Query params that are pure tracking; stripped from source links in captions.
_TRACKING_PARAMS = {
    "igsh", "igshid", "img_index", "si", "feature",
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
}


def clean_url(url):
    """Drop tracking query params (igsh, img_index, utm_*, ...) from a URL."""
    parts = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in _TRACKING_PARAMS]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


def build_caption(title, url):
    """Caption with the title as a clickable link back to the source video."""
    safe_title = html.escape(title or "Video")
    safe_url = html.escape(clean_url(url), quote=True)
    return f'<a href="{safe_url}">{safe_title}</a>'


def build_ig_caption(caption_text, url):
    """Media-group caption: a source link plus the post's caption (Telegram cap 1024)."""
    link = f'<a href="{html.escape(clean_url(url), quote=True)}">Instagram</a>'
    if not caption_text:
        return link
    body = caption_text[:900].rstrip()
    if len(caption_text) > 900:
        body += "…"
    return f"{html.escape(body)}\n\n{link}"


async def handle_instagram(client: Client, message: Message, url: str):
    """Fetch a public Instagram post (single or carousel) and send it as media."""
    status = await message.reply_text("Fetching Instagram post...")
    post = await instagram.fetch(url)
    if not post or not post.get("media"):
        logger.error(f"Instagram fetch returned nothing for {url}")
        await status.edit_text(
            "🔒 Couldn't fetch this Instagram post. It may be private/deleted, "
            "or its video is login-gated from this server's IP."
        )
        return

    media = post["media"]
    caption = build_ig_caption(post.get("caption") or "", url)
    logger.info(f"Instagram {post['shortcode']}: {len(media)} item(s)")
    files = []   # (kind, path)
    thumbs = []
    try:
        await status.edit_text(f"Downloading {len(media)} item(s)...")
        for i, item in enumerate(media):
            ext = ".mp4" if item["type"] == "video" else ".jpg"
            dest = os.path.join(Config.DOWNLOAD_DIR, f"{post['shortcode']}_{i}{ext}")
            await instagram.download_file(item["url"], dest)
            if item["type"] == "video":
                dest = await downloader.process_video(dest)  # H.264 for iOS + faststart
            files.append((item["type"], dest))

        await status.edit_text("Uploading...")
        if len(files) == 1:
            kind, path = files[0]
            if kind == "video":
                thumb = await downloader.make_thumbnail(path)
                if thumb:
                    thumbs.append(thumb)
                await client.send_video(
                    message.chat.id, path, caption=caption, parse_mode=ParseMode.HTML,
                    thumb=thumb, supports_streaming=True,
                )
            else:
                await client.send_photo(
                    message.chat.id, path, caption=caption, parse_mode=ParseMode.HTML,
                )
        else:
            group = []
            for kind, path in files:
                if kind == "video":
                    thumb = await downloader.make_thumbnail(path)
                    if thumb:
                        thumbs.append(thumb)
                    group.append(InputMediaVideo(path, thumb=thumb, supports_streaming=True))
                else:
                    group.append(InputMediaPhoto(path))
            # Telegram allows max 10 items per group; caption goes on the first item.
            first = True
            for start in range(0, len(group), 10):
                chunk = group[start:start + 10]
                if first:
                    chunk[0].caption = caption
                    chunk[0].parse_mode = ParseMode.HTML
                    first = False
                await client.send_media_group(message.chat.id, chunk)
        await status.delete()
        logger.info(f"Instagram post {post['shortcode']} sent ({len(files)} item(s))")
    except Exception as e:
        logger.error(f"Instagram handling failed for {url}: {e}")
        await status.edit_text(f"Failed to send Instagram post: {e}")
    finally:
        for _, path in files:
            if path and os.path.exists(path):
                os.remove(path)
        for thumb in thumbs:
            if thumb and os.path.exists(thumb):
                os.remove(thumb)

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

    # Instagram posts (carousels/photos/reels) go through the no-login module,
    # which sends the whole post as a media group with its caption.
    if instagram.is_instagram_url(url):
        await handle_instagram(client, message, url)
        return

    status_message = await message.reply_text("Extracting info...")

    info = await downloader.extract_info(url)
    if not info:
        logger.error(f"Failed to extract info for URL: {url}")
        err = (downloader.last_extract_error or "").lower()
        auth_markers = ("empty media response", "login required", "requires authentication",
                        "cookies", "requested content is not available", "rate-limit",
                        "sign in", "private")
        if any(m in err for m in auth_markers):
            await status_message.edit_text(
                "🔒 This post requires login (e.g. Instagram now needs it) and can't be downloaded without an authenticated cookies file."
            )
        else:
            await status_message.edit_text("Failed to extract video info. Are you sure the link is valid?")
        return

    video_id = info.get('id')
    platform = info.get('extractor')
    title = info.get('title')
    # `or 0` guards against keys present with a None value (e.g. PornHub width)
    duration = int(info.get('duration') or 0)
    width = int(info.get('width') or 0)
    height = int(info.get('height') or 0)

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
        width = int(info.get('width') or width)
        height = int(info.get('height') or height)
        duration = int(info.get('duration') or duration)

    # Trim a detected PornHub intro and/or transcode to H.264 (VP9/AV1 won't play on iOS)
    await status_message.edit_text("Processing video...")
    file_path = await downloader.process_video(file_path)
    # Duration may have changed if an intro was trimmed — re-probe for an accurate value
    probed_duration = await downloader.probe_duration(file_path)
    if probed_duration:
        duration = probed_duration

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
