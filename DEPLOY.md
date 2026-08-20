# Deploying to Fly.io

This repo builds a single image (root `Dockerfile`) containing SearXNG plus a
Caddy reverse proxy that enforces a bearer-token check (`container/Caddyfile`,
`container/start.sh`) — see those files for how the token gate works. Fly's
public port (8080) is Caddy; SearXNG itself only listens on
`127.0.0.1:8081` inside the container and is never directly reachable.

## 1. Launch the app (no deploy yet)

```sh
fly launch --no-deploy
```

This creates/updates `fly.toml` with your app name and region. It should
detect the root `Dockerfile` automatically (no separate Fly builder needed).

## 2. Set the auth token secret

```sh
fly secrets set AUTH_TOKEN=$(openssl rand -hex 32)
```

Keep a copy of this value somewhere safe (e.g. a secrets manager) — you'll
need to hand it to whatever service calls this SearXNG instance.

## 3. Deploy

```sh
fly deploy
```

## 4. Test

```sh
curl -H "Authorization: Bearer <AUTH_TOKEN>" \
  "https://<your-app-name>.fly.dev/search?q=test&format=json"
```

A request without the header (or with the wrong token) should get a 401 from
Caddy, e.g.:

```sh
curl -i "https://<your-app-name>.fly.dev/search?q=test&format=json"
# HTTP/2 401
```
