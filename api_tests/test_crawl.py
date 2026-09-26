import re
import uuid

import pytest

from api.crawl import _BoundedCrawlSpider, _compute_allowed_domains, run_job
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


# --- path/domain filtering (select_paths, exclude_paths, select_domains, allow_external) ---


def test_compute_allowed_domains_default_is_start_domain_only():
    assert _compute_allowed_domains("https://example.com/x", None, False) == {"example.com"}


def test_compute_allowed_domains_adds_select_domains():
    assert _compute_allowed_domains(
        "https://example.com/x", ["other.example.com", "third.example.com"], False
    ) == {"example.com", "other.example.com", "third.example.com"}


def test_compute_allowed_domains_allow_external_ignores_select_domains():
    """Empty set means "no restriction at all" to Scrapling - allow_external
    opts fully out, so select_domains (a narrower allowlist) is moot."""
    assert _compute_allowed_domains("https://example.com/x", ["other.example.com"], True) == set()


def _configured_spider() -> _BoundedCrawlSpider:
    spider = _BoundedCrawlSpider()
    spider.robots_txt_obey = False
    return spider


def test_path_allowed_with_no_patterns_allows_everything():
    spider = _configured_spider()
    assert spider._path_allowed("https://example.com/anything")


def test_path_allowed_select_paths_is_an_allowlist():
    spider = _configured_spider()
    spider.select_path_patterns = [re.compile(r"^/blog/")]
    assert spider._path_allowed("https://example.com/blog/post-1")
    assert not spider._path_allowed("https://example.com/about")


def test_path_allowed_exclude_paths_is_a_denylist_checked_after_select():
    spider = _configured_spider()
    spider.select_path_patterns = [re.compile(r"^/blog/")]
    spider.exclude_path_patterns = [re.compile(r"^/blog/drafts/")]
    assert spider._path_allowed("https://example.com/blog/post-1")
    assert not spider._path_allowed("https://example.com/blog/drafts/unfinished")
    # excluded from the allowlist entirely, exclude_paths is irrelevant here
    assert not spider._path_allowed("https://example.com/about")


@pytest.mark.asyncio
async def test_is_safe_link_blocks_loopback_and_metadata_targets():
    spider = _configured_spider()
    assert not await spider._is_safe_link("http://127.0.0.1:9/internal")
    assert not await spider._is_safe_link("http://169.254.169.254/latest/meta-data/")


@pytest.mark.asyncio
async def test_is_safe_link_allows_real_public_url():
    spider = _configured_spider()
    assert await spider._is_safe_link("https://example.com/")


@pytest.mark.asyncio
async def test_crawl_select_paths_restricts_which_links_are_followed(crawl_fixture_url):
    """page1.html and page2.html both link out from index.html - a
    select_paths allowlist matching only page1 must keep page2 (and
    page3, only reachable via page1) out of the results."""
    spider = _spider(crawl_fixture_url)
    spider.max_pages = 10
    spider.max_depth = 5
    spider.extract_content = False
    spider.select_path_patterns = [re.compile(r"page1\.html$")]

    items = [item async for item in spider.stream()]
    urls = {item["url"] for item in items}
    assert urls == {f"{crawl_fixture_url}/index.html", f"{crawl_fixture_url}/page1.html"}


@pytest.mark.asyncio
async def test_crawl_exclude_paths_removes_matching_links(crawl_fixture_url):
    spider = _spider(crawl_fixture_url)
    spider.max_pages = 10
    spider.max_depth = 5
    spider.extract_content = False
    spider.exclude_path_patterns = [re.compile(r"page2\.html$")]

    items = [item async for item in spider.stream()]
    urls = {item["url"] for item in items}
    assert f"{crawl_fixture_url}/page2.html" not in urls
    # page1 (and page3, reached through it) are unaffected
    assert f"{crawl_fixture_url}/page1.html" in urls
    assert f"{crawl_fixture_url}/page3.html" in urls


