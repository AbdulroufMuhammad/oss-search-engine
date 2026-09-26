# Seekly — Developer Guide

Internal API for structured web search, page extraction, and LLM-synthesized
answers. This guide is for the ~16 devs integrating it into their own apps.
For architecture/deployment details, see `README.rst` and `DEPLOY.md`.

**Using Python or JS/Node?** `sdk/python/` and `sdk/js/` wrap everything
below (auth headers, params, typed errors) so you don't have to hand-roll
raw HTTP calls — see their READMEs. This guide still applies either way:
it's the contract the SDKs implement, and the only option for other
languages.

## 1. Get an API key

1. Open the dashboard (ask whoever runs it for the URL — see `dashboard/README.md`
   if you're the one setting it up).
2. Sign up with your email (`POST /v1/auth/signup` under the hood) — you get
   your own account, not a shared login.
3. Click **New API key**, give it a name (e.g. `my-app-prod`), optionally set
   a rate limit, and create it.
4. **Copy the key now.** It's shown once (`sk_live_...`) and never again —
   only its hash is stored server-side. If you lose it, revoke it and make a
   new one.

Prefer curl over the dashboard? Same two calls it makes internally:

```bash
curl -X POST https://<api-host>/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "at-least-8-chars"}'
# -> {"access_token": "<jwt>", "token_type": "bearer"}

curl -X POST https://<api-host>/v1/keys \
  -H "Authorization: Bearer <jwt>" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-app-prod"}'
# -> {"id": "...", "key": "sk_live_...", ...}
```

One account can hold multiple keys — make a separate one per app/environment
(`my-app-dev`, `my-app-prod`, ...) rather than sharing a single key, so you
can revoke or resize one app's access without touching another's.

## 2. Authenticate your requests

Every call to `/v1/search`, `/v1/extract`, `/v1/extract/batch`, `/v1/crawl`,
or `/v1/map` needs your key in **one** of:

```
X-API-Key: sk_live_...
```
or
```
Authorization: Bearer sk_live_...
```

`/v1/health` needs no auth. `/v1/auth/*` and `/v1/keys*` use your **JWT**
(from login/signup), not the API key — those are account-management calls,
not search calls.

Don't hardcode the key in source — read it from an env var / secrets store
in your app, same as any other credential.

## 3. Search

```
GET /v1/search
```

| Param              | Type    | Default   | Notes                                                                          |
|---------------------|---------|-----------|----------------------------------------------------------------------------------|
| `q`                 | string  | —         | required                                                                          |
| `max_results`       | int     | 10        | 1–50                                                                              |
| `categories`        | string  | —         | comma-delimited, upstream search-engine categories (e.g. `news,science`)               |
| `expand`            | bool    | false     | fan out to `<q> news` + `<q> latest`, merge & re-rank                            |
| `include_answer`    | bool    | false     | LLM-synthesized answer over the top results (costs a DeepSeek call — see §5)     |
| `include_domains`   | string  | —         | comma-delimited (e.g. `python.org,docs.python.org`); matches domain or subdomain |
| `exclude_domains`   | string  | —         | same format, drops matches instead of keeping only them                         |
| `time_range`        | string  | —         | one of `day` / `week` / `month` / `year`                                        |
| `topic`             | string  | `general` | `general` or `news` — `news` ensures the news category is included              |
| `include_images`    | bool    | false     | also returns up to 10 image results in `images` (see §6)                        |
| `include_raw_content` | bool  | false     | attach each result's full extracted page text as `raw_content` - skips a separate `GET /v1/extract` call per result. Fails soft per-URL (`raw_content: null`), never fails the search. |
| `semantic_rerank`   | bool    | false     | have a DeepSeek call re-judge the top results for relevance before returning them (see §8). Fails soft to the original deterministic order. |
| `search_depth`      | string  | `basic`   | `basic` or `advanced`. `advanced` fetches each result's full page (absorbing `include_raw_content`'s job) and re-scores ranking from the full text instead of the snippet - more accurate but slower and pricier. |
| `chunks_per_source` | int     | —         | only meaningful with `search_depth=advanced`; attaches up to N (max 10) query-relevant passages per result as `content_chunks`. |
| `include_image_descriptions` | bool | false | mirrors each image's own title into `description` on that image (no vision model call - nothing here does actual image understanding). |
| `country`           | string  | —         | forwarded best-effort to the upstream as a `country` param; whether it changes anything depends on the upstream's own backend support. An unsupported value is a safe no-op, not an error. |

