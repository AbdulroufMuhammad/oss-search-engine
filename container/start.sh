#!/bin/sh
# shellcheck shell=dash
set -eu

# Starts SearXNG (via the original entrypoint.sh) in the background, bound to
# 127.0.0.1:8081 (see GRANIAN_HOST/GRANIAN_PORT in the Dockerfile), then
# starts transform.py (reshapes SearXNG's JSON into a Tavily-style response)
# on 127.0.0.1:8082, then runs Caddy in the foreground on the container's
# public port (8080). Caddy is the only process reachable from outside the
# container and enforces the AUTH_TOKEN bearer-token check defined in
# container/Caddyfile, forwarding authorized requests to transform.py.

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

/usr/local/searxng/.venv/bin/python /usr/local/searxng/transform.py &

exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
