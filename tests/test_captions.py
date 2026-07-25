from src.utils.captions import build_caption, build_ig_caption


def test_build_caption_links_title_and_cleans_url():
    out = build_caption("My Video", "https://youtu.be/x?si=track")
    assert out == '<a href="https://youtu.be/x">My Video</a>'


def test_build_caption_escapes_title():
    out = build_caption('Rock & <b>', "https://youtu.be/x")
    assert "&amp;" in out and "&lt;b&gt;" in out


def test_build_caption_default_title():
    assert build_caption(None, "https://youtu.be/x") == '<a href="https://youtu.be/x">Video</a>'


def test_ig_caption_text_then_link():
    out = build_ig_caption("hello", "https://instagram.com/p/AB/?igsh=zz")
    assert out == 'hello\n\n<a href="https://instagram.com/p/AB/">Instagram</a>'


def test_ig_caption_link_only_when_empty():
    out = build_ig_caption("", "https://instagram.com/p/AB/")
    assert out == '<a href="https://instagram.com/p/AB/">Instagram</a>'


def test_ig_caption_escapes_and_truncates():
    long_text = "a" * 2000
    out = build_ig_caption(long_text, "https://instagram.com/p/AB/")
    assert "…" in out
    # body is truncated to 900 chars + ellipsis, well under Telegram's 1024 cap
    assert out.index("\n\n") <= 901
    assert "&amp;" in build_ig_caption("a & b", "https://instagram.com/p/AB/")
