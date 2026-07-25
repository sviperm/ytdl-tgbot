from src.platforms.ytdlp_base import YtDlpPlatform


class GenericPlatform(YtDlpPlatform):
    """yt-dlp fallback for any other site (VK, Vimeo, Facebook, ...).

    Inherits matches() (any http/https URL) — must be registered LAST.
    """

    name = "generic"
