import pytest

from seekly import APIError, AuthenticationError, RateLimitError, SeeklyClient


class FakeResponse:
    def __init__(self, status_code, json_data=None, headers=None):
        self.status_code = status_code
        self._json = json_data
        self.headers = headers or {}
        self.ok = 200 <= status_code < 300

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json


class FakeSession:
    def __init__(self, response):
        self._response = response
        self.last_request = None

    def request(self, method, url, headers=None, timeout=None, **kwargs):
        self.last_request = {"method": method, "url": url, "headers": headers, **kwargs}
        return self._response


def make_client(response):
    session = FakeSession(response)
    client = SeeklyClient(api_key="sk_live_test", base_url="https://api.example.com", session=session)
    return client, session


def test_requires_api_key():
    with pytest.raises(ValueError):
        SeeklyClient(api_key="", base_url="https://api.example.com")


def test_requires_base_url():
    with pytest.raises(ValueError):
        SeeklyClient(api_key="sk_live_x", base_url="")


def test_search_sends_api_key_header_and_query_params():
    client, session = make_client(
        FakeResponse(200, {"query": "q", "answer": None, "results": [], "images": [], "response_time": 0.1})
    )
    resp = client.search("rust async runtimes", max_results=5, include_answer=True)

    assert session.last_request["headers"]["X-API-Key"] == "sk_live_test"
    assert session.last_request["url"] == "https://api.example.com/v1/search"
    assert session.last_request["params"]["q"] == "rust async runtimes"
    assert session.last_request["params"]["max_results"] == 5
    assert session.last_request["params"]["include_answer"] is True
    assert resp.query == "q"
    assert resp.results == []


def test_search_response_is_attribute_accessible():
    client, _ = make_client(
        FakeResponse(
            200,
            {
                "query": "q",
                "answer": "an answer",
                "results": [{"title": "t", "url": "https://x", "final_score": 0.9}],
                "images": [],
                "response_time": 0.1,
            },
        )
    )
    resp = client.search("q")
    assert resp.answer == "an answer"
    assert resp.results[0].title == "t"
    assert resp.results[0].final_score == 0.9


def test_search_joins_domain_lists():
    client, session = make_client(
        FakeResponse(200, {"query": "q", "answer": None, "results": [], "images": [], "response_time": 0.1})
    )
    client.search("q", include_domains=["python.org", "docs.python.org"], exclude_domains="spam.com")
    assert session.last_request["params"]["include_domains"] == "python.org,docs.python.org"
    assert session.last_request["params"]["exclude_domains"] == "spam.com"


def test_extract_passes_url_and_query():
    client, session = make_client(
        FakeResponse(200, {"url": "https://x", "word_count": 1, "content": "c", "passages": []})
    )
    doc = client.extract("https://x", query="pricing")
    assert session.last_request["params"]["url"] == "https://x"
    assert session.last_request["params"]["query"] == "pricing"
    assert doc.content == "c"


def test_extract_batch_posts_json_body():
    client, session = make_client(FakeResponse(200, {"results": []}))
    client.extract_batch(["https://a", "https://b"], query="pricing")
    assert session.last_request["json"] == {"urls": ["https://a", "https://b"], "query": "pricing"}


def test_401_raises_authentication_error():
    client, _ = make_client(FakeResponse(401, {"detail": "invalid or revoked API key"}))
    with pytest.raises(AuthenticationError, match="invalid or revoked API key"):
        client.search("q")


def test_429_raises_rate_limit_error_with_retry_after():
    client, _ = make_client(
        FakeResponse(429, {"detail": "rate limit exceeded"}, headers={"Retry-After": "42"})
    )
    with pytest.raises(RateLimitError) as exc_info:
        client.search("q")
    assert exc_info.value.retry_after == 42


def test_other_error_raises_api_error_with_status_code():
    client, _ = make_client(FakeResponse(502, {"detail": "searxng upstream unavailable"}))
    with pytest.raises(APIError) as exc_info:
        client.search("q")
    assert exc_info.value.status_code == 502
    assert "unavailable" in str(exc_info.value)


def test_health_does_not_require_special_handling():
    client, _ = make_client(FakeResponse(200, {"searxng": "ok"}))
    resp = client.health()
    assert resp.searxng == "ok"
