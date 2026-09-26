from datetime import datetime

from pydantic import BaseModel, Field

from api.config import (
    DEFAULT_CRAWL_MAX_DEPTH,
    DEFAULT_CRAWL_MAX_PAGES,
    MAX_CRAWL_MAX_DEPTH,
    MAX_CRAWL_MAX_PAGES,
)


class CrawlRequest(BaseModel):
    url: str
    max_pages: int = Field(default=DEFAULT_CRAWL_MAX_PAGES, ge=1, le=MAX_CRAWL_MAX_PAGES)
    max_depth: int = Field(default=DEFAULT_CRAWL_MAX_DEPTH, ge=0, le=MAX_CRAWL_MAX_DEPTH)


# Map takes the same shape as crawl - it's the same job engine, just without
# per-page content extraction (see api/crawl.py's extract_content flag).
class MapRequest(CrawlRequest):
    pass


class CrawlResultItem(BaseModel):
    url: str
    title: str | None = None
    content: str | None = None  # only present for /v1/crawl, not /v1/map


class CrawlJobOut(BaseModel):
    id: str
    mode: str
    start_url: str
    max_pages: int
    max_depth: int
    status: str  # "queued" | "running" | "done" | "failed"
    error: str | None = None
    results: list[CrawlResultItem] | None = None
    created_at: datetime
    finished_at: datetime | None = None

    model_config = {"from_attributes": True}
