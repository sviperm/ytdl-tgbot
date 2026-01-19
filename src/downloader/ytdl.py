import yt_dlp
import asyncio
import os
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
            # Best quality mp4 merged with m4a audio
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': os.path.join(Config.DOWNLOAD_DIR, '%(id)s.%(ext)s'),
            'cookiefile': Config.COOKIES_FILE if os.path.exists(Config.COOKIES_FILE) else None,
            'quiet': True,
            'no_warnings': True,
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
