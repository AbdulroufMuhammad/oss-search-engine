from shared.canonical_url import canonicalize_url


def test_strips_utm_params():
    url = "https://example.com/article?utm_source=x&utm_medium=y&utm_campaign=z&id=1"
    assert canonicalize_url(url) == "https://example.com/article?id=1"


def test_strips_all_known_tracking_params():
    url = (
        "https://example.com/a?"
        "utm_source=a&utm_medium=b&utm_campaign=c&utm_term=d&utm_content=e"
        "&utm_id=f&gclid=g&fbclid=h&msclkid=i&keep=1"
    )
    assert canonicalize_url(url) == "https://example.com/a?keep=1"


def test_strips_www_prefix():
    assert canonicalize_url("https://www.example.com/path") == "https://example.com/path"


def test_non_www_subdomain_untouched():
    assert canonicalize_url("https://blog.example.com/path") == "https://blog.example.com/path"


def test_strips_trailing_slash():
    assert canonicalize_url("https://example.com/path/") == "https://example.com/path"


def test_root_trailing_slash_preserved():
    assert canonicalize_url("https://example.com/") == "https://example.com/"


def test_strips_fragment():
    assert canonicalize_url("https://example.com/path#section") == "https://example.com/path"


def test_query_params_sorted():
    a = canonicalize_url("https://example.com/path?b=2&a=1")
    b = canonicalize_url("https://example.com/path?a=1&b=2")
    assert a == b == "https://example.com/path?a=1&b=2"


def test_scheme_and_host_lowercased():
    assert canonicalize_url("HTTPS://Example.COM/Path") == "https://example.com/Path"


def test_path_case_not_normalized():
    assert canonicalize_url("https://example.com/PathCase") == "https://example.com/PathCase"


def test_combined_normalization_produces_matching_canonical_urls():
    a = canonicalize_url("https://WWW.Example.com/article/?utm_source=twitter#top")
    b = canonicalize_url("https://example.com/article")
    assert a == b
