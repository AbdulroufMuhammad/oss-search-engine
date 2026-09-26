import os

UPSTREAM_SEARCH_URL = os.environ.get("UPSTREAM_SEARCH_URL", "http://127.0.0.1:8081")

# Extra upstream instances to fail over to if the primary is erroring or
# timing out - comma-separated, e.g. "http://upstream-2:8081,http://upstream-3:8081".
# Empty by default (single instance, no failover) so local dev needs no
# extra setup; add instances here once you're running more than one for
# real resilience, not just capacity.
UPSTREAM_SEARCH_FALLBACK_URLS = [
    u.strip() for u in os.environ.get("UPSTREAM_SEARCH_FALLBACK_URLS", "").split(",") if u.strip()
]
UPSTREAM_SEARCH_URLS = [UPSTREAM_SEARCH_URL, *UPSTREAM_SEARCH_FALLBACK_URLS]

# Simple in-process circuit breaker per upstream URL: after this many
# consecutive failures, that URL is deprioritized (tried last) for
# UPSTREAM_COOLDOWN_SECONDS, rather than retried on every single request.
# Deliberately per-instance state, not Valkey-backed - a stale "unhealthy"
# mark on one API instance self-heals within one cooldown window, and this
# is a resilience nice-to-have, not a correctness requirement like rate
# limiting, so the added complexity of a shared store isn't worth it.
UPSTREAM_FAILURE_THRESHOLD = int(os.environ.get("UPSTREAM_FAILURE_THRESHOLD", "3"))
UPSTREAM_COOLDOWN_SECONDS = float(os.environ.get("UPSTREAM_COOLDOWN_SECONDS", "30"))

CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "300"))

# Persistence (users + API keys). Defaults to a local SQLite file so the API
# runs out of the box; point DATABASE_URL at Postgres (e.g.
# "postgresql+asyncpg://user:pass@host/db") in production.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./seekly.db")

# Session auth (dashboard signup/login) uses JWTs signed with this secret.
# Must be set explicitly in production; a random per-process value is used
# as a fallback so local dev doesn't crash, but it invalidates all sessions
# on every restart.
JWT_SECRET = os.environ.get("JWT_SECRET") or os.urandom(32).hex()
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))

# Valkey/Redis connection for rate limiting + the search cache, e.g.
# "redis://host:6379/0" locally, or an AWS ElastiCache endpoint in
# production ("rediss://..." if TLS-in-transit is enabled). Required once
# you run more than one API instance - see api/valkeydb.py.
VALKEY_URL = os.environ.get("VALKEY_URL", "")

# Default per-key rate limit (requests/minute) assigned to newly created API
# keys that don't request a specific limit. This is an in-house tool shared
# by a handful of internal apps/devs, not a metered public API, so the
# default is generous; MAX_RATE_LIMIT_PER_MINUTE is the ceiling a key can
# request for itself at creation time.
DEFAULT_RATE_LIMIT_PER_MINUTE = int(os.environ.get("DEFAULT_RATE_LIMIT_PER_MINUTE", "300"))
MAX_RATE_LIMIT_PER_MINUTE = int(os.environ.get("MAX_RATE_LIMIT_PER_MINUTE", "3000"))

# Origins allowed to call the dashboard-facing endpoints (/v1/auth/*, /v1/keys*)
# from a browser. Comma-separated, e.g. "https://app.example.com,http://localhost:8080".
# Defaults to "*" for local development; restrict this in production.
CORS_ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("CORS_ALLOWED_ORIGINS", "*").split(",") if o.strip()
]

# Cap on how many URLs POST /v1/extract/batch will accept in one call -
# keeps a single request's fan-out (and its response size) bounded.
MAX_BATCH_EXTRACT_URLS = int(os.environ.get("MAX_BATCH_EXTRACT_URLS", "20"))

# Crawl/map jobs (POST /v1/crawl, POST /v1/map) run as bounded in-process
# background tasks - no separate worker to deploy. These caps are what
# keeps that safe: a job can never fetch more than DEFAULT/MAX pages, go
# deeper than DEFAULT/MAX depth, or run longer than the timeout, no matter
# what a caller asks for.
DEFAULT_CRAWL_MAX_PAGES = int(os.environ.get("DEFAULT_CRAWL_MAX_PAGES", "20"))
MAX_CRAWL_MAX_PAGES = int(os.environ.get("MAX_CRAWL_MAX_PAGES", "200"))
DEFAULT_CRAWL_MAX_DEPTH = int(os.environ.get("DEFAULT_CRAWL_MAX_DEPTH", "2"))
MAX_CRAWL_MAX_DEPTH = int(os.environ.get("MAX_CRAWL_MAX_DEPTH", "5"))
CRAWL_JOB_TIMEOUT_SECONDS = float(os.environ.get("CRAWL_JOB_TIMEOUT_SECONDS", "120"))
CRAWL_CONCURRENCY = int(os.environ.get("CRAWL_CONCURRENCY", "5"))
CRAWL_FETCH_TIMEOUT_SECONDS = float(os.environ.get("CRAWL_FETCH_TIMEOUT_SECONDS", "10"))

# DeepSeek is used for LLM-synthesized search answers (`include_answer=true`)
# and for semantic re-ranking (`semantic_rerank=true`, see api/llm/rerank.py).
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_TIMEOUT_SECONDS = float(os.environ.get("DEEPSEEK_TIMEOUT_SECONDS", "15"))
SEMANTIC_RERANK_TOP_K = int(os.environ.get("SEMANTIC_RERANK_TOP_K", "10"))

# Tavily is used as a fallback for /v1/search when Seekly's own upstream
# comes back empty or with a weak top result (see api/providers/tavily.py).
# Unset (default) means fallback never triggers - this is opt-in, since it's
# a per-call cost against a third party, not something every deployment
# wants on by default.
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
TAVILY_BASE_URL = os.environ.get("TAVILY_BASE_URL", "https://api.tavily.com")
TAVILY_TIMEOUT_SECONDS = float(os.environ.get("TAVILY_TIMEOUT_SECONDS", "15"))
# Below this final_score on the top result (or on an empty result list),
# fall back to Tavily for that query rather than return a weak/empty
# response - see api/routes/search.py.
TAVILY_FALLBACK_SCORE_THRESHOLD = float(os.environ.get("TAVILY_FALLBACK_SCORE_THRESHOLD", "0.35"))
