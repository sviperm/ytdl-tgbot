"""The one table of real links, shared by every live tier.

Three tiers read this file, so a link exists in exactly one place:

- ``test_live_urls.py`` tier 1 — offline: routing, ``clean_url``, ``normalize_url``,
  shortcode extraction. Pure functions, so the links are used as data.
- ``test_live_urls.py`` tier 2 — probes the services for metadata.
- ``test_telegram_send.py`` — takes the ``e2e=True`` rows through the whole
  pipeline into a real Telegram chat.

Adding a service means adding a row, not a test. Live links rot: when one dies,
replace it here.
"""

from dataclasses import dataclass

from src.platforms.generic import GenericPlatform
from src.platforms.instagram import InstagramPlatform
from src.platforms.pornhub import PornHubPlatform
from src.platforms.youtube import YouTubePlatform


@dataclass(frozen=True)
class Link:
    """One real link plus what it is expected to prove.

    ``orientation`` is asserted wherever dimensions are known: from ``probe`` in
    tier 2, and from Telegram's own reply in the send tier. Instagram reports none
    at probe time (probe is pure there), so for those rows tier 2 treats it as
    documentation and the send tier does the real check.

    ``media_types`` is the exact list of items a post must yield. It drives the
    send tier's expectation too: one video -> a video message, one image -> a photo,
    more than one -> an album.
    """

    name: str            # parametrize id
    url: str
    platform: type       # class the production registry must resolve this to
    orientation: str     # "landscape" | "portrait" | "photo" (nothing to orient)
    live_probe: bool = True    # tier 2: await platform.probe(url)
    e2e: bool = False          # send tier: run the full pipeline into Telegram
    tracking_url: str = None   # same link as a user actually shares it (?si=/?igsh=)
    normalized: str = None     # what normalize_url must rewrite the URL to
    shortcode: str = None      # Instagram only: expected extract_shortcode result
    media_types: tuple = ()    # exact media kinds fetch() must return

    @property
    def expects_cache_row(self):
        """Only single yt-dlp videos are cacheable; Instagram sets supports_cache=False."""
        return self.platform is not InstagramPlatform

    @property
    def sends_as(self):
        """What the sender must produce: "video", "photo" or "album"."""
        if len(self.media_types) > 1:
            return "album"
        return self.media_types[0] if self.media_types else "video"


