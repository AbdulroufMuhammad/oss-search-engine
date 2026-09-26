import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import CRAWL_JOB_TIMEOUT_SECONDS
from api.crawl import run_job
from api.db import get_session
from api.db_models import ApiKey, CrawlJob
from api.deps import get_api_key
from api.models.crawl import CrawlJobOut, CrawlRequest, MapRequest
from shared.url_safety import UnsafeUrlError, assert_safe_url

router = APIRouter()


async def _create_job(
    body: CrawlRequest,
    mode: str,
    api_key: ApiKey,
    session: AsyncSession,
) -> CrawlJob:
    if not body.url.strip():
        raise HTTPException(status_code=400, detail="url must not be empty")
    try:
        assert_safe_url(body.url)
    except UnsafeUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    job = CrawlJob(
        api_key_id=api_key.id,
        mode=mode,
        start_url=body.url,
        max_pages=body.max_pages,
        max_depth=body.max_depth,
        select_paths=body.select_paths,
        exclude_paths=body.exclude_paths,
        select_domains=body.select_domains,
        allow_external=body.allow_external,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    asyncio.create_task(run_job(job.id, timeout_seconds=CRAWL_JOB_TIMEOUT_SECONDS))
    return job


async def _get_job(job_id: str, api_key: ApiKey, session: AsyncSession) -> CrawlJob:
    result = await session.execute(
        select(CrawlJob).where(CrawlJob.id == job_id, CrawlJob.api_key_id == api_key.id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="crawl/map job not found")
    return job


@router.post("/v1/crawl", response_model=CrawlJobOut, status_code=201)
async def create_crawl(
    body: CrawlRequest,
    api_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    """Crawls a site starting from `url`, following same-domain links up to
    `max_depth`/`max_pages`, extracting each page's main content as
    Markdown. Runs as a bounded background job - poll GET /v1/crawl/{id}
    for status and results."""
    job = await _create_job(body, "crawl", api_key, session)
    return job


@router.get("/v1/crawl/{job_id}", response_model=CrawlJobOut)
async def get_crawl(
    job_id: str,
    api_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    return await _get_job(job_id, api_key, session)


@router.post("/v1/map", response_model=CrawlJobOut, status_code=201)
async def create_map(
    body: MapRequest,
    api_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    """Discovers URLs reachable from `url` within the same domain, up to
    `max_depth`/`max_pages` - no content extraction, so it's faster and
    cheaper than /v1/crawl. Same job/polling model as crawl."""
    job = await _create_job(body, "map", api_key, session)
    return job


@router.get("/v1/map/{job_id}", response_model=CrawlJobOut)
async def get_map(
    job_id: str,
    api_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    return await _get_job(job_id, api_key, session)
