from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api import valkeydb
from api.config import CORS_ALLOWED_ORIGINS, UPSTREAM_SEARCH_URL, UPSTREAM_SEARCH_URLS
from api.db import init_models
from api.providers.upstream import UpstreamSearchProvider
from api.routes import analyze, auth, crawl, events, extract, finance, guide, health, keys, research, search

# The dashboard (dashboard/) is a static, no-build-step frontend for
# self-service signup/login/API-key management - see dashboard/README.md.
# Mounting it here means it ships in the same deployment/container as the
# API itself instead of needing separate static hosting; the app's own
# route-level auth (API keys, JWT) is what gates the sensitive endpoints,
# not this mount, so nothing here needs its own access control.
DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_models()
    await valkeydb.initialize()
    client = httpx.AsyncClient()
    app.state.http_client = client
    app.state.upstream_search_url = UPSTREAM_SEARCH_URL
    app.state.upstream_search_urls = UPSTREAM_SEARCH_URLS
    app.state.search_provider = UpstreamSearchProvider(UPSTREAM_SEARCH_URLS, client)
    yield
    await client.aclose()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(search.router)
app.include_router(health.router)
app.include_router(extract.router)
app.include_router(auth.router)
app.include_router(keys.router)
app.include_router(analyze.router)
app.include_router(research.router)
app.include_router(finance.router)
app.include_router(events.router)
app.include_router(crawl.router)
app.include_router(guide.router)

# Mounted last and at "/" so it never shadows the API routes above -
# Starlette matches routes in registration order, and the routers'
# concrete paths (e.g. /v1/search) are registered before this catch-all.
if DASHBOARD_DIR.is_dir():
    app.mount("/", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")
