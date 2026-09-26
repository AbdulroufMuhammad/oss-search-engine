.. SPDX-License-Identifier: AGPL-3.0-or-later

====================
Seekly
====================

Seekly is an internal search and retrieval platform: structured web search,
document extraction, research workflows, finance/SEC lookups, and event
detection, all behind one FastAPI API.

This project exposes a FastAPI-based API that wraps an upstream search
engine's results, normalizes them, and enriches them with deterministic
ranking metadata, query analysis, source extraction, finance lookups, and
event detection. (The upstream engine is a SearXNG-based service — see
*Credits* below.)

The web search output is intentionally LLM-friendly: it is a compact,
machine-readable schema optimized for AI agents and downstream tools, similar in
spirit to Tavily and other structured search APIs. Each result carries a stable
URL, title, snippet, publication date, and ranking scores instead of leaving
clients to scrape raw HTML or re-derive relevance heuristics.

**Integrating an app against this API?** See ``API_GUIDE.md`` — auth,
endpoints, rate limits, error handling, and copy-paste code samples. (It
covers search/extract/crawl/map/filters/SDKs in depth; the
analyze/research/finance/events endpoints below use the same auth and are
additional to it.)

Overview
========

Seekly provides:

- normalized web search results
- deterministic ranking (relevance, authority, freshness, content quality)
- LLM-synthesized answers (DeepSeek) over the top results
- intent and entity analysis
- conversational research expansion
- document extraction from URLs (single or batched)
- bounded same-domain crawling and site mapping
- optional semantic re-ranking and a Tavily fallback for higher-stakes/
  customer-facing search, plus multi-instance upstream failover
- finance and SEC filing discovery
- event detection from search queries
- upstream health checks and service monitoring
- self-service accounts and API keys, with per-key rate limiting

The application is served by FastAPI under the API package and uses the upstream
search service configured through ``UPSTREAM_SEARCH_URL``.

Quick start
===========

Set the environment and start the API locally:

.. code-block:: bash

   export DATABASE_URL="sqlite+aiosqlite:///./seekly.db"   # default if unset
   export JWT_SECRET="change-me"                            # required in production
   export DEEPSEEK_API_KEY="sk-..."                          # optional, enables include_answer
   uvicorn api.app:app --host 0.0.0.0 --port 8000

Create an account and an API key:

.. code-block:: bash

   curl -X POST http://127.0.0.1:8000/v1/auth/signup \
     -H "Content-Type: application/json" \
     -d '{"email": "you@example.com", "password": "at-least-8-chars"}'
   # -> {"access_token": "<jwt>", "token_type": "bearer"}

   curl -X POST http://127.0.0.1:8000/v1/keys \
     -H "Authorization: Bearer <jwt>" \
     -H "Content-Type: application/json" \
     -d '{"name": "my first key"}'
   # -> {"id": "...", "key": "sk_live_...", ...}  (the raw key is shown once, at creation)

Example search request, authenticated with the API key:

.. code-block:: bash

   curl "http://127.0.0.1:8000/v1/search?q=open%20source%20intelligence&max_results=5" \
     -H "X-API-Key: sk_live_..."

Authentication
===============

Two separate credential types are in play:

- **Session JWTs** (``Authorization: Bearer <jwt>`` from ``/v1/auth/login`` or
  ``/v1/auth/signup``) authenticate a logged-in user against the account/key
  management endpoints (``/v1/auth/me``, ``/v1/keys*``). This is what the
  dashboard frontend uses.
- **API keys** (``X-API-Key: sk_live_...``, or ``Authorization: Bearer
  sk_live_...``) authenticate every other endpoint below (search, extract,
  crawl/map, analyze, research, finance, events). Generate one from the
  dashboard or via ``POST /v1/keys``. The raw key is only ever shown once,
  at creation time; only its hash is stored server-side.

Every API key carries a per-minute rate limit (``rate_limit_per_minute``,
default ``DEFAULT_RATE_LIMIT_PER_MINUTE``, cap ``MAX_RATE_LIMIT_PER_MINUTE``).
Exceeding it returns ``429`` with a ``Retry-After`` header of at most 60
seconds — there's no lockout or backoff, the next 60-second window resets to
full quota automatically. Set a key's own limit at creation
(``POST /v1/keys`` with ``rate_limit_per_minute``) or change it later
(``PATCH /v1/keys/{id}``) — useful when different internal apps need
different quotas.

