import assert from "node:assert/strict";
import { test } from "node:test";

import { APIError, AuthenticationError, RateLimitError, SeeklyClient } from "../index.js";

function fakeFetch({ status, json, headers = {} }) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init });
    return {
      status,
      ok: status >= 200 && status < 300,
      headers: { get: (name) => headers[name] },
      json: async () => json,
    };
  };
  return { fetchImpl, calls };
}

function makeClient({ status = 200, json = {}, headers = {} } = {}) {
  const { fetchImpl, calls } = fakeFetch({ status, json, headers });
  const client = new SeeklyClient({ apiKey: "sk_live_test", baseUrl: "https://api.example.com", fetchImpl });
  return { client, calls };
}

test("requires apiKey", () => {
  assert.throws(() => new SeeklyClient({ baseUrl: "https://api.example.com" }));
});

test("requires baseUrl", () => {
  assert.throws(() => new SeeklyClient({ apiKey: "sk_live_x" }));
});

test("search sends API key header and query params", async () => {
  const { client, calls } = makeClient({
    json: { query: "q", answer: null, results: [], images: [], response_time: 0.1 },
  });
  const resp = await client.search("rust async runtimes", { maxResults: 5, includeAnswer: true });

  const [call] = calls;
  assert.equal(call.init.headers["X-API-Key"], "sk_live_test");
  const url = new URL(call.url);
  assert.equal(url.pathname, "/v1/search");
  assert.equal(url.searchParams.get("q"), "rust async runtimes");
  assert.equal(url.searchParams.get("max_results"), "5");
  assert.equal(url.searchParams.get("include_answer"), "true");
  assert.equal(resp.query, "q");
});

test("search joins domain list options into comma-separated params", async () => {
  const { client, calls } = makeClient({
    json: { query: "q", answer: null, results: [], images: [], response_time: 0.1 },
  });
  await client.search("q", { includeDomains: ["python.org", "docs.python.org"], excludeDomains: "spam.com" });

  const url = new URL(calls[0].url);
  assert.equal(url.searchParams.get("include_domains"), "python.org,docs.python.org");
  assert.equal(url.searchParams.get("exclude_domains"), "spam.com");
});

test("extract passes url and query as params", async () => {
  const { client, calls } = makeClient({
    json: { url: "https://x", word_count: 1, content: "c", passages: [] },
  });
  const doc = await client.extract("https://x", { query: "pricing" });

  const url = new URL(calls[0].url);
  assert.equal(url.searchParams.get("url"), "https://x");
  assert.equal(url.searchParams.get("query"), "pricing");
  assert.equal(doc.content, "c");
});

test("extractBatch posts a JSON body", async () => {
  const { client, calls } = makeClient({ json: { results: [] } });
  await client.extractBatch(["https://a", "https://b"], { query: "pricing" });

  assert.equal(calls[0].init.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].init.body), { urls: ["https://a", "https://b"], query: "pricing" });
});

test("401 throws AuthenticationError", async () => {
  const { client } = makeClient({ status: 401, json: { detail: "invalid or revoked API key" } });
  await assert.rejects(client.search("q"), (err) => {
    assert.ok(err instanceof AuthenticationError);
    assert.match(err.message, /invalid or revoked API key/);
    return true;
  });
});

test("429 throws RateLimitError with retryAfter", async () => {
  const { client } = makeClient({
    status: 429,
    json: { detail: "rate limit exceeded" },
    headers: { "Retry-After": "42" },
  });
  await assert.rejects(client.search("q"), (err) => {
    assert.ok(err instanceof RateLimitError);
    assert.equal(err.retryAfter, 42);
    return true;
  });
});

test("other non-2xx throws APIError with statusCode", async () => {
  const { client } = makeClient({ status: 502, json: { detail: "upstream search engine unavailable" } });
  await assert.rejects(client.search("q"), (err) => {
    assert.ok(err instanceof APIError);
    assert.equal(err.statusCode, 502);
    assert.match(err.message, /unavailable/);
    return true;
  });
});

test("health returns parsed JSON", async () => {
  const { client } = makeClient({ json: { upstream: "ok" } });
  const resp = await client.health();
  assert.equal(resp.upstream, "ok");
});

function jobResponse(mode = "crawl", status = "queued") {
  return {
    id: "job-1",
    mode,
    start_url: "https://example.com",
    max_pages: 20,
    max_depth: 2,
    status,
    error: null,
    results: null,
    created_at: "2026-01-01T00:00:00Z",
    finished_at: null,
  };
}

