.. SPDX-License-Identifier: AGPL-3.0-or-later

====================
OSS Search RXNG
====================

OSS Search RXNG is the open-source search and retrieval platform for structured
search, source aggregation, document extraction, and research workflows.

This project exposes a FastAPI-based API that wraps upstream SearXNG search
results, normalizes them, and enriches them with deterministic ranking metadata,
query analysis, source extraction, finance lookups, and event detection.

The web search output is intentionally LLM-friendly: it is a compact,
machine-readable schema optimized for AI agents and downstream tools, similar in
spirit to Tavily and other structured search APIs. Each result carries a stable
URL, title, snippet, publication date, and ranking scores instead of leaving
clients to scrape raw HTML or re-derive relevance heuristics.

The legacy SearXNG branding has been replaced here with the OSS Search RXNG
identity for this implementation.

Overview
========

OSS Search RXNG provides:

- normalized web search results
- intent and entity analysis
- conversational research expansion
- document extraction from URLs
- finance and SEC filing discovery
- event detection from search queries
- upstream health checks and service monitoring

The application is served by FastAPI under the API package and uses the upstream
search service configured through ``SEARXNG_UPSTREAM``.

Quick start
===========

Start the API locally:

.. code-block:: bash

   uvicorn api.app:app --host 0.0.0.0 --port 8000

Example request:

.. code-block:: bash

   curl "http://127.0.0.1:8000/v1/search?q=open%20source%20intelligence&max_results=5"

Available API endpoints
======================

The service currently exposes these endpoints:

- ``GET /v1/health``
- ``GET /v1/search``
- ``GET /v1/analyze``
- ``GET /v1/research``
- ``GET /v1/extract``
- ``GET /v1/finance/search``
- ``GET /v1/events``

Search endpoint
---------------

``GET /v1/search``

Request parameters:

- ``q``: required search query string
- ``max_results``: integer, default ``10``, range ``1..50``
- ``categories``: optional comma-delimited categories from the upstream engine
- ``expand``: boolean, default ``false``

The ``expand`` flag performs a multi-query fan-out using the original query plus
``<query> news`` and ``<query> latest`` and then merges and re-ranks the results.

Response model:

.. code-block:: json

   {
     "query": "open source intelligence",
     "answer": "Optional summarized answer text",
     "results": [
       {
         "title": "Example result title",
         "url": "https://example.com/article",
         "content": "Snippet or excerpt from the result",
         "published_at": "2025-01-02T12:00:00Z",
         "score": 2.3,
         "relevance_score": 0.87,
         "authority_score": 0.74,
         "freshness_score": 0.61,
         "content_quality_score": 0.91,
         "duplicate_penalty": 0.0,
         "final_score": 0.89
       }
     ],
     "response_time": 0.233
   }

The full normalized result shape is:

- ``title``: result title
- ``url``: canonicalized destination URL
- ``content``: extracted snippet or summary
- ``published_at``: ISO-like publication date when available
- ``score``: raw upstream SearXNG relevance score
- ``relevance_score``: content/query relevance score
- ``authority_score``: domain authority score
- ``freshness_score``: time-based freshness score
- ``content_quality_score``: quality estimate for snippet and title
- ``duplicate_penalty``: penalty for near-duplicate content
- ``final_score``: final deterministic ranking score

Search response structure
=========================

The API wraps the upstream search engine response into a deterministic schema
represented by the following model, designed for direct consumption by LLMs,
agents, and application backends.

``SearchResponse``

.. code-block:: json

   {
     "query": "string",
     "answer": "string or null",
     "results": [
       {
         "title": "string",
         "url": "string",
         "content": "string",
         "published_at": "string or null",
         "score": 0.0,
         "relevance_score": 0.0,
         "authority_score": 0.0,
         "freshness_score": 0.0,
         "content_quality_score": 0.0,
         "duplicate_penalty": 0.0,
         "final_score": 0.0
       }
     ],
     "response_time": 0.0
   }

Notes:

- The response is deduplicated by canonicalized URL.
- Near-duplicate content can receive a ``duplicate_penalty``.
- ``response_time`` is measured in seconds.
- ``answer`` is populated from upstream answer or infobox content when available.
- The structure is intentionally concise and agent-friendly, with ranking metadata
  included alongside the source snippet instead of forcing clients to infer quality.

Additional endpoints
====================

Analyze query intent
-------------------

``GET /v1/analyze?q=...``

Returns query intelligence with fields such as:

- ``intent``
- ``entities``
- ``topics``
- ``time_range``
- ``queries``

Research mode
-------------

``GET /v1/research?q=...``

Returns a structured multi-step research object containing:

- ``question``
- ``subquestions``
- ``answer``
- ``evidence``
- ``citations``
- ``corroborated_subquestions``
- ``conflicting_claims``
- ``confidence``
- ``response_time``

Document extraction
-------------------

``GET /v1/extract?url=https://example.com&query=...``

Extracts document content and metadata for a given URL, optionally using a query
for keyword-aware extraction.

Finance search
--------------

``GET /v1/finance/search?q=apple``

Returns:

- ``query``
- ``companies``
- ``filings``
- ``news``
- ``response_time``

Event detection
---------------

``GET /v1/events?q=tesla&max_results=10``

Returns detected events with:

- ``event_type``
- ``entity``
- ``sentiment``
- ``importance``
- ``market_sector``
- ``time_detected``
- ``source_url``
- ``source_title``

Health check
------------

``GET /v1/health``

Returns the upstream status, for example:

.. code-block:: json

   {
     "searxng": "ok"
   }

Project notes
=============

- This implementation is designed around a FastAPI API layer and an upstream
  SearXNG-compatible search service.
- The project is not the original upstream SearXNG website; it is the OSS Search
  RXNG API implementation and metadata pipeline.
- The search results are transformed into a consistent, machine-usable schema for
  downstream applications, research workflows, and integrations.

License
=======

This project is licensed under the GNU Affero General Public License (AGPL-3.0).