Rate limiting (and the search response cache) is backed by Valkey/Redis when
``VALKEY_URL`` is set, so multiple API instances share one correct view of
each key's usage — required once you run more than one instance (see
*Deploying on AWS* below). Without ``VALKEY_URL`` it falls back to an
in-process counter, which is fine for local dev but gives every instance its
own counters in production.

Available API endpoints
======================

The service currently exposes these endpoints:

- ``POST /v1/auth/signup`` / ``POST /v1/auth/login`` / ``GET /v1/auth/me``
- ``POST /v1/keys`` / ``GET /v1/keys`` / ``DELETE /v1/keys/{id}`` / ``PATCH /v1/keys/{id}``
- ``GET /v1/health`` (public, no auth)
- ``GET /v1/search`` (requires an API key)
- ``GET /v1/extract`` / ``POST /v1/extract/batch`` (requires an API key)
- ``POST /v1/crawl`` / ``GET /v1/crawl/{id}`` (requires an API key)
- ``POST /v1/map`` / ``GET /v1/map/{id}`` (requires an API key)
- ``GET /v1/analyze`` (requires an API key)
- ``GET /v1/research`` (requires an API key)
- ``GET /v1/finance/search`` (requires an API key)
- ``GET /v1/events`` (requires an API key)

Search endpoint
---------------

``GET /v1/search`` (requires ``X-API-Key`` or ``Authorization: Bearer <api key>``)

Request parameters:

- ``q``: required search query string
- ``max_results``: integer, default ``10``, range ``1..50``
- ``categories``: optional comma-delimited categories from the upstream engine
- ``expand``: boolean, default ``false``
- ``include_answer``: boolean, default ``false`` — when true, ``answer`` is
  generated by DeepSeek from the top results instead of just passed through
  from the upstream's infobox/instant-answer. Requires ``DEEPSEEK_API_KEY`` to be
  set; silently falls back to no answer if DeepSeek is unreachable or unset,
  so search itself never fails because of it.
- ``include_domains`` / ``exclude_domains``: optional comma-delimited domain
  lists (e.g. ``python.org,docs.python.org``). Matches the domain or any
  subdomain of it. Applied as a post-filter on whatever the upstream returned —
  not a request to the upstream itself — so a narrow ``include_domains`` can
  yield fewer than ``max_results`` if few/none of the returned results
  matched.
- ``time_range``: optional, one of ``day`` / ``week`` / ``month`` / ``year``.
  Passed straight through to the upstream's native time-range filter.
- ``topic``: optional, one of ``general`` (default) / ``news``. ``news`` is
  shorthand for making sure the ``news`` category is included — merged with,
  not overriding, an explicit ``categories`` param.
- ``include_images``: boolean, default ``false`` — when true, also runs an
  images-category query and returns up to 10 results in the ``images``
  field. Failures here degrade to an empty list rather than failing the
  whole search.
- ``include_raw_content``: boolean, default ``false`` — when true, each
  result also carries its full extracted page text as ``raw_content``
  (same extraction ``GET /v1/extract`` uses), so callers don't need a
  second round-trip per result. A single URL's extraction failing leaves
  that result's ``raw_content`` as ``null`` rather than failing the search.
- ``semantic_rerank``: boolean, default ``false`` — when true, a single
  DeepSeek call re-judges the top ``SEMANTIC_RERANK_TOP_K`` results for
  relevance and returns them in that order instead of Seekly's default
  deterministic ranking. Fails soft to the original order on any error.
  See *Reliability* below for why this exists.
- ``search_depth``: ``basic`` (default) or ``advanced``. ``advanced``
  fetches each result's full page (absorbing ``include_raw_content``'s
  job) and re-scores ranking from the full text instead of the snippet -
  more accurate but slower and pricier than ``basic``.
- ``chunks_per_source``: integer, only meaningful with
  ``search_depth=advanced``; attaches up to N (max 10) query-relevant
  passages per result as ``content_chunks``.
- ``include_image_descriptions``: boolean, default ``false`` — mirrors
  each image's own title into ``description`` on that image (no vision
  model call - nothing here does actual image understanding).
