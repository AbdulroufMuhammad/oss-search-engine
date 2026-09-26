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
covers search/extract/filters/SDKs in depth; the analyze/research/finance/
events endpoints below use the same auth and are additional to it.)

Overview
========

Seekly provides:

- normalized web search results
- deterministic ranking (relevance, authority, freshness, content quality)
- LLM-synthesized answers (DeepSeek) over the top results
- intent and entity analysis
- conversational research expansion
- document extraction from URLs (single or batched)
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
  analyze, research, finance, events). Generate one from the dashboard or
  via ``POST /v1/keys``. The raw key is only ever shown once, at creation
  time; only its hash is stored server-side.

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
     "images": [
       {
         "title": "Example image title",
         "url": "https://example.com/page-the-image-is-on",
         "image_url": "https://example.com/image.jpg",
         "thumbnail_url": "https://example.com/image-thumb.jpg"
       }
     ],
     "response_time": 0.233
   }

``images`` is only populated when ``include_images=true`` was passed;
otherwise it's an empty list.

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

Health check
------------

``GET /v1/health``

Returns the upstream status, for example:

.. code-block:: json

   {
     "upstream": "ok"
   }

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
``extract_batch``/``extractBatch``, and typed errors for ``401``/``429``/
other non-2xx responses. They don't wrap analyze/research/finance/events
yet — use raw HTTP + this README for those. Raw HTTP + ``API_GUIDE.md``
remains the source of truth for anything an SDK doesn't wrap.

Configuration
=============

- ``UPSTREAM_SEARCH_URL``: base URL of the upstream search engine instance
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
- ``DEEPSEEK_API_KEY`` / ``DEEPSEEK_BASE_URL`` / ``DEEPSEEK_MODEL`` /
  ``DEEPSEEK_TIMEOUT_SECONDS``: DeepSeek settings for ``include_answer``

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
