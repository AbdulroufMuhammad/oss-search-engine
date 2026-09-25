# seekly (JavaScript/TypeScript client)

A zero-dependency client for the internal Seekly search API — just the
global `fetch`/`AbortController`/`URL` available in Node 18+ and any modern
browser. See the repo root's `API_GUIDE.md` for the underlying HTTP API
this wraps.

## Install

From within this repo (workspace-relative path):

```bash
npm install /path/to/Seekly/sdk/js
```

Or point at the repo directly from another project's `package.json`:

```json
"dependencies": {
  "seekly": "github:AbdulroufMuhammad/Seekly#path:sdk/js"
}
```

## Usage

```js
import { SeeklyClient, RateLimitError } from "seekly";

const client = new SeeklyClient({
  apiKey: process.env.SEEKLY_API_KEY,
  baseUrl: "https://api.your-domain.com",
});

const resp = await client.search("rust async runtimes", { maxResults: 5, includeAnswer: true });
console.log(resp.answer);
for (const r of resp.results) {
  console.log(r.final_score, r.title, r.url);
}

const doc = await client.extract("https://example.com/article", { query: "pricing" });
console.log(doc.content);

const batch = await client.extractBatch(["https://a.example.com", "https://b.example.com"]);
for (const item of batch.results) {
  if (item.error) {
    console.log(`${item.url} failed: ${item.error}`);
  } else {
    console.log(`${item.url}: ${item.document.word_count} words`);
  }
}
```

Responses are plain parsed JSON, not wrapped model classes — new fields the
server adds show up automatically without an SDK release. Field names
follow the server's JSON exactly (`snake_case`, e.g. `final_score`), while
this client's own options use `camelCase` (`maxResults`) to match JS
convention.

## Errors

```js
import { AuthenticationError, RateLimitError, APIError } from "seekly";

try {
  await client.search("q");
} catch (err) {
  if (err instanceof AuthenticationError) {
    // bad/revoked key
  } else if (err instanceof RateLimitError) {
    await new Promise((r) => setTimeout(r, err.retryAfter * 1000)); // at most 60s, then retry
  } else if (err instanceof APIError) {
    console.log(err.statusCode, err.detail);
  }
}
```

## Development

```bash
npm test
```

Uses Node's built-in test runner (`node:test`) — no test framework
dependency either.
