import os

SEARXNG_UPSTREAM = os.environ.get("SEARXNG_UPSTREAM", "http://127.0.0.1:8081")
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "300"))
