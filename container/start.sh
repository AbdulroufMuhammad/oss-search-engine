#!/bin/sh
# shellcheck shell=dash
set -eu

# Starts SearXNG (via the original entrypoint.sh) in the background, bound
# to 127.0.0.1:8081 (GRANIAN_HOST/GRANIAN_PORT set in the Dockerfile), then
# runs the FastAPI gateway (api/app.py) in the foreground as a second
# Granian process, in ASGI mode, on 0.0.0.0:8080 - the container's public
# port. SearXNG is never reachable from outside the container; the gateway
# is the only thing that talks to it directly, and it's also what serves
# the dashboard (api/app.py mounts dashboard/ - see that file).
#
# There is no separate auth wrapper in front of the gateway: it has its own
# route-level auth (API keys for /v1/search, /v1/extract, /v1/crawl,
# /v1/map; JWT sessions for /v1/keys), and /v1/auth/signup plus the
# dashboard are meant to be publicly reachable for self-service - a blanket
# bearer-token gate in front of everything (the old Caddy/AUTH_TOKEN setup)
# actively conflicted with that. See README.rst's "Deploying" section.

/usr/local/searxng/entrypoint.sh &

# Env vars set inline on this one command only, not exported globally, so
# they don't leak into entrypoint.sh's own GRANIAN_PORT=8081/GRANIAN_INTERFACE=wsgi
# SearXNG process above. GRANIAN_BLOCKING_THREADS must be overridden to 1
# here: the image-level ENV sets it to 4 for SearXNG's WSGI process, but
# that's container-wide (every process inherits it), and ASGI mode doesn't
# support blocking threads > 1.
exec env GRANIAN_INTERFACE=asgi GRANIAN_HOST=0.0.0.0 GRANIAN_PORT=8080 GRANIAN_PROCESS_NAME=seekly-api \
    GRANIAN_BLOCKING_THREADS=1 \
    /usr/local/searxng/.venv/bin/granian api.app:app