- ``country``: forwarded best-effort to the upstream as a ``country``
  param; whether it changes anything depends on the upstream's own
  backend support. An unsupported value is a safe no-op, not an error.

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
         "final_score": 0.89,
         "raw_content": null,
         "content_chunks": null
       }
     ],
     "images": [
       {
         "title": "Example image title",
         "url": "https://example.com/page-the-image-is-on",
         "image_url": "https://example.com/image.jpg",
         "thumbnail_url": "https://example.com/image-thumb.jpg",
         "description": null
       }
     ],
     "response_time": 0.233,
     "fallback_used": false
   }

``images`` is only populated when ``include_images=true`` was passed;
otherwise it's an empty list. ``description`` on each image is only
populated when ``include_image_descriptions=true`` was also passed.

The full normalized result shape is:

- ``title``: result title
- ``url``: canonicalized destination URL
- ``content``: extracted snippet or summary
- ``published_at``: ISO-like publication date when available
- ``score``: raw upstream relevance score
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
- ``answer`` is populated from upstream answer/infobox content when available,
  or replaced with a DeepSeek-generated synthesis when ``include_answer=true``.
- The structure is intentionally concise and agent-friendly, with ranking metadata
  included alongside the source snippet instead of forcing clients to infer quality.

Document extraction
====================

``GET /v1/extract?url=https://example.com&query=...`` (requires an API key)

Extracts document content and metadata for a given URL, optionally using a query
for keyword-aware, relevance-ranked passage extraction.

Batch extraction
----------------

``POST /v1/extract/batch`` (requires an API key)

.. code-block:: json

   {
     "urls": ["https://a.example.com", "https://b.example.com"],
     "query": "optional, applied to every URL",
     "max_passages": null
   }

Extracts up to ``MAX_BATCH_EXTRACT_URLS`` (default ``20``) URLs concurrently
in one call. Response:

.. code-block:: json

   {
     "results": [
       {"url": "https://a.example.com", "document": { "...": "Document, same shape as GET /v1/extract" }, "error": null},
       {"url": "https://b.example.com", "document": null, "error": "no extractable article content found on this page"}
     ]
   }

Results come back in the same order as the request's ``urls``. One URL
failing (unreachable, no content, etc.) never fails the batch — it just
gets a non-null ``error`` on that entry.

Crawl and map
=============

``POST /v1/crawl`` / ``POST /v1/map`` (requires an API key)

.. code-block:: json

   {
     "url": "https://example.com",
     "max_pages": 20,
     "max_depth": 2
   }

Both start a bounded, same-domain crawl from ``url`` and return a job
immediately in ``queued`` status rather than blocking on the crawl itself.
``/v1/crawl`` also extracts each page's main content as Markdown;
``/v1/map`` skips extraction and only reports which URLs were discovered.
``max_pages`` (default ``20``, range ``1..200``) and ``max_depth`` (default
``2``, range ``0..5``) bound the job; ``url`` goes through the same
SSRF/private-network check as ``/v1/extract``.

Optional filters, both taking up to 20 entries:

- ``select_paths`` / ``exclude_paths``: regex patterns matched against
  each discovered link's URL path. ``select_paths`` is an allowlist (a
  link must match at least one); ``exclude_paths`` is a denylist, checked
  after ``select_paths``.
