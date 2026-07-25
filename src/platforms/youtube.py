import re

from src.platforms.ytdlp_base import YtDlpPlatform
from src.config import Config

_RE = re.compile(r"https?://(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)/", re.I)


class YouTubePlatform(YtDlpPlatform):
    name = "youtube"

    def matches(self, url):
        return bool(_RE.match(url or ""))

    @property
    def extractor_args(self):
        # Fetch GVS PO tokens from the bgutil provider to unlock 1080p (SABR).
        return {"youtubepot-bgutilhttp": {"base_url": [Config.POT_PROVIDER_URL]}}
