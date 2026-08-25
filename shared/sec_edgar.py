"""SEC EDGAR client -- public, free, no-API-key financial filing data.

Three endpoints used, all public per SEC's open data policy
(https://www.sec.gov/os/webmaster-faq#developers) -- a descriptive
User-Agent header is required (not optional), no API key needed:

- company_tickers.json: a ticker/CIK/company-name lookup table (~10k
  entries), cached in-memory since it changes rarely.
- EDGAR full-text search: search filing text (10-K, 10-Q, 8-K, Form 4, etc).
- submissions API: a specific company's recent filing history, once we
  have its CIK from the ticker lookup.

Deliberately does NOT cover market/price data (quotes, OHLCV) -- that needs
a different provider entirely and was explicitly descoped for this phase.
"""

import time

import httpx

from api.models.finance import CompanyMatch, FilingResult

USER_AGENT = "oss-search-engine research-agent (+https://oss-search-engine-gl6faa.fly.dev)"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FULLTEXT_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

TICKER_CACHE_TTL_SECONDS = 24 * 60 * 60

_ticker_cache: dict | None = None
_ticker_cache_expires_at: float = 0.0


async def _get_ticker_table(client: httpx.AsyncClient) -> dict:
    global _ticker_cache, _ticker_cache_expires_at
    if _ticker_cache is not None and time.monotonic() < _ticker_cache_expires_at:
        return _ticker_cache
    resp = await client.get(TICKERS_URL, headers={"User-Agent": USER_AGENT}, timeout=15.0)
    resp.raise_for_status()
    _ticker_cache = resp.json()
    _ticker_cache_expires_at = time.monotonic() + TICKER_CACHE_TTL_SECONDS
    return _ticker_cache


async def lookup_company(query: str, client: httpx.AsyncClient, limit: int = 5) -> list[CompanyMatch]:
    query = query.strip()
    if not query:
        return []
    table = await _get_ticker_table(client)
    query_lower = query.lower()

    exact: list[CompanyMatch] = []
    partial: list[CompanyMatch] = []
    for entry in table.values():
        ticker = entry["ticker"]
        name = entry["title"]
        cik = entry["cik_str"]
        if ticker.lower() == query_lower:
            exact.append(CompanyMatch(ticker=ticker, name=name, cik=f"{cik:010d}"))
        elif query_lower in name.lower() and len(partial) < limit:
            partial.append(CompanyMatch(ticker=ticker, name=name, cik=f"{cik:010d}"))

    return (exact + partial)[:limit]


async def search_filings(
    query: str, client: httpx.AsyncClient, forms: list[str] | None = None, limit: int = 10
) -> list[FilingResult]:
    query = query.strip()
    if not query:
        return []
    params: dict[str, str] = {"q": query}
    if forms:
        params["forms"] = ",".join(forms)
    resp = await client.get(FULLTEXT_SEARCH_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=15.0)
    resp.raise_for_status()
    data = resp.json()

    results: list[FilingResult] = []
    seen_accessions: set[str] = set()
    # EDGAR full-text search indexes individual XBRL exhibit fragments
    # (e.g. R32.xml, R38.xml) as separate hits within the same filing --
    # dedupe by accession number so each real filing appears once, using
    # its first (highest-relevance-ranked) hit as the representative doc.
    for hit in data.get("hits", {}).get("hits", []):
        if len(results) >= limit:
            break
        src = hit["_source"]
        adsh = src.get("adsh", "")
        if not adsh or adsh in seen_accessions:
            continue
        seen_accessions.add(adsh)

        cik_raw = (src.get("ciks") or [""])[0]
        cik_no_zeros = cik_raw.lstrip("0") or "0"
        adsh_no_dashes = adsh.replace("-", "")
        filename = hit["_id"].split(":", 1)[-1]
        url = f"https://www.sec.gov/Archives/edgar/data/{cik_no_zeros}/{adsh_no_dashes}/{filename}"
        display_name = (src.get("display_names") or [""])[0]
        results.append(
            FilingResult(
                company=display_name,
                cik=cik_raw,
                form=src.get("form", ""),
                filed_at=src.get("file_date", ""),
                url=url,
            )
        )
    return results


async def company_recent_filings(cik: int, client: httpx.AsyncClient, limit: int = 10) -> list[FilingResult]:
    resp = await client.get(SUBMISSIONS_URL.format(cik=cik), headers={"User-Agent": USER_AGENT}, timeout=15.0)
    resp.raise_for_status()
    data = resp.json()
    name = data.get("name", "")
    ticker = (data.get("tickers") or [None])[0]
    recent = data.get("filings", {}).get("recent", {})

    results: list[FilingResult] = []
    for form, date, accession, primary_doc in zip(
        recent.get("form", []),
        recent.get("filingDate", []),
        recent.get("accessionNumber", []),
        recent.get("primaryDocument", []),
    ):
        if len(results) >= limit:
            break
        adsh_no_dashes = accession.replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh_no_dashes}/{primary_doc}"
        results.append(
            FilingResult(company=name, ticker=ticker, cik=f"{cik:010d}", form=form, filed_at=date, url=url)
        )
    return results
