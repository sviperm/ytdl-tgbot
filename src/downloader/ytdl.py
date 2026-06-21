import yt_dlp
import asyncio
import os
import subprocess
from src.config import Config

from src.utils.logger import logger


class Downloader:
    """Wrapper for yt-dlp to extract info and download videos asynchronously."""

    def __init__(self):
        # Check if ffmpeg is available
        import shutil
        if not shutil.which("ffmpeg"):
            logger.error("FFmpeg not found! High-quality downloads will fail. Please install ffmpeg.")

        self.ydl_opts = {
            # Prefer H.264 (avc1) + AAC: the only codecs iOS/Telegram play everywhere
            # (VP9/AV1 freeze on iOS). Anything else is transcoded after download.
            # Capped at 1080p on the long edge so vertical/shorts keep full resolution.
            # `<=?` keeps formats whose dimensions are unknown (e.g. some non-YouTube sites).
            'format': (
                'bestvideo[vcodec^=avc1][width<=?1920][height<=?1920]+bestaudio[acodec^=mp4a]/'
                'bestvideo[vcodec^=avc1][width<=?1920][height<=?1920]+bestaudio/'
                'bestvideo[width<=?1920][height<=?1920][ext=mp4]+bestaudio[ext=m4a]/'
                'bestvideo[width<=?1920][height<=?1920]+bestaudio/'
                'best[width<=?1920][height<=?1920]/best'
            ),
            'outtmpl': os.path.join(Config.DOWNLOAD_DIR, '%(id)s.%(ext)s'),
            'cookiefile': Config.COOKIES_FILE if os.path.isfile(Config.COOKIES_FILE) else None,
            # 'quiet': True,
            # 'no_warnings': True,
            'extractor_args': {
                # Let yt-dlp use its current default YouTube clients (tv/web_safari) and
                # fetch GVS PO tokens from the bgutil HTTP provider to unlock 1080p.
                'youtubepot-bgutilhttp': {
                    'base_url': [Config.POT_PROVIDER_URL],
                },
            },
        }

    async def extract_info(self, url):
        return await asyncio.to_thread(self._extract_info, url)

    def _extract_info(self, url):
        with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
            try:
                logger.info(f"Extracting metadata for: {url}")
                info = ydl.extract_info(url, download=False)
                return info
            except Exception as e:
                logger.error(f"Error during metadata extraction for {url}: {e}")
                return None

    async def download(self, url):
        return await asyncio.to_thread(self._download, url)

    def _download(self, url):
        with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
            try:
                logger.info(f"Starting actual download for: {url}")
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                # If it's a merged file, the extension might change
                if not os.path.exists(filename):
                    # Try to find the file with any extension but same id
                    base = os.path.splitext(filename)[0]
                    for f in os.listdir(Config.DOWNLOAD_DIR):
                        if f.startswith(os.path.basename(base)):
                            filename = os.path.join(Config.DOWNLOAD_DIR, f)
                            break

                if os.path.exists(filename):
                    logger.info(f"File downloaded successfully to: {filename}")
                else:
                    logger.error(f"Download reported success but file not found: {filename}")

                return filename, info
            except Exception as e:
                logger.error(f"Error during download for {url}: {e}")
                return None, None

    async def make_thumbnail(self, video_path):
        return await asyncio.to_thread(self._make_thumbnail, video_path)

    def _make_thumbnail(self, video_path):
        """Extract a small JPEG frame for Telegram's video preview.

        Telegram bakes the supplied thumb into the uploaded file, so it is
        preserved in the cached file_id and shows up on later cache hits.
        Must be JPEG, <=200KB and <=320px on the longest side.
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
                check=True,
                capture_output=True,
            )
            if os.path.isfile(thumb_path) and os.path.getsize(thumb_path) > 0:
                logger.info(f"Generated thumbnail: {thumb_path}")
                return thumb_path
            logger.warning(f"Thumbnail not created for {video_path}")
        except Exception as e:
            logger.warning(f"Thumbnail generation failed for {video_path}: {e}")
        return None

    async def ensure_compatible(self, video_path):
        return await asyncio.to_thread(self._ensure_compatible, video_path)

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

    def _ensure_compatible(self, video_path):
        """Transcode to H.264/AAC/yuv420p if the video codec isn't iOS-friendly.

        iOS Telegram can't decode VP9/AV1 (audio plays, video freezes), so anything
        that isn't H.264 is re-encoded. H.264 files are returned untouched.
        """
        vcodec = self._probe_vcodec(video_path)
        if vcodec.startswith("h264") or vcodec.startswith("avc"):
            return video_path

        logger.info(f"Transcoding {vcodec or 'unknown'} -> h264 for compatibility: {video_path}")
        out_path = os.path.splitext(video_path)[0] + "_h264.mp4"
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", video_path,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "128k",
                    "-movflags", "+faststart",
                    out_path,
                ],
                check=True, capture_output=True,
            )
            if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                os.remove(video_path)  # replace the original download
                logger.info(f"Transcode done: {out_path}")
                return out_path
            logger.error(f"Transcode produced no file for {video_path}")
        except Exception as e:
            logger.error(f"Transcode failed for {video_path}: {e}")
        return video_path  # fall back to the original on failure
