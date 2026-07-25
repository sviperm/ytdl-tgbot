"""Sends a prepared Post to Telegram (single item or media group)."""

from dataclasses import dataclass
from typing import Optional

from pyrogram.enums import ParseMode
from pyrogram.types import InputMediaPhoto, InputMediaVideo

from src.services.progress import UploadProgress

_MEDIA_GROUP_LIMIT = 10  # Telegram max items per media group


@dataclass
class SendResult:
    file_id: Optional[str] = None  # set only for a cacheable single video


class TelegramSender:
    async def send_cached_video(self, client, chat_id, file_id, meta):
        await client.send_video(
            chat_id=chat_id, video=file_id, caption=meta.caption_html,
            parse_mode=ParseMode.HTML, duration=meta.duration,
            width=meta.width, height=meta.height, supports_streaming=True,
        )

    async def send_post(self, client, chat_id, post, status):
        media = post.media
        caption = post.meta.caption_html
        if not media:
            return SendResult()

        if len(media) == 1:
            await status.set("Uploading to Telegram...")
            return await self._send_single(client, chat_id, media[0], caption, post, status)
        # Pyrogram 2.0.106's send_media_group takes no progress callback, so a group
        # upload can only announce that it started.
        await status.set(f"Uploading {len(media)} items to Telegram...")
        return await self._send_group(client, chat_id, media, caption)

    async def _send_single(self, client, chat_id, item, caption, post, status):
        if item.kind == "video":
            progress = UploadProgress(status).update
            sent = await client.send_video(
                chat_id=chat_id, video=item.path, caption=caption, parse_mode=ParseMode.HTML,
                thumb=item.thumb, duration=post.meta.duration,
                width=post.meta.width, height=post.meta.height,
                supports_streaming=True, progress=progress,
            )
            return SendResult(file_id=self._video_file_id(sent))
        await client.send_photo(
            chat_id=chat_id, photo=item.path, caption=caption, parse_mode=ParseMode.HTML,
        )
        return SendResult()

    async def _send_group(self, client, chat_id, media, caption):
        group = []
        for index, item in enumerate(media):
            # Telegram shows the album caption from its first item, so only that
            # one carries it.
            text = caption if index == 0 else ""
            if item.kind == "video":
                group.append(InputMediaVideo(
                    item.path, thumb=item.thumb, caption=text,
                    parse_mode=ParseMode.HTML, supports_streaming=True,
                ))
            else:
                group.append(InputMediaPhoto(item.path, caption=text, parse_mode=ParseMode.HTML))
        for start in range(0, len(group), _MEDIA_GROUP_LIMIT):
            await client.send_media_group(
                chat_id=chat_id, media=group[start:start + _MEDIA_GROUP_LIMIT],
            )
        return SendResult()

    @staticmethod
    def _video_file_id(sent):
        try:
            return sent.video.file_id
        except Exception:
            return None
