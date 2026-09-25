# Seekly dashboard

A static, no-build-step frontend for self-service signup, login, and API
key management. It talks directly to the `/v1/auth` and `/v1/keys`
endpoints on the API (see the repo root `README.rst`).

## Run it locally

1. Start the API (see the root README's Quick start).
2. Serve this directory as static files, e.g.:

   ```bash
   cd dashboard
   python3 -m http.server 8080
   ```

3. Open `http://127.0.0.1:8080`. Sign up, then create an API key from the
   dashboard — it's shown once, at creation.

## Configuration

Edit `config.js` to point at your API deployment:

```js
window.SEEKLY_API_BASE = "https://api.your-domain.com";
```

The API must allow the dashboard's origin via CORS — set
`CORS_ALLOWED_ORIGINS` on the API (comma-separated list of origins;
defaults to `*` for local development, which is fine here since the
dashboard uses a bearer token, not cookies).

## Deploying

These are plain static files — any static host works (S3 + CloudFront,
Netlify, Vercel, nginx, GitHub Pages). There's no build step: just publish
`index.html`, `dashboard.html`, `styles.css`, `api.js`, and `config.js`
(with `config.js` edited for your API's URL) as-is.

If the API is deployed behind the repo's old Fly.io Caddy wrapper (see the
root `DEPLOY.md`), this won't work — that wrapper requires a shared
`AUTH_TOKEN` on every request, including signup, which defeats self-service.
It needs to be dropped (see "Deploying on AWS" in the root `README.rst`) for
this dashboard to be usable as intended.

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
