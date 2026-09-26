"""Crawl/map job execution.

Runs as a bounded in-process background task - no separate worker to
deploy or monitor. Uses Scrapling's spider engine (async, in-process,
no Twisted/separate-process requirement like Scrapy) for fetching, link
discovery, and robots.txt compliance; `markdown(main_content_only=True)`
for crawl-mode content extraction, so a page's nav/footer chrome doesn't
end up in the result.

Scrapling has no built-in depth cap, so it's implemented here via
`response.meta["depth"]`, propagated through `response.follow()`.
`allowed_domains` (Scrapling's own mechanism) keeps every fetch within the
starting domain - the one thing this job's caller-supplied URL controls.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from scrapling.spiders.links import LinkExtractor
from scrapling.spiders.request import Request
from scrapling.spiders.templates.crawler import CrawlSpider

from api.config import CRAWL_CONCURRENCY
from shared.ranking import domain_of
from shared.url_safety import UnsafeUrlError, assert_safe_url

logger = logging.getLogger(__name__)


class _BoundedCrawlSpider(CrawlSpider):
    """Shared engine for both /v1/crawl (extract_content=True) and
    /v1/map (extract_content=False, faster - no markdown conversion).
    Same-domain only by default, depth-limited, page-count-limited.
    """

    name = "seekly_bounded_crawl"
    extract_content: bool = True
    max_pages: int = 0
    max_depth: int = 2
    select_path_patterns: list[re.Pattern] = []
    exclude_path_patterns: list[re.Pattern] = []
    # Only checked when allowed_domains is empty (i.e. allow_external=True) -
    # that's the one mode where a discovered link can point anywhere,
    # including an internal address. Same-domain/select_domains crawling
    # stays scoped to caller-approved domains, same trust boundary as the
    # already-validated start_url, so it's not re-checked per link (a
    # synchronous DNS lookup per discovered link would otherwise stall the
    # whole job).
    check_external_links_safe: bool = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._page_count = 0
        self._link_extractor = LinkExtractor()
        self.last_error: str | None = None

    async def on_error(self, request, error):
        """Scrapling's engine retries and logs a failed request but never
        raises out of `stream()` - so a start URL that's unreachable would
        otherwise look identical to a successful crawl that just found no
        links. Recorded here so `run_job` can tell "nothing was scraped
        because everything failed" apart from "nothing was scraped because
        the timeout hit immediately".
        """
        self.last_error = str(error)

    async def start_requests(self):
        for url in self.start_urls:
            yield Request(url, meta={"depth": 0})

    async def parse(self, response):
        if self.max_pages and self._page_count >= self.max_pages:
            return
        self._page_count += 1

        item = {"url": response.url}
        if self.extract_content:
            item["title"] = str(response.css("title::text").get() or "").strip()
            item["content"] = response.markdown(main_content_only=True)
        yield item

        depth = response.meta.get("depth", 0)
        if depth >= self.max_depth:
            return
        if self.max_pages and self._page_count >= self.max_pages:
            return

        for url in self._link_extractor.extract(response):
            if not self._path_allowed(url):
                continue
            if self.check_external_links_safe and not await self._is_safe_link(url):
                continue
            yield response.follow(url, meta={"depth": depth + 1})

    def _path_allowed(self, url: str) -> bool:
        path = urlsplit(url).path or "/"
        if self.select_path_patterns and not any(p.search(path) for p in self.select_path_patterns):
            return False
        if self.exclude_path_patterns and any(p.search(path) for p in self.exclude_path_patterns):
            return False
        return True

    async def _is_safe_link(self, url: str) -> bool:
        try:
            await asyncio.get_running_loop().run_in_executor(None, assert_safe_url, url)
        except UnsafeUrlError:
            return False
        return True


def _compute_allowed_domains(
    start_url: str, select_domains: list[str] | None, allow_external: bool
) -> set[str]:
    """Empty set means "no restriction" to Scrapling's engine. allow_external
    opts fully out of domain restriction (each link then goes through the
    SSRF recheck instead - see check_external_links_safe); otherwise it's
    the start URL's own domain plus any caller-approved extra domains."""
    if allow_external:
        return set()
    return {domain_of(start_url)} | set(select_domains or [])


async def run_job(job_id: str, timeout_seconds: float) -> None:
    """Executes a queued CrawlJob to completion (or until `timeout_seconds`
    elapses / max_pages is hit, whichever comes first) and writes the
    result back to the same row. Never raises - failures land in the job's
    own `error`/`status` fields, since nothing awaits this beyond
    `asyncio.create_task`.
    """
    from api.db import async_session
    from api.db_models import CrawlJob

    async with async_session() as session:
        job = await session.get(CrawlJob, job_id)
        if job is None:
            return
        job.status = "running"
        await session.commit()

        start_url = job.start_url
        max_pages = job.max_pages
        max_depth = job.max_depth
        mode = job.mode
        select_domains = job.select_domains
        allow_external = job.allow_external
        select_paths = job.select_paths
        exclude_paths = job.exclude_paths

    spider = _BoundedCrawlSpider()
    spider.start_urls = [start_url]
    spider.allowed_domains = _compute_allowed_domains(start_url, select_domains, allow_external)
    spider.check_external_links_safe = allow_external
    spider.select_path_patterns = [re.compile(p) for p in (select_paths or [])]
    spider.exclude_path_patterns = [re.compile(p) for p in (exclude_paths or [])]
    spider.max_pages = max_pages
    spider.max_depth = max_depth
    spider.extract_content = mode == "crawl"
    spider.robots_txt_obey = True
    spider.concurrent_requests = CRAWL_CONCURRENCY

    results: list[dict] = []
    status = "done"
    error = None
    try:
        async with asyncio.timeout(timeout_seconds):
            async for item in spider.stream():
                results.append(item)
    except TimeoutError:
        pass  # partial results on a bounded job are still useful, not a failure
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("crawl job %s failed", job_id)
        status = "failed"
        error = str(exc)[:1000]

    if status == "done" and not results and spider.last_error:
        status = "failed"
        error = spider.last_error[:1000]

    async with async_session() as session:
        job = await session.get(CrawlJob, job_id)
        if job is None:
            return
        job.status = status
        job.error = error
        job.results = results
        job.finished_at = datetime.now(timezone.utc)
        await session.commit()
