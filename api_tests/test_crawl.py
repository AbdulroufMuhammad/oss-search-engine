import uuid

import pytest

from api.crawl import _BoundedCrawlSpider, run_job
from api.db import async_session
from api.db_models import CrawlJob


def _spider(base_url: str) -> _BoundedCrawlSpider:
    from urllib.parse import urlsplit

    spider = _BoundedCrawlSpider()
    spider.start_urls = [f"{base_url}/index.html"]
    spider.allowed_domains = {urlsplit(base_url).netloc}
    spider.robots_txt_obey = False  # fixture server doesn't serve one
    return spider


@pytest.mark.asyncio
async def test_crawl_follows_same_domain_links_and_extracts_content(crawl_fixture_url):
    spider = _spider(crawl_fixture_url)
    spider.max_pages = 10
    spider.max_depth = 2
    spider.extract_content = True

    items = [item async for item in spider.stream()]

    urls = {item["url"] for item in items}
    assert urls == {
        f"{crawl_fixture_url}/index.html",
        f"{crawl_fixture_url}/page1.html",
        f"{crawl_fixture_url}/page2.html",
        f"{crawl_fixture_url}/page3.html",
    }
    index_item = next(i for i in items if i["url"].endswith("index.html"))
    assert index_item["title"] == "Index"
    assert "Welcome" in index_item["content"]


@pytest.mark.asyncio
async def test_crawl_does_not_follow_offsite_links(crawl_fixture_url):
    """index.html links to https://external.example.com/ - must never appear."""
    spider = _spider(crawl_fixture_url)
    spider.max_pages = 10
    spider.max_depth = 2
    spider.extract_content = False

    items = [item async for item in spider.stream()]
    assert all("external.example.com" not in item["url"] for item in items)


@pytest.mark.asyncio
async def test_crawl_respects_max_depth(crawl_fixture_url):
    """page3.html is only reachable via page1.html (depth 2 from index).
    At max_depth=1, it must not be visited."""
    spider = _spider(crawl_fixture_url)
    spider.max_pages = 10
    spider.max_depth = 1
    spider.extract_content = False

    items = [item async for item in spider.stream()]
    urls = {item["url"] for item in items}
    assert f"{crawl_fixture_url}/page3.html" not in urls
    assert len(urls) == 3  # index, page1, page2


@pytest.mark.asyncio
async def test_crawl_respects_max_pages(crawl_fixture_url):
    spider = _spider(crawl_fixture_url)
    spider.max_pages = 2
    spider.max_depth = 5
    spider.extract_content = False

    items = [item async for item in spider.stream()]
    assert len(items) == 2


@pytest.mark.asyncio
async def test_map_mode_has_no_content(crawl_fixture_url):
    spider = _spider(crawl_fixture_url)
    spider.max_pages = 10
    spider.max_depth = 2
    spider.extract_content = False

    items = [item async for item in spider.stream()]
    assert all("content" not in item and "title" not in item for item in items)


@pytest.mark.asyncio
async def test_crawl_dedupes_revisited_pages(crawl_fixture_url):
    """page1.html links back to index.html - must not be scraped twice."""
    spider = _spider(crawl_fixture_url)
    spider.max_pages = 20
    spider.max_depth = 5
    spider.extract_content = False

    items = [item async for item in spider.stream()]
    urls = [item["url"] for item in items]
    assert len(urls) == len(set(urls))


async def _make_job(crawl_fixture_url: str, mode: str = "crawl", **overrides) -> str:
    async with async_session() as session:
        job = CrawlJob(
            api_key_id=f"test-{uuid.uuid4().hex}",
            mode=mode,
            start_url=f"{crawl_fixture_url}/index.html",
            max_pages=overrides.get("max_pages", 10),
            max_depth=overrides.get("max_depth", 2),
        )
        session.add(job)
        await session.commit()
        return job.id


@pytest.mark.asyncio
async def test_run_job_persists_results_and_marks_done(crawl_fixture_url, client):
    job_id = await _make_job(crawl_fixture_url)
    await run_job(job_id, timeout_seconds=30)

    async with async_session() as session:
        job = await session.get(CrawlJob, job_id)
        assert job.status == "done"
        assert job.error is None
        assert len(job.results) == 4
        assert job.finished_at is not None


@pytest.mark.asyncio
async def test_run_job_marks_failed_on_unreachable_host(client):
    async with async_session() as session:
        job = CrawlJob(
            api_key_id=f"test-{uuid.uuid4().hex}",
            mode="crawl",
            start_url="http://127.0.0.1:1/unreachable",  # nothing listens on port 1
            max_pages=5,
            max_depth=1,
        )
        session.add(job)
        await session.commit()
        job_id = job.id

    await run_job(job_id, timeout_seconds=10)

    async with async_session() as session:
        job = await session.get(CrawlJob, job_id)
        assert job.status == "failed"
        assert job.error is not None


@pytest.mark.asyncio
async def test_run_job_timeout_marks_done_not_failed(crawl_fixture_url, client):
    """Hitting the time cap is an expected bound, not an error - status
    should still be "done" (with whatever partial results made it), never
    "failed"."""
    job_id = await _make_job(crawl_fixture_url)
    await run_job(job_id, timeout_seconds=0.0001)

    async with async_session() as session:
        job = await session.get(CrawlJob, job_id)
        assert job.status == "done"
        assert job.error is None
        assert isinstance(job.results, list)


@pytest.mark.asyncio
async def test_run_job_missing_job_id_is_a_noop(client):
    await run_job("does-not-exist", timeout_seconds=5)  # must not raise
