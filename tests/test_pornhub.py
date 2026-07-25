from src.platforms.pornhub import PornHubPlatform


def test_shorties_rewritten():
    p = PornHubPlatform(None, None)
    assert p.normalize_url("https://www.pornhub.com/shorties/6a25b51e258a7") == \
        "https://www.pornhub.com/view_video.php?viewkey=6a25b51e258a7"


def test_normal_pornhub_untouched():
    p = PornHubPlatform(None, None)
    url = "https://www.pornhub.com/view_video.php?viewkey=abc123"
    assert p.normalize_url(url) == url


def test_non_pornhub_untouched():
    p = PornHubPlatform(None, None)
    assert p.normalize_url("https://youtu.be/x") == "https://youtu.be/x"