```bash
curl "https://<api-host>/v1/search?q=rust%20async%20runtimes&max_results=5" \
  -H "X-API-Key: sk_live_..."
```

```json
{
  "query": "rust async runtimes",
  "answer": null,
  "results": [
    {
      "title": "...",
      "url": "https://...",
      "content": "...",
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
  "images": [],
  "response_time": 0.233,
  "fallback_used": false
}
```

Results are pre-sorted by `final_score` (highest first) — you generally
don't need to re-rank client-side. `final_score` is deterministic (relevance
+ authority + freshness + content quality, minus a duplicate penalty), not
an LLM judgment, so it's stable and reproducible across calls.

Responses are cached server-side (~5 min by default, see `X-Cache: HIT|MISS`
response header) — identical repeated queries (same params) are cheap, so
don't build your own caching layer on top unless you need longer TTLs.

`include_domains`/`exclude_domains` are applied *after* the upstream returns
results, not sent to it as a query filter (there's no reliable cross-engine
way to do that) — so a narrow `include_domains` can leave you with fewer
than `max_results` if few of the returned results matched. It's a filter on
what came back, not a guarantee of that many matching results existing.

## 4. Extract a page

```
GET /v1/extract?url=<url>&query=<optional>&max_passages=<optional>
```

```bash
curl "https://<api-host>/v1/extract?url=https://example.com/article&query=pricing" \
  -H "X-API-Key: sk_live_..."
```

Returns cleaned page content/metadata. Pass `query` to get keyword-aware,
relevance-ranked passages instead of the raw dump — useful when you only
want the part of a long page relevant to what you're looking for.

### Batch extraction

```
POST /v1/extract/batch
```

```bash
curl -X POST "https://<api-host>/v1/extract/batch" \
  -H "X-API-Key: sk_live_..." \
  -H "Content-Type: application/json" \
  -d '{"urls": ["https://a.example.com", "https://b.example.com"], "query": "pricing"}'
```

Up to `MAX_BATCH_EXTRACT_URLS` (default 20) URLs per call, extracted
concurrently, `query`/`max_passages` applied to all of them. Response:

```json
{
  "results": [
    {"url": "https://a.example.com", "document": { "...": "same shape as GET /v1/extract" }, "error": null},
    {"url": "https://b.example.com", "document": null, "error": "no extractable article content found on this page"}
  ]
}
```

Same order as the `urls` you sent. **One bad URL never fails the whole
call** — check `error` per item, not the HTTP status, to see which ones
actually failed.

## 5. LLM-synthesized answers (`include_answer=true`)

By default `answer` is only populated when the upstream's own
infobox/instant-answer has something. Set `include_answer=true` to instead
get a real synthesized answer (via DeepSeek) generated from the top results:

```bash
curl "https://<api-host>/v1/search?q=what%20is%20the%20capital%20of%20france&include_answer=true" \
  -H "X-API-Key: sk_live_..."
```

This costs an extra LLM call, so:
- Leave it `false` for anything where you only need the result list.
- It fails soft — if DeepSeek is down or not configured server-side, you
  still get a normal search response with `answer: null`, not an error.
- Identical repeated calls hit the cache like any other search, so repeat
  queries don't re-bill DeepSeek.

## 6. Image results (`include_images=true`)

```bash
curl "https://<api-host>/v1/search?q=golden%20retriever&include_images=true" \
  -H "X-API-Key: sk_live_..."
```

Adds up to 10 entries to the `images` array, each `{title, url, image_url,
thumbnail_url, description}` — `url` is the page the image was found on,
`image_url` is the direct image link. This runs one extra upstream query;
if it fails, `images` just comes back empty rather than failing the search.
`description` is only populated when `include_image_descriptions=true`
was also passed - see §3.

## 7. Crawl and map

```
POST /v1/crawl
POST /v1/map
```

Both start a bounded, same-domain crawl from a URL and return a job you
poll — they never block on the crawl itself.

