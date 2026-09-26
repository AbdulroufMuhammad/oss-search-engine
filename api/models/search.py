from pydantic import BaseModel


class SearchResult(BaseModel):
    title: str
    url: str
    content: str
    published_at: str | None = None
    score: float = 0.0  # raw upstream relevance score, unchanged
    # Only populated when the request set include_raw_content=true - the
    # full extracted page text, so a caller doesn't need a second
    # GET /v1/extract round-trip just to get it.
    raw_content: str | None = None

    # System 5: our own deterministic ranking (see shared/ranking.py)
    relevance_score: float = 0.0
    authority_score: float = 0.0
    freshness_score: float = 0.0
    content_quality_score: float = 0.0
    duplicate_penalty: float = 0.0
    final_score: float = 0.0


class ImageResult(BaseModel):
    title: str
    url: str  # source page the image was found on
    image_url: str
    thumbnail_url: str | None = None


class SearchResponse(BaseModel):
    query: str
    answer: str | None = None
    results: list[SearchResult]
    images: list[ImageResult] = []
    response_time: float
