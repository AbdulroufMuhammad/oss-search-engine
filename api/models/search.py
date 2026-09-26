from pydantic import BaseModel


class SearchResult(BaseModel):
    title: str
    url: str
    content: str
    published_at: str | None = None
    score: float = 0.0  # raw upstream relevance score, unchanged
    # Only populated when the request set include_raw_content=true, or
    # search_depth=advanced (which fetches this anyway) - the full
    # extracted page text, so a caller doesn't need a second
    # GET /v1/extract round-trip just to get it.
    raw_content: str | None = None
    # Only populated when search_depth=advanced and chunks_per_source is
    # set - the top N query-relevant passages from raw_content, same
    # extraction-and-scoring logic GET /v1/extract uses for its `query`
    # param.
    content_chunks: list[str] | None = None

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
    # Only populated when include_image_descriptions=true - mirrors the
    # image's own title rather than a fabricated caption, since nothing in
    # this stack does actual image understanding (no vision model call).
    description: str | None = None


class SearchResponse(BaseModel):
    query: str
    answer: str | None = None
    results: list[SearchResult]
    images: list[ImageResult] = []
    response_time: float
    # True when Seekly's own upstream came back empty/weak and this
    # response was served by the Tavily fallback instead - see
    # api/providers/tavily.py. Always false unless TAVILY_API_KEY is set.
    fallback_used: bool = False
