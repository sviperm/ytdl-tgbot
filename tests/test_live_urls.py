"""The table of real links, one row per service and per format.

Every other test in this suite runs against fakes, so nothing checks that the
real services still answer the way the code expects. This file holds the links —
horizontal video *and* vertical shorts/reels for each service — and uses them at
two levels:

Tier 1 (default ``pytest``): offline, credential-free. Routing, ``clean_url``,
PornHub normalization and Instagram shortcode extraction are all pure functions,
so the links are exercised as data without a single request.

Tier 2 (``RUN_NETWORK_TESTS=1 pytest -m network``): probes the live services for
metadata only — never a full download, so the opt-in run stays minutes, not hours.
Its job is to catch what mocks cannot: a service changing shape, or a yt-dlp
format-selector regression that silently drops a vertical video to a squashed
stream (hence the per-format links and the orientation assertion).

Adding a service means adding a row, not a test. Live links rot: when one dies,
replace it here.
"""

import os
from dataclasses import dataclass
from functools import lru_cache

import pytest

from live_env import skip_unless_youtube_env_ready, tcp_reachable
from src.config import Config
from src.platforms.generic import GenericPlatform
from src.platforms.instagram import InstagramPlatform
from src.platforms.pornhub import PornHubPlatform
from src.platforms.youtube import YouTubePlatform
from src.services.http import HttpClient
from src.services.instagram_client import InstagramClient, extract_shortcode
from src.utils.urls import clean_url

# Tier 2 is opt-in twice over: the marker keeps it out of `pytest -m "not network"`,
# the env var keeps a plain `pytest` (and CI) offline even without the marker.
network = pytest.mark.network
opt_in = pytest.mark.skipif(
    os.getenv("RUN_NETWORK_TESTS") != "1",
    reason="live network test: set RUN_NETWORK_TESTS=1 to run it",
)


