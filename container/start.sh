#!/bin/sh
# shellcheck shell=dash
set -eu

# Starts SearXNG (via the original entrypoint.sh) in the background, bound to
# 127.0.0.1:8081 (see GRANIAN_HOST/GRANIAN_PORT in the Dockerfile), then
# starts the FastAPI intelligence gateway (api/app.py) as a second Granian
# process, in ASGI mode, on 127.0.0.1:8083, then runs Caddy in the foreground
# on the container's public port (8080). Caddy is the only process reachable
# from outside the container and enforces the AUTH_TOKEN bearer-token check
# defined in container/Caddyfile, forwarding authorized requests to the
# FastAPI gateway, which is the only thing that talks to SearXNG directly.

if [ -z "${AUTH_TOKEN:-}" ]; then
    cat <<EOF
!!!
!!! ERROR
!!! AUTH_TOKEN is not set. Set it with: fly secrets set AUTH_TOKEN=...
!!!
EOF
    exit 1
fi

/usr/local/searxng/entrypoint.sh &

# Env vars set inline on this one command only, not exported globally, so
# they don't leak into entrypoint.sh's own GRANIAN_PORT=8081/GRANIAN_INTERFACE=wsgi
# SearXNG process above. GRANIAN_BLOCKING_THREADS must be overridden to 1
# here: the image-level ENV sets it to 4 for SearXNG's WSGI process, but
# that's container-wide (every process inherits it), and ASGI mode doesn't
# support blocking threads > 1.
GRANIAN_INTERFACE=asgi GRANIAN_HOST=127.0.0.1 GRANIAN_PORT=8083 GRANIAN_PROCESS_NAME=searxng-api \
GRANIAN_BLOCKING_THREADS=1 \
    /usr/local/searxng/.venv/bin/granian api.app:app &

exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
