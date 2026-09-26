import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from api.config import (
    DEFAULT_CRAWL_MAX_DEPTH,
    DEFAULT_CRAWL_MAX_PAGES,
    MAX_CRAWL_MAX_DEPTH,
    MAX_CRAWL_MAX_PAGES,
)

# Caps how many regex patterns / extra domains one job can carry - each is
# checked per discovered link, so this bounds that per-link cost.
MAX_PATH_PATTERNS = 20
MAX_SELECT_DOMAINS = 20


def _validate_patterns(patterns: list[str] | None) -> list[str] | None:
    if patterns is None:
        return None
    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"invalid regex {pattern!r}: {exc}") from exc
    return patterns


class CrawlRequest(BaseModel):
    url: str
    max_pages: int = Field(default=DEFAULT_CRAWL_MAX_PAGES, ge=1, le=MAX_CRAWL_MAX_PAGES)
    max_depth: int = Field(default=DEFAULT_CRAWL_MAX_DEPTH, ge=0, le=MAX_CRAWL_MAX_DEPTH)
    # Regex patterns matched against each discovered URL's path (e.g.
    # "^/blog/"). select_paths is an allowlist (a link must match at least
    # one); exclude_paths is a denylist, checked after select_paths.
    select_paths: list[str] | None = Field(default=None, max_length=MAX_PATH_PATTERNS)
    exclude_paths: list[str] | None = Field(default=None, max_length=MAX_PATH_PATTERNS)
    # Extra domains (beyond url's own) that links are allowed to follow into.
    # Ignored when allow_external=True, since that already allows any domain.
    select_domains: list[str] | None = Field(default=None, max_length=MAX_SELECT_DOMAINS)
    # Default is same-domain-only. Set true to follow links off the
    # starting domain entirely - each such link is re-checked against the
    # SSRF guard before being fetched, since it's no longer a
    # caller-approved domain.
    allow_external: bool = False

    _validate_select_paths = field_validator("select_paths")(_validate_patterns)
    _validate_exclude_paths = field_validator("exclude_paths")(_validate_patterns)


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
    select_paths: list[str] | None = None
    exclude_paths: list[str] | None = None
    select_domains: list[str] | None = None
    allow_external: bool = False
    status: str  # "queued" | "running" | "done" | "failed"
    error: str | None = None
    results: list[CrawlResultItem] | None = None
    created_at: datetime
    finished_at: datetime | None = None

    model_config = {"from_attributes": True}
