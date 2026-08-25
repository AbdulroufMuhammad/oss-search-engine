from pydantic import BaseModel

from api.models.search import SearchResult


class CompanyMatch(BaseModel):
    ticker: str
    name: str
    cik: str  # 10-digit zero-padded, SEC's standard CIK string format


class FilingResult(BaseModel):
    company: str
    ticker: str | None = None
    cik: str
    form: str
    filed_at: str
    url: str


class FinanceSearchResponse(BaseModel):
    query: str
    companies: list[CompanyMatch]
    filings: list[FilingResult]
    news: list[SearchResult]
    response_time: float
