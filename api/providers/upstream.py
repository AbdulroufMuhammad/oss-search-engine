import asyncio
import logging
import time

import httpx

from api.config import UPSTREAM_COOLDOWN_SECONDS, UPSTREAM_FAILURE_THRESHOLD
from api.models.search import ImageResult, SearchResponse, SearchResult
from api.providers.base import ProviderUnavailableError
from shared.canonical_url import canonicalize_url
from shared.ranking import (
    content_fingerprint,
    content_quality_score,
    domain_of,
    final_score,
    freshness_score,
    keyword_relevance,
)
from shared.source_registry import authority_for_domain

CONTENT_TRUNCATE = 500
DUPLICATE_CONTENT_PENALTY = 0.5
MAX_IMAGE_RESULTS = 10

logger = logging.getLogger(__name__)


def _rank_and_sort(query: str, results: list[SearchResult], max_results: int) -> list[SearchResult]:
    """System 5: score each result (deterministic, no AI) and sort by final_score.
    Also applies a content-fingerprint duplicate penalty — distinct from the
    URL-level dedup in System 3, this catches near-identical content served
    from *different* URLs (e.g. syndicated articles).
    """
    seen_fingerprints: set[str] = set()
    for r in results:
        fp = content_fingerprint(r.content) if r.content else None
        is_duplicate = fp is not None and fp in seen_fingerprints
        if fp is not None:
            seen_fingerprints.add(fp)

        r.relevance_score = keyword_relevance(query, r.title, r.content)
        r.authority_score = authority_for_domain(domain_of(r.url))
        r.freshness_score = freshness_score(r.published_at)
        r.content_quality_score = content_quality_score(r.title, r.content)
        r.duplicate_penalty = DUPLICATE_CONTENT_PENALTY if is_duplicate else 0.0
        r.final_score = final_score(
            relevance=r.relevance_score,
            authority=r.authority_score,
            freshness=r.freshness_score,
            content_quality=r.content_quality_score,
            duplicate_penalty=r.duplicate_penalty,
        )

    results.sort(key=lambda r: r.final_score, reverse=True)
    return results[:max_results]


def _domain_matches(result_domain: str, filter_domain: str) -> bool:
    filter_domain = filter_domain.lower().lstrip(".")
    return result_domain == filter_domain or result_domain.endswith("." + filter_domain)


def _filter_by_domain(
    results: list[SearchResult],
    include_domains: list[str] | None,
    exclude_domains: list[str] | None,
) -> list[SearchResult]:
    """Post-filters by domain rather than relying on upstream query syntax
    (e.g. `site:`), since that's engine-specific and not reliable across
    every backend the upstream might be configured with. Trade-off: since
    this filters what the upstream already returned rather than requesting
    more, a narrow include_domains list can yield fewer than max_results.
    """
    if not include_domains and not exclude_domains:
        return results

    filtered = []
    for r in results:
        d = domain_of(r.url)
        if include_domains and not any(_domain_matches(d, inc) for inc in include_domains):
            continue
        if exclude_domains and any(_domain_matches(d, exc) for exc in exclude_domains):
            continue
        filtered.append(r)
    return filtered