@pytest.mark.asyncio
async def test_run_job_wires_filter_fields_from_job_row_onto_spider(client, monkeypatch):
    """run_job reads select_paths/exclude_paths/select_domains/allow_external
    off the CrawlJob row and must configure the spider accordingly - checked
    here by swapping in a recording stand-in instead of really crawling."""
    import api.crawl as crawl_module

    captured = {}

    class _RecordingSpider:
        def __init__(self):
            self.last_error = None
            captured["instance"] = self

        async def stream(self):
            return
            yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(crawl_module, "_BoundedCrawlSpider", _RecordingSpider)

    async with async_session() as session:
        job = CrawlJob(
            api_key_id=f"test-{uuid.uuid4().hex}",
            mode="crawl",
            start_url="https://example.com/start",
            max_pages=5,
            max_depth=1,
            select_paths=[r"^/blog/"],
            exclude_paths=[r"^/blog/drafts/"],
            select_domains=["other.example.com"],
            allow_external=False,
        )
        session.add(job)
        await session.commit()
        job_id = job.id

    await run_job(job_id, timeout_seconds=5)

    spider = captured["instance"]
    assert spider.allowed_domains == {"example.com", "other.example.com"}
    assert spider.check_external_links_safe is False
    assert [p.pattern for p in spider.select_path_patterns] == [r"^/blog/"]
    assert [p.pattern for p in spider.exclude_path_patterns] == [r"^/blog/drafts/"]
    assert spider.instructions is None
    assert spider._http_client is None  # no LLM client created when unset


# --- instructions (LLM-guided link filtering) ---


def test_configured_spider_has_no_instructions_by_default():
    spider = _configured_spider()
    assert spider.instructions is None
    assert spider._http_client is None


@pytest.mark.asyncio
async def test_run_job_creates_and_closes_an_llm_client_only_when_instructions_set(client, monkeypatch):
    import api.crawl as crawl_module

    captured = {}

    class _RecordingSpider:
        def __init__(self):
            self.last_error = None
            captured["instance"] = self

        async def stream(self):
            return
            yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(crawl_module, "_BoundedCrawlSpider", _RecordingSpider)

    async with async_session() as session:
        job = CrawlJob(
            api_key_id=f"test-{uuid.uuid4().hex}",
            mode="crawl",
            start_url="https://example.com/start",
            max_pages=5,
            max_depth=1,
            instructions="only follow links about pricing",
        )
        session.add(job)
        await session.commit()
        job_id = job.id

    await run_job(job_id, timeout_seconds=5)

    spider = captured["instance"]
    assert spider.instructions == "only follow links about pricing"
    assert spider._http_client is not None
    assert spider._http_client.is_closed  # cleaned up after the job finished


@pytest.mark.asyncio
async def test_crawl_instructions_narrows_which_links_are_followed(crawl_fixture_url, monkeypatch):
    """index.html links to page1.html and page2.html - instructions
    filtering that only keeps page1 must exclude page2 (and page3, only
    reachable through it isn't affected here since page1 stays in)."""
    import api.crawl as crawl_module

    async def fake_filter(instructions, page_title, candidates, http_client):
        return [c for c in candidates if "page1" in c]

    monkeypatch.setattr(crawl_module, "filter_links_by_instructions", fake_filter)

    spider = _spider(crawl_fixture_url)
    spider.max_pages = 10
    spider.max_depth = 5
    spider.extract_content = False
    spider.instructions = "only follow page1"
    spider._http_client = object()  # any truthy value - the fake never uses it

    items = [item async for item in spider.stream()]
    urls = {item["url"] for item in items}
    assert f"{crawl_fixture_url}/page2.html" not in urls
    assert f"{crawl_fixture_url}/page1.html" in urls


@pytest.mark.asyncio
async def test_crawl_instructions_skipped_when_no_http_client(crawl_fixture_url, monkeypatch):
    """instructions alone, without an LLM client wired in (e.g. run_job
    only creates one when instructions is actually set - this covers the
    defensive case of one being set without the other), must not filter."""
    import api.crawl as crawl_module

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("filter_links_by_instructions should not be called without an http client")

    monkeypatch.setattr(crawl_module, "filter_links_by_instructions", fail_if_called)

    spider = _spider(crawl_fixture_url)
    spider.max_pages = 10
    spider.max_depth = 5
    spider.extract_content = False
    spider.instructions = "only follow page1"
    spider._http_client = None

    items = [item async for item in spider.stream()]
    urls = {item["url"] for item in items}
    assert f"{crawl_fixture_url}/page2.html" in urls  # unfiltered - all candidates followed


@pytest.mark.asyncio
async def test_crawl_instructions_fail_soft_keeps_all_candidates(crawl_fixture_url, monkeypatch):
    import api.crawl as crawl_module

    async def fake_filter(instructions, page_title, candidates, http_client):
        return None  # simulates a DeepSeek failure

    monkeypatch.setattr(crawl_module, "filter_links_by_instructions", fake_filter)

    spider = _spider(crawl_fixture_url)
    spider.max_pages = 10
    spider.max_depth = 5
    spider.extract_content = False
    spider.instructions = "only follow page1"
    spider._http_client = object()

    items = [item async for item in spider.stream()]
    urls = {item["url"] for item in items}
    assert f"{crawl_fixture_url}/page2.html" in urls
    assert f"{crawl_fixture_url}/page1.html" in urls
