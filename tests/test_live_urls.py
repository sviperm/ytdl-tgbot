"""Routing and live-service checks over the shared table of real links.

The table itself lives in ``live_links.py`` so the send tier can use the same rows.

Tier 1 (default ``pytest``): offline, credential-free. Routing, ``clean_url``,
PornHub normalization and Instagram shortcode extraction are all pure functions,
so the links are exercised as data without a single request.

Tier 2 (``RUN_NETWORK_TESTS=1 pytest -m network``): probes the live services for
metadata only — never a full download, so the opt-in run stays seconds, not hours.
Its job is to catch what mocks cannot: a service changing shape, or a yt-dlp
format-selector regression that silently drops a vertical video to a squashed
stream (hence the per-format links and the orientation assertion).
"""

import os
from functools import lru_cache

import pytest

from live_env import skip_unless_youtube_env_ready, tcp_reachable
from live_links import INSTAGRAM, TRACKED, URLS, YTDLP_PROBES, ids
from src.config import Config
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