- ``select_domains``: extra domains (beyond ``url``'s own) that links are
  allowed to follow into. Ignored when ``allow_external`` is set.
- ``allow_external`` (boolean, default ``false``): follow links off the
  starting domain entirely, ignoring ``select_domains``. Every such link
  still goes through the same SSRF guard as ``url`` itself, so this can't
  be used to reach a private/internal address even though it opens up
  which public domains get crawled.
- ``instructions`` (string, up to 500 chars): natural-language guidance
  for which links to follow (e.g. "only follow links about pricing").
  Costs one DeepSeek call per fetched page (up to ``max_pages`` for the
  whole job) - the one crawl option with a real per-job LLM cost.
  **Disabled by default**: rejected with ``400`` unless the deployment
  has set ``CRAWL_INSTRUCTIONS_ENABLED=true``, regardless of what a
  caller sends here.

Poll ``GET /v1/crawl/{id}`` or ``GET /v1/map/{id}`` for status/results:

.. code-block:: json

   {
     "id": "...",
     "mode": "crawl",
     "start_url": "https://example.com",
     "max_pages": 20,
     "max_depth": 2,
     "select_paths": null,
     "exclude_paths": null,
     "select_domains": null,
     "allow_external": false,
     "instructions": null,
     "status": "done",
     "error": null,
     "results": [
       {"url": "https://example.com", "title": "Example", "content": "# Example\n..."}
     ],
     "created_at": "2025-01-02T12:00:00Z",
     "finished_at": "2025-01-02T12:00:04Z"
   }

``status`` is one of ``queued`` / ``running`` / ``done`` / ``failed``.
Hitting the time or page cap still finishes as ``done`` with whatever
pages were fetched — that's an expected bound, not a failure. Jobs run as
an in-process, timeout-bounded background task (no separate worker process
to deploy or monitor), using `Scrapling <https://github.com/D4Vinci/Scrapling>`_
for fetching, link discovery, and robots.txt compliance.

Additional endpoints
====================

Analyze query intent
---------------------

``GET /v1/analyze?q=...`` (requires an API key)

Pure local query analysis — no upstream call, so it works even if the
upstream is down. Returns query intelligence with fields such as:

- ``intent``
- ``entities``
- ``topics``
- ``time_range``
- ``queries``

Research mode
--------------

``GET /v1/research?q=...`` (requires an API key)

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

Degrades gracefully if the upstream is unreachable: ``200`` with empty
``evidence``/``citations`` and ``answer: null``, rather than an error — each
subquestion is gathered independently, so one failing doesn't fail the rest.

Finance search
---------------

``GET /v1/finance/search?q=apple`` (requires an API key)

Returns:

- ``query``
- ``companies`` (from a local SEC EDGAR company/CIK dataset — no upstream needed)
- ``filings``
- ``news`` (from the upstream — degrades to an empty list if unreachable)
- ``response_time``

Event detection
-----------------

``GET /v1/events?q=tesla&max_results=10`` (requires an API key)

Returns detected events with:

- ``event_type``
- ``entity``
- ``sentiment``
- ``importance``
- ``market_sector``
- ``time_detected``
- ``source_url``
- ``source_title``

Unlike research/finance, this one has no fallback path: an upstream outage
surfaces as ``502``, not a degraded ``200``.

Reliability: semantic rerank, Tavily fallback, and upstream health
====================================================================

Three things that keep ``/v1/search`` answering well even when something
underneath it degrades:

- **Semantic rerank** (``semantic_rerank=true`` on ``/v1/search``): one
  DeepSeek call re-judges the top ``SEMANTIC_RERANK_TOP_K`` (default
  ``10``) results for relevance and returns them in that order, instead of
  Seekly's default deterministic ranking. Fails soft to the original order
  on any error - see ``api/llm/rerank.py``.
- **Tavily fallback**: if ``TAVILY_API_KEY`` is set, a query whose own
  upstream comes back empty, or whose top result scores below
  ``TAVILY_FALLBACK_SCORE_THRESHOLD`` (default ``0.35``), is retried
  against Tavily before the response is returned. The response's
  ``fallback_used`` field says whether this happened. Unset
  ``TAVILY_API_KEY`` means it never triggers - see ``api/providers/tavily.py``.
- **Upstream failover**: set ``UPSTREAM_SEARCH_FALLBACK_URLS`` to run more
  than one upstream instance; a connect/timeout/5xx failure against one is
  retried against the next automatically, inside the same request. An
  instance that fails ``UPSTREAM_FAILURE_THRESHOLD`` times in a row is
  deprioritized (tried last) for ``UPSTREAM_COOLDOWN_SECONDS`` rather than
  retried on every request - a simple in-process circuit breaker, not a
  Valkey-backed one (see ``api/providers/upstream.py`` for why that
  tradeoff is fine here).

Health check
------------

``GET /v1/health``

Returns overall status plus a per-instance breakdown (useful for alerting
on a specific down instance rather than just "something's wrong"):

.. code-block:: json

   {
     "upstream": "ok",
     "upstreams": [
       {"url": "http://upstream-1:8081", "status": "ok"},
       {"url": "http://upstream-2:8081", "status": "down"}
     ]
   }

``upstream`` is ``"ok"`` if at least one configured instance can serve a
request - that mirrors what ``/v1/search``'s own failover will actually do.

Dashboard
=========

A static, no-build-step frontend lives in ``dashboard/`` for self-service
signup, login, and API key management (create/list/revoke). It talks
directly to the ``/v1/auth`` and ``/v1/keys`` endpoints above — see
``dashboard/README.md`` for how to serve it.

Client SDKs
===========

Thin clients over the raw HTTP API, for devs who'd rather not hand-roll the
request/response/error handling themselves:

- ``sdk/python/`` — ``pip install -e sdk/python``, see ``sdk/python/README.md``
- ``sdk/js/`` — Node 18+ or a browser, zero dependencies, see ``sdk/js/README.md``

Both cover ``search`` (including the filter params above), ``extract``,
``extract_batch``/``extractBatch``, ``crawl``/``map`` and their job-polling
getters, and typed errors for ``401``/``429``/other non-2xx responses. They
don't wrap analyze/research/finance/events yet — use raw HTTP + this
README for those. Raw HTTP + ``API_GUIDE.md`` remains the source of truth
for anything an SDK doesn't wrap.

Configuration
=============

- ``UPSTREAM_SEARCH_URL``: base URL of the upstream search engine instance
- ``UPSTREAM_SEARCH_FALLBACK_URLS``: comma-separated extra upstream
  instances to fail over to (empty by default - no failover with one
  instance). See *Reliability*.
- ``UPSTREAM_FAILURE_THRESHOLD`` / ``UPSTREAM_COOLDOWN_SECONDS``:
  consecutive failures before an upstream instance is deprioritized, and
  how long for (default ``3`` / ``30``)
- ``DATABASE_URL``: SQLAlchemy async URL for users/API keys (default:
  local SQLite file; use Postgres in production — e.g. AWS RDS)
- ``VALKEY_URL``: Valkey/Redis connection for rate limiting + the search
  cache, e.g. ``redis://host:6379/0``, or ``rediss://...`` for TLS. Unset
  means both fall back to in-process state — fine for local dev, **not**
  correct once you run more than one API instance. See *Deploying on AWS*.
- ``JWT_SECRET``: signing secret for dashboard session tokens (**set this
  explicitly in production** — an unset value falls back to a random
  per-process secret, which invalidates all sessions on every restart)
- ``JWT_EXPIRE_MINUTES``: session token lifetime (default ``60``)
- ``DEFAULT_RATE_LIMIT_PER_MINUTE`` / ``MAX_RATE_LIMIT_PER_MINUTE``: default
  and cap for a key's per-minute rate limit (default ``300`` / ``3000`` —
  sized for an internal tool shared by a handful of apps, not a metered
  public API; tune to taste)
