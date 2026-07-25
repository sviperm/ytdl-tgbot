import pytest

from src.platforms.registry import PlatformRegistry
from src.platforms.base import Platform
from src.platforms.ytdlp_base import YtDlpPlatform
from src.platforms.instagram import InstagramPlatform
from src.platforms.pornhub import PornHubPlatform
from src.platforms.youtube import YouTubePlatform
from src.platforms.generic import GenericPlatform


@pytest.fixture
def registry():
    # matches() needs no real deps
    return PlatformRegistry([
        InstagramPlatform(None, None),
        PornHubPlatform(None, None),
        YouTubePlatform(None, None),
        GenericPlatform(None, None),
    ])


@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=abc", YouTubePlatform),
    ("https://youtu.be/abc", YouTubePlatform),
    ("https://youtube.com/shorts/L6SiEKv7ziE", YouTubePlatform),
    ("https://www.pornhub.com/view_video.php?viewkey=abc", PornHubPlatform),
    ("https://www.pornhub.com/shorties/6a25b51e258a7", PornHubPlatform),
    ("https://www.instagram.com/reel/DZ9sTMZMX7I/", InstagramPlatform),
    ("https://instagram.com/p/ABC/", InstagramPlatform),
    ("https://vk.com/video123", GenericPlatform),
    ("https://vimeo.com/123", GenericPlatform),
    ("https://www.facebook.com/watch/?v=1", GenericPlatform),
])
def test_resolve(registry, url, expected):
    assert isinstance(registry.resolve(url), expected)


@pytest.mark.parametrize("url", ["not a url", "", None, "ftp://host/f.mp4", " https://youtu.be/x"])
def test_no_match_for_non_http(registry, url):
    assert registry.resolve(url) is None


def test_generic_owns_the_catch_all_name_not_the_base():
    """The shared base used to be named "generic" too, leaving GenericPlatform empty."""
    assert GenericPlatform.name == "generic"
    assert YtDlpPlatform.name not in ("generic", Platform.name)


def test_every_platform_states_an_initial_status(registry):
    # the ABC no longer supplies a default, so each platform must set its own
    assert not hasattr(Platform, "initial_status")
    for platform in registry._platforms:
        assert platform.initial_status
