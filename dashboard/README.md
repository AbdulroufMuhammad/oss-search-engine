# Seekly dashboard

A static, no-build-step frontend for self-service signup, login, and API
key management. It talks directly to the `/v1/auth` and `/v1/keys`
endpoints on the API (see the repo root `README.rst`).

## Run it locally

By default this is bundled with the API — `api/app.py` mounts this
directory, so starting the API (see the root README's Quick start) is
enough; open `http://127.0.0.1:8000/`. Sign up, then create an API key from
the dashboard — it's shown once, at creation.

To run it as a separate process instead (e.g. while iterating on the
frontend with a different reload setup), serve this directory yourself:

```bash
cd dashboard
python3 -m http.server 8080
```

Then edit `config.js` to point at the API (see Configuration below) and
open `http://127.0.0.1:8080`.

## Configuration

`config.js` defaults to `window.SEEKLY_API_BASE = ""` — same-origin, which
is correct when the API serves this directory itself (the default). Only
edit it if you're hosting the dashboard separately from the API:

```js
window.SEEKLY_API_BASE = "https://api.your-domain.com";
```

In that case the API must also allow the dashboard's origin via CORS — set
`CORS_ALLOWED_ORIGINS` on the API (comma-separated list of origins;
defaults to `*` for local development, which is fine here since the
dashboard uses a bearer token, not cookies).

## Deploying

The default path needs nothing extra: it's already part of the API's own
container image (see the root `README.rst`'s "Deploying" section and
`DEPLOY.md`) and gets served at the same URL as the API.

To host it separately instead, these are plain static files — any static
host works (S3 + CloudFront, Netlify, Vercel, nginx, GitHub Pages). There's
no build step: just publish `index.html`, `dashboard.html`, `styles.css`,
`api.js`, and `config.js` (with `config.js` edited for your API's URL) as-is.

## What's here

- `index.html` — landing page + sign in / sign up
- `dashboard.html` — list, create, and revoke API keys (requires being
  signed in; redirects to `index.html` otherwise)
- `api.js` — thin fetch wrapper around the auth/keys endpoints, plus
  localStorage-backed session handling
- `config.js` — the one thing you edit per deployment (API base URL)
- `styles.css` — shared styling, no framework

## Not yet built

This is a first pass focused on the key-management loop. Natural next
additions: password reset, and per-key usage/request charts (the API
doesn't expose usage metrics yet either).