- ``CORS_ALLOWED_ORIGINS``: comma-separated origins allowed to call
  ``/v1/auth/*`` and ``/v1/keys*`` from a browser (default ``*``)
- ``CACHE_TTL_SECONDS``: search response cache TTL (default ``300``)
- ``MAX_BATCH_EXTRACT_URLS``: cap on URLs per ``POST /v1/extract/batch`` call
  (default ``20``)
- ``DEFAULT_CRAWL_MAX_PAGES`` / ``MAX_CRAWL_MAX_PAGES``: default and cap for
  ``max_pages`` on ``/v1/crawl`` and ``/v1/map`` (default ``20`` / ``200``)
- ``DEFAULT_CRAWL_MAX_DEPTH`` / ``MAX_CRAWL_MAX_DEPTH``: default and cap for
  ``max_depth`` (default ``2`` / ``5``)
- ``CRAWL_JOB_TIMEOUT_SECONDS``: wall-clock cap per crawl/map job (default
  ``120``) — a job that hits this still finishes ``done`` with whatever
  pages it got
- ``CRAWL_CONCURRENCY``: concurrent in-flight requests per crawl/map job
  (default ``5``)
- ``CRAWL_INSTRUCTIONS_ENABLED``: set to ``true`` to allow crawl/map's
  ``instructions`` option - **off by default**, since it's the one crawl
  option with a real per-job LLM cost (up to ``max_pages`` DeepSeek calls).
  A request that sets ``instructions`` while this is unset is rejected
  with ``400``, regardless of what the caller sends.
- ``DEEPSEEK_API_KEY`` / ``DEEPSEEK_BASE_URL`` / ``DEEPSEEK_MODEL`` /
  ``DEEPSEEK_TIMEOUT_SECONDS``: DeepSeek settings for ``include_answer``
  and ``semantic_rerank``
- ``SEMANTIC_RERANK_TOP_K``: how many top results ``semantic_rerank=true``
  re-judges (default ``10``)
- ``TAVILY_API_KEY`` / ``TAVILY_BASE_URL`` / ``TAVILY_TIMEOUT_SECONDS``:
  Tavily settings for the search fallback (unset ``TAVILY_API_KEY`` means
  it never triggers)
- ``TAVILY_FALLBACK_SCORE_THRESHOLD``: final_score below which the top
  result is considered weak enough to trigger the Tavily fallback
  (default ``0.35``)

Deploying on AWS
=================

This repo also has a Fly.io-specific deployment path (``Dockerfile``,
``container/start.sh``, ``fly.toml``, ``DEPLOY.md``) that puts Caddy in
front of everything and gates the *entire* app — including
``/v1/auth/signup`` and the dashboard — behind one shared ``AUTH_TOKEN``.
That predates the auth system above and actively conflicts with it: nobody
can reach self-service signup without already having that shared secret.

**On AWS, don't carry that wrapper over.** Run the API container (built from
the ``builder``/``dist`` stages in ``Dockerfile``, or your own image running
``uvicorn api.app:app`` / ``granian api.app:app``) directly behind your load
balancer, terminate TLS there, and let the app's own auth be the only gate:
JWT sessions for the dashboard, per-key auth for every other endpoint above.
Concretely, for a multi-instance setup (e.g. ECS Fargate/EC2 behind an ALB):

- **ElastiCache** (Redis or Valkey engine, both speak the same protocol this
  app uses) for ``VALKEY_URL`` — this is what makes rate limiting and the
  cache correct across instances instead of each instance tracking its own.
  Use ``rediss://`` if you enable TLS-in-transit / in-cluster encryption.
- **RDS Postgres** for ``DATABASE_URL``
  (``postgresql+asyncpg://user:pass@host/db`` — add ``asyncpg`` to
  ``api/requirements.txt``) instead of the default local SQLite file, which
  doesn't work at all across instances.
- A real ``JWT_SECRET`` from Secrets Manager / SSM Parameter Store, not the
  random per-process fallback.
- The upstream engine itself (``UPSTREAM_SEARCH_URL``) needs to be reachable
  from every API instance — run it as its own service (see
  ``container/docker-compose.yml`` for the reference pairing) rather than
  on localhost.

For local dev, ``docker-compose.dev.yml`` at the repo root gives you a real
Valkey to point ``VALKEY_URL`` at instead of the in-process fallback.

Sizing note: none of the above needs to be provisioned generously. The
users/API-keys database is two small tables with low write volume; the
Valkey dataset is small per-key counters and cached responses that
auto-expire (60s / a few minutes); DeepSeek is only called when a caller
opts into ``include_answer``. Smallest available RDS/ElastiCache instance
sizes are enough for an internal tool at this scale.

Project notes
=============

- Seekly is a FastAPI API layer in front of an upstream search engine — it
  is not that engine itself, and doesn't carry its web UI or branding; the
  engine is an implementation detail of where raw results come from (see
  *Credits*).
- The search results are transformed into a consistent, machine-usable schema for
  downstream applications, research workflows, and integrations.
- Tables are created automatically at startup (``Base.metadata.create_all``);
  there's no migration framework yet. Fine for the current schema, but add
  Alembic before making breaking model changes against a production database.

Credits
=======

Seekly's own code — the ``api/``, ``dashboard/``, and ``sdk/`` layers, and
this documentation — is original to this project. The upstream search
engine it queries is a fork of `SearXNG <https://github.com/searxng/searxng>`_,
a free, open-source metasearch engine, licensed under the GNU Affero
General Public License v3.0 (AGPL-3.0). All credit for that engine and its
search backends belongs to the SearXNG project and its contributors; this
repository does not claim it as original work. See ``LICENSE`` for the full
AGPL-3.0 text that continues to apply to that forked code.

License
=======

This project is licensed under the GNU Affero General Public License (AGPL-3.0).
