"""HTTP client for the Seekly search API.

Kept dependency-light (just `requests`) and schema-light: responses come
back as attribute-accessible objects (`resp.results[0].title`) built
directly from whatever JSON the server returns, rather than a duplicated
set of client-side model classes that could drift out of sync with the
server's own models.
"""

from types import SimpleNamespace
from typing import Any

import requests


class SeeklyError(Exception):
    """Base class for all Seekly SDK errors."""


class AuthenticationError(SeeklyError):
    """401 - missing, invalid, or revoked API key."""


class RateLimitError(SeeklyError):
    """429 - rate limit exceeded.

    `retry_after` is the number of seconds until the current window resets
    (at most 60) - there's no backoff/lockout beyond that, so retrying after
    waiting `retry_after` seconds is always the right move.
    """

    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class APIError(SeeklyError):
    """Any other non-2xx response."""

    def __init__(self, message: str, status_code: int, detail: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


def _to_namespace(obj: Any) -> Any:
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: _to_namespace(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [_to_namespace(v) for v in obj]
    return obj


def _join(value: list[str] | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return ",".join(value)


def _safe_json(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return None


def _error_detail(resp: requests.Response) -> str:
    data = _safe_json(resp)
    if isinstance(data, dict) and "detail" in data:
        return str(data["detail"])
    return f"HTTP {resp.status_code}"


class SeeklyClient:
    """Client for the Seekly search API.

    >>> client = SeeklyClient(api_key="sk_live_...", base_url="https://api.your-domain.com")
    >>> resp = client.search("rust async runtimes", max_results=5)
    >>> resp.results[0].title
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout: float = 30.0,
        session: requests.Session | None = None,
    ):
        if not api_key:
            raise ValueError("api_key is required")
        if not base_url:
            raise ValueError("base_url is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = session or requests.Session()

    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.base_url}{path}"
        headers = kwargs.pop("headers", {}) or {}
        headers["X-API-Key"] = self.api_key

        resp = self._session.request(method, url, headers=headers, timeout=self.timeout, **kwargs)

        if resp.status_code == 401:
            raise AuthenticationError(_error_detail(resp))
        if resp.status_code == 429:
            retry_after_header = resp.headers.get("Retry-After")
            retry_after = int(retry_after_header) if retry_after_header else None
            raise RateLimitError(_error_detail(resp), retry_after=retry_after)
        if not resp.ok:
            raise APIError(_error_detail(resp), status_code=resp.status_code, detail=_safe_json(resp))

        return _to_namespace(resp.json())

    def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        categories: str | None = None,
        expand: bool = False,
        include_answer: bool = False,
        include_domains: list[str] | str | None = None,
        exclude_domains: list[str] | str | None = None,
        time_range: str | None = None,
        topic: str = "general",
        include_images: bool = False,
        include_raw_content: bool = False,
    ):
        """GET /v1/search. Returns an object with `.query`, `.answer`,
        `.results` (list of result objects), `.images`, `.response_time`.
        Set `include_raw_content=True` to have each result carry the full
        extracted page text as `.raw_content` (fails soft to `None` per-URL,
        never fails the whole search) instead of making a separate `extract`
        call yourself."""
        params = {
            "q": query,
            "max_results": max_results,
            "categories": categories,
            "expand": expand,
            "include_answer": include_answer,
            "include_domains": _join(include_domains),
            "exclude_domains": _join(exclude_domains),
            "time_range": time_range,
            "topic": topic,
            "include_images": include_images,
            "include_raw_content": include_raw_content,
        }
        params = {k: v for k, v in params.items() if v is not None}
        return self._request("GET", "/v1/search", params=params)

    def extract(self, url: str, *, query: str | None = None, max_passages: int | None = None):
        """GET /v1/extract for a single URL."""
        params: dict[str, Any] = {"url": url}
        if query is not None:
            params["query"] = query
        if max_passages is not None:
            params["max_passages"] = max_passages
        return self._request("GET", "/v1/extract", params=params)

    def extract_batch(
        self, urls: list[str], *, query: str | None = None, max_passages: int | None = None
    ):
        """POST /v1/extract/batch for up to the server's configured cap
        (20 by default). Returns an object with `.results`, one entry per
        URL in the same order, each with `.url`, `.document` (or None), and
        `.error` (or None) - a failure on one URL never raises for the
        others."""
        body: dict[str, Any] = {"urls": urls}
        if query is not None:
            body["query"] = query
        if max_passages is not None:
            body["max_passages"] = max_passages
        return self._request("POST", "/v1/extract/batch", json=body)

    def health(self):
        """GET /v1/health. No API key required, but harmless to send one."""
        return self._request("GET", "/v1/health")

    def crawl(
        self,
        url: str,
        *,
        max_pages: int | None = None,
        max_depth: int | None = None,
        select_paths: list[str] | None = None,
        exclude_paths: list[str] | None = None,
        select_domains: list[str] | None = None,
        allow_external: bool | None = None,
    ):
        """POST /v1/crawl. Starts a bounded crawl from `url`, following
        same-domain links and extracting each page's main content as
        Markdown. Returns the job immediately in "queued" status - poll
        `get_crawl_job(job.id)` for progress and results.

        `select_paths`/`exclude_paths` are regex patterns matched against
        each discovered link's URL path (select is an allowlist, exclude a
        denylist checked after it). `select_domains` allows following links
        into additional domains beyond `url`'s own. `allow_external=True`
        drops the domain restriction entirely - every resulting link still
        goes through the same SSRF guard as `extract`, so it can't be used
        to reach internal/private addresses.
        """
        return self._create_crawl_job(
            "/v1/crawl", url, max_pages, max_depth, select_paths, exclude_paths, select_domains, allow_external
        )

    def get_crawl_job(self, job_id: str):
        """GET /v1/crawl/{job_id}."""
        return self._request("GET", f"/v1/crawl/{job_id}")

    def map(
        self,
        url: str,
        *,
        max_pages: int | None = None,
        max_depth: int | None = None,
        select_paths: list[str] | None = None,
        exclude_paths: list[str] | None = None,
        select_domains: list[str] | None = None,
        allow_external: bool | None = None,
    ):
        """POST /v1/map. Same job model and filter options as `crawl`, but
        discovers URLs without extracting page content - faster and
        cheaper. Poll `get_map_job(job.id)` for progress and results."""
        return self._create_crawl_job(
            "/v1/map", url, max_pages, max_depth, select_paths, exclude_paths, select_domains, allow_external
        )

    def get_map_job(self, job_id: str):
        """GET /v1/map/{job_id}."""
        return self._request("GET", f"/v1/map/{job_id}")

    def _create_crawl_job(
        self,
        path: str,
        url: str,
        max_pages: int | None,
        max_depth: int | None,
        select_paths: list[str] | None = None,
        exclude_paths: list[str] | None = None,
        select_domains: list[str] | None = None,
        allow_external: bool | None = None,
    ):
        body: dict[str, Any] = {"url": url}
        if max_pages is not None:
            body["max_pages"] = max_pages
        if max_depth is not None:
            body["max_depth"] = max_depth
        if select_paths is not None:
            body["select_paths"] = select_paths
        if exclude_paths is not None:
            body["exclude_paths"] = exclude_paths
        if select_domains is not None:
            body["select_domains"] = select_domains
        if allow_external is not None:
            body["allow_external"] = allow_external
        return self._request("POST", path, json=body)
