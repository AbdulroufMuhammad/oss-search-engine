from pydantic import BaseModel


class SearchResult(BaseModel):
    title: str
    url: str
    content: str
    published_at: str | None = None
    score: float = 0.0  # raw upstream (SearXNG) relevance score, unchanged

    # System 5: our own deterministic ranking (see shared/ranking.py)
    relevance_score: float = 0.0
    authority_score: float = 0.0
    freshness_score: float = 0.0
    content_quality_score: float = 0.0
    duplicate_penalty: float = 0.0
    final_score: float = 0.0


class SearchResponse(BaseModel):
    query: str
    answer: str | None = None
    results: list[SearchResult]
    response_time: float
