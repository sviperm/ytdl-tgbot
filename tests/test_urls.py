from src.utils.urls import clean_url, is_http_url, extract_urls


def test_is_http_url_accepts_http_and_https():
    assert is_http_url("http://example.com")
    assert is_http_url("https://example.com/p?a=1")


def test_is_http_url_rejects_everything_else():
    assert not is_http_url("")
    assert not is_http_url(None)
    assert not is_http_url("example.com")
    assert not is_http_url("ftp://example.com")
    assert not is_http_url("  https://example.com")  # leading space is not a URL
    assert not is_http_url(b"https://example.com")


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


# --- extract_urls -------------------------------------------------------------

def test_extracts_a_link_from_a_forwarded_post():
    text = ("Миллиардеры никогда не работали? Чем живёт Олег Тиньков "
            "#кирбирева #экономика #работа #зарплата - YouTube "
            "https://m.youtube.com/shorts/xOs8qxm2KOI")
    assert extract_urls(text) == ["https://m.youtube.com/shorts/xOs8qxm2KOI"]


def test_extracts_every_link_in_order():
    text = "смотри https://youtu.be/one и ещё https://vk.com/video-1_2 всё"
    assert extract_urls(text) == ["https://youtu.be/one", "https://vk.com/video-1_2"]


def test_deduplicates_repeated_links():
    assert extract_urls("https://youtu.be/x и снова https://youtu.be/x") == ["https://youtu.be/x"]


def test_markdown_link_yields_the_url_not_the_label():
    assert extract_urls("[Смотреть видео](https://youtu.be/xOs8qxm2KOI)") == \
        ["https://youtu.be/xOs8qxm2KOI"]


def test_hidden_hyperlinks_are_merged_in():
    urls = extract_urls("нажми сюда", ["https://youtu.be/hidden", "ftp://nope"])
    assert urls == ["https://youtu.be/hidden"]


def test_sentence_punctuation_is_not_part_of_the_url():
    assert extract_urls("вот: https://youtu.be/x.") == ["https://youtu.be/x"]
    assert extract_urls("**https://youtu.be/x**, дальше") == ["https://youtu.be/x"]
    assert extract_urls("(см. https://youtu.be/x)") == ["https://youtu.be/x"]


def test_balanced_brackets_stay_in_the_url():
    url = "https://en.wikipedia.org/wiki/Aliens_(film)"
    assert extract_urls(f"про {url} вот") == [url]


def test_no_links_no_results():
    assert extract_urls("просто болтаю") == []
    assert extract_urls(None) == []
    assert extract_urls("") == []
