from src.utils.urls import clean_url


def test_strips_instagram_tracking():
    assert clean_url("https://www.instagram.com/reel/ABC/?igsh=xx") == \
        "https://www.instagram.com/reel/ABC/"
    assert clean_url("https://www.instagram.com/p/ABC/?igsh=xx&img_index=2") == \
        "https://www.instagram.com/p/ABC/"


def test_strips_youtube_si():
    assert clean_url("https://youtu.be/HpEGLBdYcrA?si=track") == "https://youtu.be/HpEGLBdYcrA"


def test_keeps_legit_params():
    assert clean_url("https://youtube.com/watch?v=abc&si=track") == \
        "https://youtube.com/watch?v=abc"


def test_strips_utm_family():
    out = clean_url("https://x.com/p?utm_source=a&utm_medium=b&utm_campaign=c&keep=1")
    assert out == "https://x.com/p?keep=1"


def test_no_query_and_fragment_untouched():
    assert clean_url("https://example.com/path") == "https://example.com/path"
    assert clean_url("https://example.com/p?a=1#frag") == "https://example.com/p?a=1#frag"
