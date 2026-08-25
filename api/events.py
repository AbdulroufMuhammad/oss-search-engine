"""System 9: Event Detection orchestration.

Runs a news search (System 2/5) then applies shared/event_detection.py's
rule-based classifier to each result. Only results where a recognizable
event pattern actually matched are returned -- most news won't be a
structured "event" in this sense, and that's the correct, honest behavior
(see detect_event()'s None-return path), not a bug to paper over.
"""

import time

import httpx

from api.models.event import Event, EventsResponse
from api.providers.searxng import SearxngProvider
from shared.event_detection import detect_event


async def detect_events(
    query: str,
    provider: SearxngProvider,
    client: httpx.AsyncClient,
    *,
    max_results: int = 10,
) -> EventsResponse:
    start = time.monotonic()

    resp = await provider.search(query, max_results=max_results, categories="news")

    events: list[Event] = []
    for r in resp.results:
        ev = detect_event(
            r.title,
            r.content,
            entity=None,
            authority_score=r.authority_score,
            published_at=r.published_at,
            source_url=r.url,
        )
        if ev is not None:
            events.append(ev)

    events.sort(key=lambda e: e.importance, reverse=True)

    return EventsResponse(query=query, events=events, response_time=round(time.monotonic() - start, 3))