test("crawl posts url and returns queued job", async () => {
  const { client, calls } = makeClient({ status: 201, json: jobResponse() });
  const job = await client.crawl("https://example.com", { maxPages: 5, maxDepth: 1 });

  const url = new URL(calls[0].url);
  assert.equal(url.pathname, "/v1/crawl");
  assert.equal(calls[0].init.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    url: "https://example.com",
    max_pages: 5,
    max_depth: 1,
  });
  assert.equal(job.status, "queued");
  assert.equal(job.mode, "crawl");
});

test("crawl omits unset options from body", async () => {
  const { client, calls } = makeClient({ status: 201, json: jobResponse() });
  await client.crawl("https://example.com");
  assert.deepEqual(JSON.parse(calls[0].init.body), { url: "https://example.com" });
});

test("getCrawlJob hits the right path", async () => {
  const { client, calls } = makeClient({ json: jobResponse("crawl", "done") });
  const job = await client.getCrawlJob("job-1");
  const url = new URL(calls[0].url);
  assert.equal(url.pathname, "/v1/crawl/job-1");
  assert.equal(job.status, "done");
});

test("map posts url and returns queued job", async () => {
  const { client, calls } = makeClient({ status: 201, json: jobResponse("map") });
  const job = await client.map("https://example.com");
  const url = new URL(calls[0].url);
  assert.equal(url.pathname, "/v1/map");
  assert.equal(job.mode, "map");
});

test("getMapJob hits the right path", async () => {
  const { client, calls } = makeClient({ json: jobResponse("map", "done") });
  const job = await client.getMapJob("job-1");
  const url = new URL(calls[0].url);
  assert.equal(url.pathname, "/v1/map/job-1");
  assert.equal(job.status, "done");
});

test("search sends includeRawContent as include_raw_content", async () => {
  const { client, calls } = makeClient({
    json: { query: "q", answer: null, results: [], images: [], response_time: 0.1 },
  });
  await client.search("q", { includeRawContent: true });
  const url = new URL(calls[0].url);
  assert.equal(url.searchParams.get("include_raw_content"), "true");
});

test("search sends semanticRerank as semantic_rerank", async () => {
  const { client, calls } = makeClient({
    json: { query: "q", answer: null, results: [], images: [], response_time: 0.1 },
  });
  await client.search("q", { semanticRerank: true });
  const url = new URL(calls[0].url);
  assert.equal(url.searchParams.get("semantic_rerank"), "true");
});

test("search response exposes fallback_used", async () => {
  const { client } = makeClient({
    json: {
      query: "q",
      answer: null,
      results: [],
      images: [],
      response_time: 0.1,
      fallback_used: true,
    },
  });
  const resp = await client.search("q");
  assert.equal(resp.fallback_used, true);
});

test("crawl sends path and domain filters", async () => {
  const { client, calls } = makeClient({ status: 201, json: jobResponse() });
  await client.crawl("https://example.com", {
    selectPaths: ["^/blog/"],
    excludePaths: ["^/blog/drafts/"],
    selectDomains: ["other.example.com"],
    allowExternal: true,
  });
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    url: "https://example.com",
    select_paths: ["^/blog/"],
    exclude_paths: ["^/blog/drafts/"],
    select_domains: ["other.example.com"],
    allow_external: true,
  });
});

test("map sends path and domain filters", async () => {
  const { client, calls } = makeClient({ status: 201, json: jobResponse("map") });
  await client.map("https://example.com", { selectDomains: ["other.example.com"] });
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    url: "https://example.com",
    select_domains: ["other.example.com"],
  });
});

test("crawl sends instructions", async () => {
  const { client, calls } = makeClient({ status: 201, json: jobResponse() });
  await client.crawl("https://example.com", { instructions: "only follow links about pricing" });
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    url: "https://example.com",
    instructions: "only follow links about pricing",
  });
});

test("search sends advanced depth options", async () => {
  const { client, calls } = makeClient({
    json: { query: "q", answer: null, results: [], images: [], response_time: 0.1 },
  });
  await client.search("q", {
    searchDepth: "advanced",
    chunksPerSource: 3,
    includeImageDescriptions: true,
    country: "japan",
  });
  const url = new URL(calls[0].url);
  assert.equal(url.searchParams.get("search_depth"), "advanced");
  assert.equal(url.searchParams.get("chunks_per_source"), "3");
  assert.equal(url.searchParams.get("include_image_descriptions"), "true");
  assert.equal(url.searchParams.get("country"), "japan");
});

test("search defaults searchDepth to basic", async () => {
  const { client, calls } = makeClient({
    json: { query: "q", answer: null, results: [], images: [], response_time: 0.1 },
  });
  await client.search("q");
  const url = new URL(calls[0].url);
  assert.equal(url.searchParams.get("search_depth"), "basic");
});