@dataclass(frozen=True)
class Link:
    """One real link plus what it is expected to prove.

    ``orientation`` is asserted only for yt-dlp rows, where ``probe`` reports the
    dimensions of the format the selector picked. Instagram never reports them
    (probe is pure and no media is downloaded), so there it is documentation only.
    """

    name: str            # parametrize id
    url: str
    platform: type       # class the production registry must resolve this to
    orientation: str     # "landscape" | "portrait" | "photo" (nothing to orient)
    live_probe: bool = True    # tier 2: await platform.probe(url)
    tracking_url: str = None   # same link as a user actually shares it (?si=/?igsh=)
    normalized: str = None     # what normalize_url must rewrite the URL to
    shortcode: str = None      # Instagram only: expected extract_shortcode result
    media_types: tuple = ()    # Instagram only: exact media kinds fetch() must return


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
    # the ordinary case where no cap or transcode is involved.
    Link(
        name="youtube-landscape-plain-1080p",
        url="https://youtu.be/IdyXKJ8NcNI",
        platform=YouTubePlatform,
        orientation="landscape",
    ),
    # /shorts/ URLs are a different path through the extractor and the only YouTube
    # format that must come back taller than it is wide.
    Link(
        name="youtube-shorts-portrait",
        url="https://youtube.com/shorts/L6SiEKv7ziE",
        platform=YouTubePlatform,
        orientation="portrait",
    ),

    # --- PornHub -------------------------------------------------------------
    # Top-rated all-time upload, picked for longevity over anything topical.
    Link(
        name="pornhub-landscape",
        url="https://www.pornhub.com/view_video.php?viewkey=ph5e7218510fcd8",
        platform=PornHubPlatform,
        orientation="landscape",
    ),
    # A "shorties" link is the vertical format *and* the only URL shape that needs
    # normalize_url — without the rewrite yt-dlp returns an empty playlist.
    Link(
        name="pornhub-shorties-portrait",
        url="https://www.pornhub.com/shorties/6a25b51e258a7",
        platform=PornHubPlatform,
        orientation="portrait",
        normalized="https://www.pornhub.com/view_video.php?viewkey=6a25b51e258a7",
    ),

    # --- Instagram -----------------------------------------------------------
    # A reel: the single-video case, sent as one item.
    Link(
        name="instagram-reel-portrait",
        url="https://www.instagram.com/reel/DZ9sTMZMX7I/",
        platform=InstagramPlatform,
        orientation="portrait",
        live_probe=False,  # probe() is pure for Instagram; fetch() is the live check
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
        shortcode="DFlc5rYy1XW",
        media_types=("image",),
    ),

    # --- Generic (yt-dlp catch-all) -----------------------------------------
    # VK, one of the sites the README advertises; also yt-dlp's own extractor test
    # link, so it is maintained upstream rather than by us.
    Link(
        name="generic-vk-landscape",
        url="https://vk.com/video205387401_165548505",
        platform=GenericPlatform,
        orientation="landscape",
    ),
    # VK clips are the vertical format on that site — the catch-all has to keep the
    # portrait aspect too, not just the named platforms.
    Link(
        name="generic-vk-clip-portrait",
        url="https://vk.com/clip30014565_456240946",
        platform=GenericPlatform,
        orientation="portrait",
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


def ids(entries):
    return [e.name for e in entries]


@lru_cache(maxsize=1)
def _registry():
    """The production registry, so the table is checked against real wiring.

    Imported lazily: the container pulls in pyrogram, and a lazy import keeps a
    breakage there from failing collection of the offline tests.
    """
    from src.container import container

    return container.registry


def _registered_platforms():
    """The registry's platforms in default order."""
    return list(_registry().platforms)


def _resolve(url):
    platform = _registry().resolve(url)
    assert platform is not None, f"no platform resolves {url}"
    return platform


# --- Tier 1: offline ---------------------------------------------------------

@pytest.mark.parametrize("entry", URLS, ids=ids(URLS))
def test_routes_to_expected_platform(entry):
    assert isinstance(_resolve(entry.url), entry.platform)


@pytest.mark.parametrize("entry", URLS, ids=ids(URLS))
def test_clean_url_leaves_real_links_intact(entry):
    # A "cleaner" that mangles a real link breaks the caption and the cache key.
    assert clean_url(entry.url) == entry.url


@pytest.mark.parametrize("entry", TRACKED, ids=ids(TRACKED))
def test_clean_url_strips_tracking_params(entry):
    assert clean_url(entry.tracking_url) == entry.url


def test_table_covers_the_tracking_params_users_actually_send():
    # The two params real shares carry; losing them from the table would quietly
    # stop testing the stripping that captions depend on.
    tracked = " ".join(e.tracking_url for e in TRACKED)
    assert "igsh=" in tracked
    assert "si=" in tracked


@pytest.mark.parametrize("entry", URLS, ids=ids(URLS))
def test_pornhub_normalize_url(entry):
    pornhub = _resolve("https://www.pornhub.com/view_video.php?viewkey=x")
    assert pornhub.normalize_url(entry.url) == (entry.normalized or entry.url)


@pytest.mark.parametrize("entry", INSTAGRAM, ids=ids(INSTAGRAM))
def test_instagram_shortcode(entry):
    assert extract_shortcode(entry.url) == entry.shortcode


def test_every_registered_platform_has_a_link():
    registered = {type(p) for p in _registered_platforms()}
    covered = {e.platform for e in URLS}
    assert not registered - covered, \
        f"no live URL in the table for: {sorted(p.__name__ for p in registered - covered)}"
    assert not covered - registered, \
        f"table row for an unregistered platform: {sorted(p.__name__ for p in covered - registered)}"


# --- Tier 2: live services ---------------------------------------------------

@network
@opt_in
@pytest.mark.parametrize("entry", YTDLP_PROBES, ids=ids(YTDLP_PROBES))
async def test_probe_returns_sane_metadata(entry):
    platform = _resolve(entry.url)
    if isinstance(platform, YouTubePlatform):
        skip_unless_youtube_env_ready()

    meta = await platform.probe(entry.url)

    assert isinstance(meta.title, str) and meta.title.strip(), f"no title for {entry.url}"
    assert meta.video_id, f"no video_id for {entry.url}"
    assert meta.duration > 0, f"no duration for {entry.url}"
    assert meta.width > 0 and meta.height > 0, f"no dimensions for {entry.url}"
    # The point of per-format links: a format selector that quietly falls back to a
    # rotated or squashed stream still returns dimensions, just the wrong ones.
    if entry.orientation == "portrait":
        assert meta.height > meta.width, \
            f"{entry.url} should be vertical, got {meta.width}x{meta.height}"
    elif entry.orientation == "landscape":
        assert meta.width > meta.height, \
            f"{entry.url} should be horizontal, got {meta.width}x{meta.height}"
    else:  # a probed row with no declared orientation would assert nothing
        pytest.fail(f"{entry.name}: orientation must be landscape or portrait")


@network
@opt_in
@pytest.mark.parametrize("entry", INSTAGRAM, ids=ids(INSTAGRAM))
async def test_instagram_fetch_returns_expected_media(entry):
    # fetch() swallows per-method failures and returns None, so reachability is
    # checked up front: after this gate an empty result is a parsing regression,
    # not a dead host, and must fail rather than skip.
    if not tcp_reachable(Config.IG_FIXER_URL, timeout=10):
        pytest.skip(
            f"Instagram fixer host {Config.IG_FIXER_URL} is unreachable; the direct "
            "endpoints additionally need an unblocked IP or IG_PROXY_URL"
        )

    post = await InstagramClient(HttpClient()).fetch(entry.url)

    assert post, f"no post returned for {entry.url}"
    assert post["shortcode"] == entry.shortcode
    assert [item["type"] for item in post["media"]] == list(entry.media_types)
    assert all(item["url"] for item in post["media"]), "media item without a URL"
