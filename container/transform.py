#!/usr/bin/env python3
"""Reshaping proxy: turns SearXNG's raw JSON into a compact, Tavily-style shape.

Sits between Caddy (public, auth-gated, port 8080) and SearXNG
(127.0.0.1:8081). Listens on 127.0.0.1:8082. Only /search responses whose
content-type is application/json get reshaped; every other path/format is
passed through byte-for-byte unmodified.
"""
import json
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

UPSTREAM = "http://127.0.0.1:8081"
LISTEN = ("127.0.0.1", 8082)
DEFAULT_MAX_RESULTS = 10
CONTENT_TRUNCATE = 500


def reshape(data: dict, max_results: int) -> dict:
    answer = None
    answers = data.get("answers") or []
    if answers:
        answer = " ".join(a.get("answer", str(a)) if isinstance(a, dict) else str(a) for a in answers)
    else:
        infoboxes = data.get("infoboxes") or []
        if infoboxes:
            answer = infoboxes[0].get("content") or None

    seen_urls = set()
    cleaned = []
    for r in data.get("results", []):
        url = r.get("url")
        if not url or url in seen_urls:
            continue
        title = (r.get("title") or "").strip()
        content = (r.get("content") or "").strip()
        if not title and not content:
            continue
        seen_urls.add(url)
        if len(content) > CONTENT_TRUNCATE:
            content = content[:CONTENT_TRUNCATE].rsplit(" ", 1)[0] + "..."
        cleaned.append({
            "title": title,
            "url": url,
            "content": content,
            "score": r.get("score", 0),
        })

    cleaned.sort(key=lambda r: r["score"], reverse=True)
    cleaned = cleaned[:max_results]

    return {
        "query": data.get("query", ""),
        "answer": answer,
        "results": cleaned,
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # Caddy already logs at the edge; keep this layer quiet

    def _proxy(self):
        parts = urlsplit(self.path)
        qs = parse_qs(parts.query)
        max_results = DEFAULT_MAX_RESULTS
        if "max_results" in qs:
            try:
                max_results = max(1, min(50, int(qs["max_results"][0])))
            except ValueError:
                pass

        body = None
        length = self.headers.get("Content-Length")
        if length:
            body = self.rfile.read(int(length))

        req = urllib.request.Request(UPSTREAM + self.path, data=body, method=self.command)
        for h in ("Content-Type", "Accept", "User-Agent", "Cookie"):
            if h in self.headers:
                req.add_header(h, self.headers[h])

        start = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw = resp.read()
                status = resp.status
                content_type = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            raw = e.read()
            status = e.code
            content_type = e.headers.get("Content-Type", "") if e.headers else ""
        except Exception:
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"upstream unavailable")
            return

        if parts.path == "/search" and "application/json" in content_type:
            try:
                data = json.loads(raw)
                out = reshape(data, max_results)
                out["response_time"] = round(time.monotonic() - start, 3)
                payload = json.dumps(out).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            except (json.JSONDecodeError, KeyError, TypeError):
                pass  # fall through and return the raw upstream response

        self.send_response(status)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self._proxy()

    def do_POST(self):
        self._proxy()


if __name__ == "__main__":
    server = ThreadingHTTPServer(LISTEN, Handler)
    server.serve_forever()
