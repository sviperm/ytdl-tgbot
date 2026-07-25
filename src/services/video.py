"""ffmpeg-based video processing: iOS-compatible transcode, thumbnails, probing."""

import os
import asyncio
import subprocess

from src.utils.logger import logger


class VideoProcessor:
    # PornHub "Community" intro trimming was removed: a precise cut forces a full
    # re-encode that is far too slow on long videos. Recoverable from git history
    # (commits 9f780aa / 1de6158).

    # --- public async API ----------------------------------------------------

    async def process(self, video_path):
        return await asyncio.to_thread(self._process, video_path)

    async def make_thumbnail(self, video_path):
        return await asyncio.to_thread(self._make_thumbnail, video_path)

    async def probe_duration(self, video_path):
        return await asyncio.to_thread(self._probe_duration, video_path)

    async def probe_dimensions(self, video_path):
        return await asyncio.to_thread(self._probe_dimensions, video_path)

    # --- transcode -----------------------------------------------------------

    def _process(self, video_path):
        """Transcode to H.264/AAC/yuv420p if the codec isn't iOS-friendly.

        iOS Telegram can't decode VP9/AV1 (audio plays, video freezes). H.264
        files are returned untouched (no wasteful re-encode).
        """
        vcodec = self._probe_vcodec(video_path)
        if vcodec.startswith("h264") or vcodec.startswith("avc"):
            return video_path  # nothing to do

        out_path = os.path.splitext(video_path)[0] + "_proc.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            out_path,
        ]
        logger.info(
            f"Processing video (transcode {vcodec or 'unknown'}->h264): {video_path}"
        )
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                os.remove(video_path)
                logger.info(f"Processing done: {out_path}")
                return out_path
            logger.error(f"Processing produced no file for {video_path}")
        except Exception as e:
            logger.error(f"Processing failed for {video_path}: {e}")
        return video_path  # fall back to the original on failure

    def _make_thumbnail(self, video_path):
        """Extract a small JPEG frame for Telegram's video preview (<=320px, <=200KB).

        Baked into the uploaded file, so it survives in the cached file_id.
        """
        thumb_path = os.path.splitext(video_path)[0] + "_thumb.jpg"
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", video_path,
                    "-vframes", "1",  # first frame
                    "-vf", "scale=320:320:force_original_aspect_ratio=decrease",
                    thumb_path,
                ],
                check=True, capture_output=True,
            )
            if os.path.isfile(thumb_path) and os.path.getsize(thumb_path) > 0:
                logger.info(f"Generated thumbnail: {thumb_path}")
                return thumb_path
            logger.warning(f"Thumbnail not created for {video_path}")
        except Exception as e:
            logger.warning(f"Thumbnail generation failed for {video_path}: {e}")
        return None

    def _probe_vcodec(self, video_path):
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=codec_name",
                    "-of", "default=noprint_wrappers=1:nokey=1", video_path,
                ],
                check=True, capture_output=True, text=True,
            )
            return result.stdout.strip()
        except Exception as e:
            logger.warning(f"ffprobe failed for {video_path}: {e}")
            return ""

    def _probe_dimensions(self, video_path):
        """(width, height) of the first video stream, (0, 0) if ffprobe can't say.

        Telegram lays the player out from these: sent as 0 it renders a vertical
        reel as a squashed strip. Needed wherever the metadata didn't come from
        yt-dlp — Instagram, whose fetch chain reports no dimensions at all.
        """
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=width,height",
                    "-of", "csv=p=0:s=x", video_path,
                ],
                check=True, capture_output=True, text=True,
            )
            first = (result.stdout.strip().splitlines() or [""])[0]
            width, _, height = first.partition("x")
            return int(width), int(height)
        except Exception as e:
            logger.warning(f"ffprobe dimensions failed for {video_path}: {e}")
            return 0, 0

    def _probe_duration(self, video_path):
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", video_path,
                ],
                check=True, capture_output=True, text=True,
            )
            return int(float(result.stdout.strip() or 0))
        except Exception as e:
            logger.warning(f"ffprobe duration failed for {video_path}: {e}")
            return 0
