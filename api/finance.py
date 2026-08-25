"""System 8: Finance Intelligence Layer (v1 -- filings/company data only).

Combines three free, no-API-key sources into one response:
  - company/ticker resolution (SEC EDGAR ticker table)
  - SEC filing search (10-K/10-Q/8-K/Form 4/etc via EDGAR full-text search,
    covering "SEC filing search", "regulatory search", and "insider search"
    since Form 4 -- insider transactions -- is just another form type)
  - finance-biased news search (existing SearXNG search, categories=news)

Deliberately does NOT include market/price data (quotes, OHLCV) or
macroeconomic data (FRED etc.) -- both need a different provider and were
explicitly descoped for this phase. "market news search" here means news
*about* the company, not price data.
"""

import asyncio
import time

import httpx

from api.models.finance import FinanceSearchResponse
from api.providers.searxng import SearxngProvider
from shared.sec_edgar import company_recent_filings, lookup_company, search_filings

FILING_FORMS = ["10-K", "10-Q", "8-K", "4"]


async def finance_search(
    query: str,
    provider: SearxngProvider,
    client: httpx.AsyncClient,
    *,
    max_companies: int = 3,
    max_filings: int = 5,
    max_news: int = 5,
) -> FinanceSearchResponse:
    start = time.monotonic()

    companies_task = lookup_company(query, client, limit=max_companies)
    filings_task = search_filings(query, client, forms=FILING_FORMS, limit=max_filings)
    news_task = provider.search(query, max_results=max_news, categories="news")

    companies, filings, news_or_exc = await asyncio.gather(
        companies_task, filings_task, news_task, return_exceptions=True
    )

    if isinstance(companies, BaseException):
        companies = []
    if isinstance(filings, BaseException):
        filings = []

    # if the query resolved to a known company, also pull its own recent
    # filings directly (submissions API) -- catches recent filings that the
    # full-text search's relevance ranking might not surface
    if companies and not isinstance(companies, BaseException):
        top_match = companies[0]
        try:
            own_filings = await company_recent_filings(int(top_match.cik), client, limit=max_filings)
            seen_urls = {f.url for f in filings}
            for f in own_filings:
                if f.url not in seen_urls:
                    filings.append(f)
                    seen_urls.add(f.url)
            filings = filings[: max_filings * 2]
        except Exception:
            pass

    news = news_or_exc.results if not isinstance(news_or_exc, BaseException) else []

    return FinanceSearchResponse(
        query=query,
        companies=companies,
        filings=filings,
        news=news,
        response_time=round(time.monotonic() - start, 3),
    )
