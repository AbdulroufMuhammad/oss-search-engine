# Deploying to Fly.io

This repo builds a single image (root `Dockerfile`) containing a
SearXNG-based search engine (see the root README's *Credits* section), the
FastAPI gateway (`api/`), and the dashboard (`dashboard/`) — see
`container/start.sh` for how the two processes are wired together. Fly's
public port (8080) is the FastAPI gateway; SearXNG itself only listens on
`127.0.0.1:8081` inside the container and is never directly reachable.

There's no separate auth wrapper in front of the gateway — it has its own
route-level auth (API keys for `/v1/search`, `/v1/extract`, `/v1/crawl`,
`/v1/map`; JWT sessions for `/v1/keys`), and `/v1/auth/signup` plus the
dashboard are meant to be publicly reachable for self-service signup. See
the root `README.rst` for the full auth model and required env vars
(`JWT_SECRET` in particular — set a real one, not the random per-process
fallback).

## 1. Launch the app (no deploy yet)

```sh
fly launch --no-deploy
```

This creates/updates `fly.toml` with your app name and region. It should
detect the root `Dockerfile` automatically (no separate Fly builder needed).

## 2. Set required secrets

```sh
fly secrets set JWT_SECRET=$(openssl rand -hex 32)
```

Set `DATABASE_URL`/`VALKEY_URL`/any other config from `README.rst`'s
Configuration section as needed for your setup; SQLite + the in-process
rate-limit/cache fallback both work for a single-instance deployment, but
neither survives across multiple instances — see README.rst's "Deploying
on AWS" section if you need that.

## 3. Deploy

```sh
fly deploy
```

## 4. Test

```sh
# Dashboard
curl -i "https://<your-app-name>.fly.dev/"

# Sign up, then search with the resulting API key
curl -X POST "https://<your-app-name>.fly.dev/v1/auth/signup" \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "..."}'
```