| Field       | Type   | Default | Notes                                           |
|-------------|--------|---------|--------------------------------------------------|
| `url`       | string | —       | required; must be a public URL (private/loopback IPs and cloud metadata endpoints are rejected with `400`) |
| `max_pages` | int    | 20      | 1–200                                             |
| `max_depth` | int    | 2       | 0–5; 0 = only `url` itself                       |
| `select_paths` | string[] | — | regex allowlist; a discovered link is only followed if its URL path matches at least one pattern. Up to 20. |
| `exclude_paths` | string[] | — | regex denylist, checked after `select_paths`; a matching link is never followed. Up to 20. |
| `select_domains` | string[] | — | extra domains (beyond `url`'s own) that links may follow into. Ignored when `allow_external` is set. Up to 20. |
| `allow_external` | bool | false | follow links off the starting domain entirely, ignoring `select_domains`. Every such link still goes through the same SSRF guard as `url` itself, so it can't be used to reach a private/internal address. |
| `instructions` | string | — | natural-language guidance for which links to follow (e.g. "only follow links about pricing"), up to 500 chars. Costs one DeepSeek call per fetched page (up to `max_pages` for the whole job) - the one crawl option with a real per-job LLM cost. **Off by default**: rejected with `400` unless the deployment has set `CRAWL_INSTRUCTIONS_ENABLED=true`, regardless of what you send here. |

`/v1/crawl` also extracts each page's main content as Markdown;
`/v1/map` skips extraction (faster, cheaper) and only reports which URLs
were found — use it when you just need the site's structure.

```bash
curl -X POST "https://<api-host>/v1/crawl" \
  -H "X-API-Key: sk_live_..." \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "max_pages": 20, "max_depth": 2}'
# -> {"id": "...", "mode": "crawl", "status": "queued", "results": null, ...}
```

Poll for completion:

```
GET /v1/crawl/{job_id}
GET /v1/map/{job_id}
```

```bash
curl "https://<api-host>/v1/crawl/<job_id>" -H "X-API-Key: sk_live_..."
```

```json
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
    {"url": "https://example.com", "title": "Example", "content": "# Example\n..."},
    {"url": "https://example.com/about", "title": "About", "content": "..."}
  ],
  "created_at": "2025-01-02T12:00:00Z",
  "finished_at": "2025-01-02T12:00:04Z"
}
```

`status` is one of `queued` / `running` / `done` / `failed`. `results` stays
`null` until the job finishes; on `/v1/map`, each item has `url` only (no
`title`/`content`). A job that hits its time or page cap still finishes as
`done` with whatever pages it got — that's an expected bound, not an error.
`status` only becomes `failed` when nothing could be crawled at all (e.g.
the start URL itself is unreachable), with `error` explaining why.

Jobs run server-side with a fixed timeout and never spawn a separate
worker — nothing to poll externally, no queue infrastructure on your end.
Only same-domain links are followed (subdomains of the start URL's domain
count as the same site); off-site links, and anything past `max_depth`,
are never fetched.

## 8. Reliability: semantic rerank, Tavily fallback, and upstream health

Three things the server does to keep `/v1/search` answering well even when
something underneath it is having a bad day:

**Semantic rerank (`semantic_rerank=true`).** Seekly's default ranking is
deterministic — relevance/authority/freshness/content-quality math, no
embeddings (see §3). That's fast and reproducible, but weaker on fuzzy or
ambiguous queries than a real semantic judgment. Setting
`semantic_rerank=true` adds one DeepSeek call that re-judges the top
results (`SEMANTIC_RERANK_TOP_K`, default 10) and returns them in that
order instead. It fails soft — a DeepSeek outage or malformed response
just leaves the original deterministic order in place, same convention as
`include_answer`.

**Tavily fallback (server-configured, not a request param).** If the
operator has set `TAVILY_API_KEY`, a query whose own upstream comes back
empty, or whose top result scores below `TAVILY_FALLBACK_SCORE_THRESHOLD`
(default `0.35`), is retried against Tavily before the response is
returned to you. The response's `fallback_used` field tells you whether
this happened. Unset `TAVILY_API_KEY` means this never triggers — it's an
opt-in safety net for deployments that want it, not default behavior.

**Upstream failover.** If the operator has configured more than one
upstream instance (`UPSTREAM_SEARCH_FALLBACK_URLS`), a connect/timeout/5xx
failure against one is retried against the next automatically, inside the
same request — you never see the failure as a caller. An instance that
fails repeatedly is deprioritized (tried last) for a cooldown window
rather than retried on every request. `GET /v1/health` reports each
configured instance individually:

```json
{
  "upstream": "ok",
  "upstreams": [
    {"url": "http://upstream-1:8081", "status": "ok"},
    {"url": "http://upstream-2:8081", "status": "down"}
  ]
}
```

`upstream` is the overall status (`ok` if at least one instance can serve
a request); `upstreams` is the per-instance detail an alert should page on.

## 9. Rate limits

Each key has its own `requests/minute` limit (see it / change it from the
dashboard, or `GET /v1/keys`). Go over it and you get:

```
HTTP 429
Retry-After: <seconds, max 60>
```

There's no penalty box — the next 60-second window resets to full quota
automatically. Handle it like any `429`: back off for `Retry-After` seconds
and retry, don't hammer.

If your app legitimately needs a higher steady-state rate (a batch job,
high-traffic service), set a higher `rate_limit_per_minute` on that key's
own row rather than working around 429s — see the dashboard's "Edit limit"
or `PATCH /v1/keys/{id}`.

## 10. Errors

| Status | Meaning                                              | What to do                                  |
|--------|-------------------------------------------------------|-----------------------------------------------|
| 400    | bad request (empty `q`, invalid `topic`/`time_range`/`search_depth`, a crawl/map `url` that's unsafe/unreachable-by-policy, or `instructions` sent while disabled on this deployment) | fix the request |
| 401    | missing/invalid/revoked API key, or bad JWT            | check your key; re-login for JWT endpoints    |
| 404    | key not found (on `/v1/keys/{id}`), or crawl/map job not found / not yours | check the id                   |
| 422    | validation error (bad param shape/type, batch urls empty or over the cap, `max_pages`/`max_depth` out of range, invalid `select_paths`/`exclude_paths` regex, or too many patterns/domains), or extract found no content | fix input |
| 429    | rate limited                                           | back off `Retry-After` seconds, retry         |
| 502    | upstream search engine unavailable (every configured instance failed over, and Tavily fallback either isn't configured or also failed — see §8) | transient — retry with backoff |

Error bodies are `{"detail": "..."}`. Batch extract is the one exception:
its per-URL failures (unreachable page, no content, etc.) show up as
`error` on that item, not as an HTTP error status.

## 11. Code samples

**Using the SDKs (recommended for Python/JS):**

```python
from seekly import SeeklyClient
client = SeeklyClient(api_key="sk_live_...", base_url="https://<api-host>")
resp = client.search("rust async runtimes", max_results=5)
```

```js
import { SeeklyClient } from "seekly";
const client = new SeeklyClient({ apiKey: "sk_live_...", baseUrl: "https://<api-host>" });
const resp = await client.search("rust async runtimes", { maxResults: 5 });
```

See `sdk/python/README.md` / `sdk/js/README.md` for install instructions
and full usage (batch extract, filters, error types).

**Raw HTTP, Python (`requests`):**

```python
import os
import requests

API_KEY = os.environ["SEEKLY_API_KEY"]
BASE_URL = "https://<api-host>"

resp = requests.get(
    f"{BASE_URL}/v1/search",
    params={"q": "rust async runtimes", "max_results": 5},
    headers={"X-API-Key": API_KEY},
    timeout=30,
)
resp.raise_for_status()
data = resp.json()
for r in data["results"]:
    print(r["final_score"], r["title"], r["url"])
```

**Raw HTTP, Node / JS (`fetch`):**

```js
const API_KEY = process.env.SEEKLY_API_KEY;
const BASE_URL = "https://<api-host>";

const params = new URLSearchParams({ q: "rust async runtimes", max_results: "5" });
const resp = await fetch(`${BASE_URL}/v1/search?${params}`, {
  headers: { "X-API-Key": API_KEY },
});
if (!resp.ok) {
  if (resp.status === 429) {
    const retryAfter = resp.headers.get("Retry-After");
    // back off and retry
  }
  throw new Error(`search failed: ${resp.status}`);
}
const data = await resp.json();
```

## 12. Good practices

- One key per app/environment, not one shared key for everything — makes
  revocation and quota changes safe and scoped.
- Read the key from config/secrets, never commit it.
- Use `include_answer=true`, `include_images=true`, `semantic_rerank=true`,
  and `search_depth=advanced` only where you actually use the result — each
  costs an extra call (DeepSeek, a second upstream query, another DeepSeek
  call, or a per-result fetch, respectively).
- Crawl/map `instructions` is disabled by default server-side — don't rely
  on it being active just because your request includes it; check the
  operator has set `CRAWL_INSTRUCTIONS_ENABLED` first.
- For customer-facing use, check `fallback_used` if you want to know when a
  response came from the Tavily safety net rather than Seekly's own
  ranking — useful for monitoring how often that's happening, not required
  for correctness (the response shape is identical either way).
- For batch extract, check each item's `error`, not just the HTTP status —
  a 200 can still contain per-URL failures.
- Treat `429` as expected, not exceptional — handle it, don't alert-page on it.
- If you're decommissioning an app, revoke its key from the dashboard
  rather than leaving it live.

## Questions / issues

Ping whoever's running the instance, or open an issue in this repo.
