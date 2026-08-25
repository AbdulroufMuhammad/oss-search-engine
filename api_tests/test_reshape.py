from api.providers.searxng import _reshape


def test_dedup_same_canonical_url():
    data = {
        "query": "python",
        "results": [
            {"url": "https://www.example.com/py?utm_source=x", "title": "Python", "content": "About python."},
            {"url": "https://example.com/py", "title": "Python (dup)", "content": "About python again."},
        ],
    }
    out = _reshape(data, max_results=10)
    assert len(out.results) == 1


def test_results_sorted_by_final_score_descending():
    data = {
        "query": "python testing",
        "results": [
            {
                "url": "https://example.com/weak",
                "title": "unrelated",
                "content": "nothing to do with the query at all",
            },
            {
                "url": "https://example.com/strong",
                "title": "python testing guide",
                "content": "a thorough guide to python testing " * 10,
            },
        ],
    }
    out = _reshape(data, max_results=10)
    assert [r.url for r in out.results] == ["https://example.com/strong", "https://example.com/weak"]
    scores = [r.final_score for r in out.results]
    assert scores == sorted(scores, reverse=True)


def test_result_with_no_title_and_no_content_dropped():
    data = {
        "query": "python",
        "results": [
            {"url": "https://example.com/empty", "title": "", "content": ""},
            {"url": "https://example.com/ok", "title": "Python", "content": "content"},
        ],
    }
    out = _reshape(data, max_results=10)
    urls = [r.url for r in out.results]
    assert "https://example.com/empty" not in urls
    assert "https://example.com/ok" in urls


def test_result_missing_url_is_skipped():
    data = {
        "query": "python",
        "results": [
            {"title": "No URL here", "content": "content"},
            {"url": "https://example.com/ok", "title": "Python", "content": "content"},
        ],
    }
    out = _reshape(data, max_results=10)
    assert len(out.results) == 1


def test_answer_populated_from_infoboxes_when_present():
    data = {
        "query": "python",
        "results": [],
        "infoboxes": [{"content": "Python is a programming language."}],
    }
    out = _reshape(data, max_results=10)
    assert out.answer == "Python is a programming language."


def test_answer_populated_from_answers_when_present():
    data = {
        "query": "2+2",
        "results": [],
        "answers": ["4"],
        "infoboxes": [{"content": "should not be used"}],
    }
    out = _reshape(data, max_results=10)
    assert out.answer == "4"


def test_answer_none_when_no_answers_or_infoboxes():
    data = {"query": "python", "results": []}
    out = _reshape(data, max_results=10)
    assert out.answer is None


def test_max_results_truncates():
    data = {
        "query": "python",
        "results": [
            {"url": f"https://example.com/{i}", "title": f"Python {i}", "content": "python content " * 5}
            for i in range(5)
        ],
    }
    out = _reshape(data, max_results=2)
    assert len(out.results) == 2


def test_long_content_truncated():
    data = {
        "query": "python",
        "results": [
            {"url": "https://example.com/long", "title": "Python", "content": "word " * 200},
        ],
    }
    out = _reshape(data, max_results=10)
    assert len(out.results[0].content) <= 503
    assert out.results[0].content.endswith("...")
