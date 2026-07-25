"""Composition root: builds one shared instance of each service/platform.

Imported by both main.py (for the DB) and bot/handlers.py (for the orchestrator),
so they share the same instances (Python caches the module).
"""

from src.services.ytdlp import YtDlpClient
from src.services.video import VideoProcessor
from src.services.http import HttpClient
from src.services.instagram_client import InstagramClient
from src.services.sender import TelegramSender
from src.platforms.registry import PlatformRegistry
from src.platforms.instagram import InstagramPlatform
from src.platforms.pornhub import PornHubPlatform
from src.platforms.youtube import YouTubePlatform
from src.platforms.generic import GenericPlatform
from src.bot.orchestrator import DownloadOrchestrator
from src.storage.database import Database


class Container:
    def __init__(self):
        self.db = Database()

        ytdlp = YtDlpClient()
        video = VideoProcessor()
        instagram_client = InstagramClient(HttpClient())

        self.sender = TelegramSender()
        self.registry = PlatformRegistry([
            InstagramPlatform(instagram_client, video),   # instagram.com
            PornHubPlatform(ytdlp, video),                # pornhub.com
            YouTubePlatform(ytdlp, video),                # youtube.com / youtu.be
            GenericPlatform(ytdlp, video),                # any other http(s) (last)
        ])
        self.orchestrator = DownloadOrchestrator(self.registry, self.sender, self.db)


container = Container()