# e2e rows are kept deliberately short (9-22s clips, small carousels): the send
# tier downloads, transcodes and uploads each one for real, so a 10-minute video
# would buy no extra coverage and cost minutes of wall clock. The long links stay
# in the probe tier, where only metadata is fetched.
URLS = [
    # --- YouTube -------------------------------------------------------------
    # Blender Foundation upload, permanent by construction; the source is 4K, so a
    # 1920x1080 probe also proves the format selector's 1080p cap still bites.
    Link(
        name="youtube-landscape-4k-source",
        url="https://youtu.be/aqz-KE-bpKQ",
        platform=YouTubePlatform,
        orientation="landscape",
        tracking_url="https://youtu.be/aqz-KE-bpKQ?si=lIrGXWyKMLmMbtGz",
    ),
    # The link the author used while building the bot: a plain 1080p upload, i.e.
    # the ordinary case where no cap or transcode is involved. Short enough to send.
    Link(
        name="youtube-landscape-plain-1080p",
        url="https://youtu.be/IdyXKJ8NcNI",
        platform=YouTubePlatform,
        orientation="landscape",
        e2e=True,
        media_types=("video",),
    ),
    # /shorts/ URLs are a different path through the extractor and the only YouTube
    # format that must come back taller than it is wide.
    Link(
        name="youtube-shorts-portrait",
        url="https://youtube.com/shorts/L6SiEKv7ziE",
        platform=YouTubePlatform,
        orientation="portrait",
        e2e=True,
        media_types=("video",),
    ),

    # --- PornHub -------------------------------------------------------------
    # Top-rated all-time upload, picked for longevity over anything topical. Not an
    # e2e row: at 8 minutes it would dominate the send tier's runtime.
    Link(
        name="pornhub-landscape",
        url="https://www.pornhub.com/view_video.php?viewkey=ph5e7218510fcd8",
        platform=PornHubPlatform,
        orientation="landscape",
    ),
    # A "shorties" link is the vertical format *and* the only URL shape that needs
    # normalize_url — without the rewrite yt-dlp returns an empty playlist. Sending
    # it end to end is what proves the rewrite survives the whole pipeline.
    Link(
        name="pornhub-shorties-portrait",
        url="https://www.pornhub.com/shorties/6a25b51e258a7",
        platform=PornHubPlatform,
        orientation="portrait",
        e2e=True,
        normalized="https://www.pornhub.com/view_video.php?viewkey=6a25b51e258a7",
        media_types=("video",),
    ),

    # --- Instagram -----------------------------------------------------------
    # A reel: the single-video case, sent as one item. The e2e run is the only test
    # that exercises the fixer's offload host actually serving video bytes.
    Link(
        name="instagram-reel-portrait",
        url="https://www.instagram.com/reel/DZ9sTMZMX7I/",
        platform=InstagramPlatform,
        orientation="portrait",
        live_probe=False,  # probe() is pure for Instagram; fetch() is the live check
        e2e=True,
        tracking_url="https://www.instagram.com/reel/DZ9sTMZMX7I/?igsh=MXBjbHZ2ZW1sMHl4dw==",
        shortcode="DZ9sTMZMX7I",
        media_types=("video",),
    ),
    # A mixed carousel: the sidecar structure the fixer has to reconstruct, and the
    # reason posts are sent as a media group. Post contents are immutable, so the
    # exact item list is a fair invariant — a shrunk list means the parse degraded.
    Link(
        name="instagram-carousel-mixed",
        url="https://www.instagram.com/p/DFYwLR5xReU/",
        platform=InstagramPlatform,
        orientation="portrait",
        live_probe=False,
        e2e=True,
        shortcode="DFYwLR5xReU",
        media_types=("video", "image", "image", "image"),
    ),
    # A single photo post: the image-only branch, which must not be mistaken for a
    # failed video fetch.
    Link(
        name="instagram-single-photo",
        url="https://www.instagram.com/p/DFlc5rYy1XW/",
        platform=InstagramPlatform,
        orientation="photo",
        live_probe=False,
        e2e=True,
        shortcode="DFlc5rYy1XW",
        media_types=("image",),
    ),

    # --- Generic (yt-dlp catch-all) -----------------------------------------
    # VK, one of the sites the README advertises; also yt-dlp's own extractor test
    # link, so it is maintained upstream rather than by us. 9s, so it carries the
    # landscape e2e case cheaply.
    Link(
        name="generic-vk-landscape",
        url="https://vk.com/video205387401_165548505",
        platform=GenericPlatform,
        orientation="landscape",
        e2e=True,
        media_types=("video",),
    ),
    # VK clips are the vertical format on that site — the catch-all has to keep the
    # portrait aspect too, not just the named platforms.
    Link(
        name="generic-vk-clip-portrait",
        url="https://vk.com/clip30014565_456240946",
        platform=GenericPlatform,
        orientation="portrait",
        e2e=True,
        media_types=("video",),
    ),
    # Vimeo, also advertised in the README. Routing is checked, the live probe is
    # not: yt-dlp's Vimeo extractor now demands an OAuth token it cannot get
    # anonymously ("Failed to fetch macos OAuth token: 401"), so a live probe here
    # would be a permanent red that says nothing about this repo. Flip live_probe
    # back on once anonymous Vimeo extraction works again.
    Link(
        name="generic-vimeo-landscape",
        url="https://vimeo.com/76979871",
        platform=GenericPlatform,
        orientation="landscape",
        live_probe=False,
    ),
]

YTDLP_PROBES = [e for e in URLS if e.live_probe]
INSTAGRAM = [e for e in URLS if e.platform is InstagramPlatform]
TRACKED = [e for e in URLS if e.tracking_url]
E2E = [e for e in URLS if e.e2e]


def ids(entries):
    return [e.name for e in entries]