def _reshape(
    data: dict,
    max_results: int,
    *,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> SearchResponse:
    answer = None
    answers = data.get("answers") or []
    if answers:
        answer = " ".join(a.get("answer", str(a)) if isinstance(a, dict) else str(a) for a in answers)
    else:
        infoboxes = data.get("infoboxes") or []
        if infoboxes:
            answer = infoboxes[0].get("content") or None

    seen_urls: set[str] = set()
    cleaned: list[SearchResult] = []
    for r in data.get("results", []):
        raw_url = r.get("url")
        if not raw_url:
            continue
        url = canonicalize_url(raw_url)
        if url in seen_urls:
            continue
        title = (r.get("title") or "").strip()
        content = (r.get("content") or "").strip()
        if not title and not content:
            continue
        seen_urls.add(url)
        if len(content) > CONTENT_TRUNCATE:
            content = content[:CONTENT_TRUNCATE].rsplit(" ", 1)[0] + "..."
        published_at = r.get("publishedDate") or r.get("pubdate") or None
        cleaned.append(
            SearchResult(
                title=title, url=url, content=content, published_at=published_at, score=r.get("score", 0)
            )
        )

    cleaned = _filter_by_domain(cleaned, include_domains, exclude_domains)

    query = data.get("query", "")
    cleaned = _rank_and_sort(query, cleaned, max_results)

    return SearchResponse(query=query, answer=answer, results=cleaned, response_time=0.0)


class UpstreamSearchProvider:
    """Talks to the configured upstream search engine's JSON search API.

    Accepts one or more base URLs. On a connect/timeout/5xx failure against
    one, it tries the next before giving up - each failing URL is tracked
    with a simple in-process circuit breaker (see api/config.py) so a
    consistently-down instance is deprioritized instead of adding its own
    timeout to every single request.
    """

    def __init__(self, base_urls: str | list[str], client: httpx.AsyncClient):
        self._base_urls = [base_urls] if isinstance(base_urls, str) else list(base_urls)
        self._client = client
        self._failure_counts: dict[str, int] = {}
        self._cooldown_until: dict[str, float] = {}

    def _ordered_urls(self) -> list[str]:
        """Healthy URLs first, in configured order; URLs still in cooldown
        are tried last (never dropped entirely - a stale "unhealthy" mark
        shouldn't cause a 502 if every other instance is also down)."""
        now = time.monotonic()
        healthy = [u for u in self._base_urls if self._cooldown_until.get(u, 0.0) <= now]
        cooling = [u for u in self._base_urls if self._cooldown_until.get(u, 0.0) > now]
        return healthy + cooling

    def _record_success(self, url: str) -> None:
        self._failure_counts[url] = 0
        self._cooldown_until.pop(url, None)

    def _record_failure(self, url: str) -> None:
        count = self._failure_counts.get(url, 0) + 1
        self._failure_counts[url] = count
        if count >= UPSTREAM_FAILURE_THRESHOLD:
            self._cooldown_until[url] = time.monotonic() + UPSTREAM_COOLDOWN_SECONDS
            logger.warning(
                "upstream %s failed %d times in a row - deprioritizing for %.0fs",
                url, count, UPSTREAM_COOLDOWN_SECONDS,
            )

    async def _get_with_failover(self, path: str, params: dict) -> httpx.Response:
        last_exc: Exception | None = None
        for url in self._ordered_urls():
            try:
                resp = await self._client.get(f"{url}{path}", params=params, timeout=20.0)
                resp.raise_for_status()
            except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                self._record_failure(url)
                last_exc = exc
                continue
            self._record_success(url)
            return resp
        raise ProviderUnavailableError(f"upstream search engine unavailable: {last_exc}") from last_exc

    async def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        categories: str | None = None,
        time_range: str | None = None,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        country: str | None = None,
    ) -> SearchResponse:
        start = time.monotonic()
        params = {"q": query, "format": "json"}
        if categories:
            params["categories"] = categories
        if time_range:
            params["time_range"] = time_range
        if country:
            # Best-effort: forwarded as-is, honored only if the configured
            # upstream instance/backends support it. An unsupported value
            # is a safe no-op (SearXNG ignores unknown params), not an error.
            params["country"] = country
        resp = await self._get_with_failover("/search", params)

        out = _reshape(resp.json(), max_results, include_domains=include_domains, exclude_domains=exclude_domains)
        out.response_time = round(time.monotonic() - start, 3)
        return out

    async def search_images(self, query: str, *, max_results: int = MAX_IMAGE_RESULTS) -> list[ImageResult]:
        params = {"q": query, "format": "json", "categories": "images"}
        resp = await self._get_with_failover("/search", params)

        seen: set[str] = set()
        images: list[ImageResult] = []
        for r in resp.json().get("results", []):
            image_url = r.get("img_src")
            page_url = r.get("url")
            if not image_url or not page_url or image_url in seen:
                continue
            seen.add(image_url)
            images.append(
                ImageResult(
                    title=(r.get("title") or "").strip(),
                    url=page_url,
                    image_url=image_url,
                    thumbnail_url=r.get("thumbnail_src") or None,
                )
            )
            if len(images) >= max_results:
                break
        return images

    async def search_expanded(
        self,
        query: str,
        *,
        max_results: int = 10,
        categories: str | None = None,
        extra_queries: list[str] | None = None,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        country: str | None = None,
    ) -> SearchResponse:
        """Runs `query` plus each of `extra_queries` against the upstream
        concurrently, then merges/dedupes/re-ranks the combined results
        (System 2: parallel multi-query search acquisition). This is
        rule-based fan-out, not intent-aware expansion — that's System 1
        (query intelligence), which doesn't exist yet; the caller supplies
        the variant queries.
        """
        queries = [query, *(extra_queries or [])]
        start = time.monotonic()
        results = await asyncio.gather(
            *(
                self.search(
                    q,
                    max_results=max_results,
                    categories=categories,
                    include_domains=include_domains,
                    exclude_domains=exclude_domains,
                    country=country,
                )
                for q in queries
            ),
            return_exceptions=True,
        )

        responses = [r for r in results if isinstance(r, SearchResponse)]
        if not responses:
            # every variant failed the same way -> surface the first error
            first_error = next(r for r in results if isinstance(r, Exception))
            raise first_error

        seen_urls: set[str] = set()
        merged: list[SearchResult] = []
        answer = None
        for resp in responses:
            if answer is None and resp.answer:
                answer = resp.answer
            for r in resp.results:
                if r.url in seen_urls:
                    continue
                seen_urls.add(r.url)
                merged.append(r)

        # re-rank the merged set: a duplicate detected only across two
        # different sub-queries wouldn't otherwise get penalized
        merged = _rank_and_sort(query, merged, max_results)

        return SearchResponse(
            query=query,
            answer=answer,
            results=merged,
            response_time=round(time.monotonic() - start, 3),
        )
