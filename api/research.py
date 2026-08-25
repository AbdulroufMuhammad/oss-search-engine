"""System 7: Deep Research Engine — evidence assembly, not AI reasoning/synthesis.

Question -> subquestions (System 1's rule-based query expansion) -> search each
(System 2/3/5) -> extract top-ranked sources (System 4/6) -> assemble evidence,
a corroboration signal, and a resource-bounded stopping rule ("saturation" =
either every subquestion already has evidence, or a hard extraction budget is
spent -- both concrete/deterministic, not a fuzzy "is this enough" judgment).

No AI: this does NOT synthesize a novel answer from the assembled evidence --
`answer` only ever reuses the same rule-based infobox-derived answer /v1/search
already returns for the original question, or is None. It also does NOT verify
factual claims: `conflicting_claims` is honestly always empty here (real
contradiction detection needs claim extraction/NLP, out of scope for this
phase, same as `detect_language` in shared/query_intelligence.py).
"""

import asyncio
import time

import httpx

from api.extraction import ExtractionError
from api.extraction import extract as extract_document
from api.models.research import Evidence, ResearchResponse
from api.providers.searxng import SearxngProvider
from shared.query_intelligence import analyze_query
from shared.ranking import domain_of

MAX_TOTAL_EXTRACTIONS = 6
DEFAULT_MAX_SUBQUESTIONS = 3
DEFAULT_MAX_SOURCES_PER_SUBQUESTION = 2
EXTRACTION_PASSAGES_PER_SOURCE = 2


async def _extract_evidence(
    subquestion: str,
    url: str,
    title: str,
    authority: float,
    relevance: float,
    client: httpx.AsyncClient,
) -> Evidence | None:
    try:
        doc = await extract_document(url, client, query=subquestion, max_passages=EXTRACTION_PASSAGES_PER_SOURCE)
    except ExtractionError:
        return None
    return Evidence(
        subquestion=subquestion,
        url=url,
        title=doc.title or title or None,
        domain=domain_of(url),
        authority_score=authority,
        relevance_score=relevance,
        passages=[p.text for p in doc.passages],
    )


async def research(
    question: str,
    provider: SearxngProvider,
    client: httpx.AsyncClient,
    *,
    max_subquestions: int = DEFAULT_MAX_SUBQUESTIONS,
    max_sources_per_subquestion: int = DEFAULT_MAX_SOURCES_PER_SUBQUESTION,
) -> ResearchResponse:
    start = time.monotonic()

    qi = analyze_query(question)
    subquestions = qi.queries[:max_subquestions] or [question]

    # Search every subquestion first (cheap: no extraction yet) so we can
    # rank candidates across all of them before spending the extraction budget.
    search_responses = await asyncio.gather(
        *(provider.search(sq, max_results=max_sources_per_subquestion + 2) for sq in subquestions),
        return_exceptions=True,
    )

    # subquestions[0] is always the original `question` (System 1's
    # expand_queries always puts the input query first) -- reuse that
    # response's infobox-derived answer instead of firing an extra search.
    answer = None
    if search_responses and not isinstance(search_responses[0], Exception):
        answer = search_responses[0].answer

    evidence: list[Evidence] = []
    covered_subquestions: set[str] = set()
    extractions_done = 0

    for subq, resp in zip(subquestions, search_responses):
        if extractions_done >= MAX_TOTAL_EXTRACTIONS:
            break  # saturation: extraction budget spent

        if isinstance(resp, BaseException) or not resp.results:
            continue

        remaining_budget = MAX_TOTAL_EXTRACTIONS - extractions_done
        candidates = resp.results[:max_sources_per_subquestion][:remaining_budget]
        if not candidates:
            break

        results = await asyncio.gather(
            *(
                _extract_evidence(subq, r.url, r.title, r.authority_score, r.relevance_score, client)
                for r in candidates
            ),
            return_exceptions=True,
        )
        extractions_done += len(candidates)

        got_any = False
        for ev in results:
            if isinstance(ev, Evidence):
                evidence.append(ev)
                got_any = True
        if got_any:
            covered_subquestions.add(subq)

        if len(covered_subquestions) == len(subquestions):
            break  # saturation: every subquestion already has evidence

    corroborated: list[str] = []
    for subq in subquestions:
        domains = {e.domain for e in evidence if e.subquestion == subq}
        if len(domains) >= 2:
            corroborated.append(subq)

    citations = sorted({e.url for e in evidence})

    coverage = len(covered_subquestions) / len(subquestions) if subquestions else 0.0
    avg_relevance = sum(e.relevance_score for e in evidence) / len(evidence) if evidence else 0.0
    corroboration_ratio = len(corroborated) / len(subquestions) if subquestions else 0.0
    confidence = round((coverage + avg_relevance + corroboration_ratio) / 3, 4)

    return ResearchResponse(
        question=question,
        subquestions=subquestions,
        answer=answer,
        evidence=evidence,
        citations=citations,
        corroborated_subquestions=corroborated,
        conflicting_claims=[],
        confidence=confidence,
        response_time=round(time.monotonic() - start, 3),
    )
