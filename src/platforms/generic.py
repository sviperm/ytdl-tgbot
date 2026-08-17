from src.platforms.ytdlp_base import YtDlpPlatform
from src.services.ytdlp import has_dedicated_extractor


class GenericPlatform(YtDlpPlatform):
    """yt-dlp fallback for any other site (VK, Vimeo, Facebook, ...).

    Inherits matches() (any http/https URL) — must be registered LAST.
    """

    name = "generic"

    def is_media_link(self, url):
        # matches() owns every URL, so only yt-dlp's extractor list narrows it down.
        return has_dedicated_extractor(url)
