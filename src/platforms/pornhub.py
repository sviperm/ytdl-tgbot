import re

from src.platforms.ytdlp_base import YtDlpPlatform

_RE = re.compile(r"https?://(?:www\.)?pornhub\.com/", re.I)
_SHORTIES = re.compile(r"https?://(?:www\.)?pornhub\.com/shorties/([0-9a-zA-Z]+)")


class PornHubPlatform(YtDlpPlatform):
    name = "pornhub"

    def matches(self, url):
        return bool(_RE.match(url or ""))

    def normalize_url(self, url):
        # A 'shorties/<id>' link is caught by yt-dlp's paged-list extractor and
        # yields an empty playlist; the single-video form downloads correctly.
        m = _SHORTIES.match(url or "")
        if m:
            return f"https://www.pornhub.com/view_video.php?viewkey={m.group(1)}"
        return url
