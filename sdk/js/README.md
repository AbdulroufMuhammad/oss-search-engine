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

// skip a separate extract() call - get each result's full page text inline
const withRaw = await client.search("rust async runtimes", { includeRawContent: true });
console.log(withRaw.results[0].raw_content);

// re-judge the top results with a DeepSeek call for fuzzy/ambiguous queries
const reranked = await client.search("that thing about quantum computers and encryption", {
  semanticRerank: true,
});
if (reranked.fallback_used) {
  console.log("served by the Tavily fallback, not Seekly's own upstream");
}

// fetch each result's full page and re-score ranking from it, not the snippet
const advanced = await client.search("rust async runtimes", { searchDepth: "advanced", chunksPerSource: 3 });
console.log(advanced.results[0].content_chunks);

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

let job = await client.crawl("https://example.com", { maxPages: 20, maxDepth: 2 });
while (job.status === "queued" || job.status === "running") {
  await new Promise((r) => setTimeout(r, 2000));
  job = await client.getCrawlJob(job.id);
}
for (const page of job.results || []) {
  console.log(page.url, page.title);
}

// map is the same job model, without page content extraction
const mapJob = await client.map("https://example.com", { maxDepth: 1 });

// restrict crawling to /blog/ paths, plus a second domain, and skip drafts
const filtered = await client.crawl("https://example.com", {
  selectPaths: ["^/blog/"],
  excludePaths: ["^/blog/drafts/"],
  selectDomains: ["blog.example.com"],
});

// natural-language link guidance - costs one DeepSeek call per fetched
// page, and is off by default server-side (CRAWL_INSTRUCTIONS_ENABLED)
// until an operator opts in, regardless of what's sent here
const guided = await client.crawl("https://example.com", {
  instructions: "only follow links about pricing",
});
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
