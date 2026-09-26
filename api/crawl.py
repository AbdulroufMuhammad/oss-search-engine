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

import logging
from datetime import datetime, timezone

from scrapling.spiders.links import LinkExtractor
from scrapling.spiders.request import Request
from scrapling.spiders.templates.crawler import CrawlSpider

from api.config import CRAWL_CONCURRENCY
from shared.ranking import domain_of

logger = logging.getLogger(__name__)


class _BoundedCrawlSpider(CrawlSpider):
    """Shared engine for both /v1/crawl (extract_content=True) and
    /v1/map (extract_content=False, faster - no markdown conversion).
    Same-domain only, depth-limited, page-count-limited.
    """

    name = "seekly_bounded_crawl"
    extract_content: bool = True
    max_pages: int = 0
    max_depth: int = 2

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
            yield response.follow(url, meta={"depth": depth + 1})


async def run_job(job_id: str, timeout_seconds: float) -> None:
    """Executes a queued CrawlJob to completion (or until `timeout_seconds`
    elapses / max_pages is hit, whichever comes first) and writes the
    result back to the same row. Never raises - failures land in the job's
    own `error`/`status` fields, since nothing awaits this beyond
    `asyncio.create_task`.
    """
    import asyncio

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

    spider = _BoundedCrawlSpider()
    spider.start_urls = [start_url]
    spider.allowed_domains = {domain_of(start_url)}
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
