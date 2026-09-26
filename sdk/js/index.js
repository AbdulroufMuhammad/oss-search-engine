/**
 * JS/TS client for the Seekly search API. Zero runtime dependencies - just
 * the global `fetch`/`AbortController`/`URL` available in Node 18+ and any
 * modern browser.
 *
 * Responses are returned as plain parsed JSON (not wrapped model classes),
 * so new fields the server adds show up automatically without an SDK
 * release, at the cost of no compile-time typing on response shape - use
 * the field names documented in the repo root's API_GUIDE.md.
 */

export class SeeklyError extends Error {}

/** 401 - missing, invalid, or revoked API key. */
export class AuthenticationError extends SeeklyError {}

/**
 * 429 - rate limit exceeded. `retryAfter` is the number of seconds until
 * the current window resets (at most 60) - there's no backoff/lockout
 * beyond that, so retrying after waiting `retryAfter` seconds is always
 * the right move.
 */
export class RateLimitError extends SeeklyError {
  constructor(message, retryAfter) {
    super(message);
    this.retryAfter = retryAfter;
  }
}

/** Any other non-2xx response. */
export class APIError extends SeeklyError {
  constructor(message, statusCode, detail) {
    super(message);
    this.statusCode = statusCode;
    this.detail = detail;
  }
}

function join(value) {
  if (value === undefined || value === null) return undefined;
  return Array.isArray(value) ? value.join(",") : value;
}

function errorDetail(data, status) {
  if (data && typeof data === "object" && "detail" in data) return String(data.detail);
  return `HTTP ${status}`;
}

export class SeeklyClient {
  /**
   * @param {object} options
   * @param {string} options.apiKey
   * @param {string} options.baseUrl
   * @param {number} [options.timeoutMs=30000]
   * @param {typeof fetch} [options.fetchImpl] - override for testing
   */
  constructor({ apiKey, baseUrl, timeoutMs = 30000, fetchImpl } = {}) {
    if (!apiKey) throw new Error("apiKey is required");
    if (!baseUrl) throw new Error("baseUrl is required");
    this.apiKey = apiKey;
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.timeoutMs = timeoutMs;
    this._fetch = fetchImpl || fetch;
  }

  async _request(method, path, { params, body } = {}) {
    const url = new URL(this.baseUrl + path);
    if (params) {
      for (const [key, value] of Object.entries(params)) {
        if (value !== undefined && value !== null) {
          url.searchParams.set(key, String(value));
        }
      }
    }

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    let resp;
    try {
      resp = await this._fetch(url.toString(), {
        method,
        headers: {
          "X-API-Key": this.apiKey,
          ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timeout);
    }

    const data = await resp.json().catch(() => null);

    if (resp.status === 401) {
      throw new AuthenticationError(errorDetail(data, resp.status));
    }
    if (resp.status === 429) {
      const retryAfterHeader = resp.headers.get("Retry-After");
      const retryAfter = retryAfterHeader ? parseInt(retryAfterHeader, 10) : undefined;
      throw new RateLimitError(errorDetail(data, resp.status), retryAfter);
    }
    if (!resp.ok) {
      throw new APIError(errorDetail(data, resp.status), resp.status, data);
    }
    return data;
  }

  /**
   * GET /v1/search
   * @param {string} query
   * @param {object} [options]
   * @param {number} [options.maxResults=10]
   * @param {string} [options.categories]
   * @param {boolean} [options.expand=false]
   * @param {boolean} [options.includeAnswer=false]
   * @param {string[]|string} [options.includeDomains]
   * @param {string[]|string} [options.excludeDomains]
   * @param {"day"|"week"|"month"|"year"} [options.timeRange]
   * @param {"general"|"news"} [options.topic="general"]
   * @param {boolean} [options.includeImages=false]
   * @param {boolean} [options.includeRawContent=false] - attach each
   *   result's full extracted page text as `.raw_content` (fails soft to
   *   `null` per-URL) instead of a separate `extract` call.
   */
  search(query, options = {}) {
    const {
      maxResults = 10,
      categories,
      expand = false,
      includeAnswer = false,
      includeDomains,
      excludeDomains,
      timeRange,
      topic = "general",
      includeImages = false,
      includeRawContent = false,
    } = options;
    return this._request("GET", "/v1/search", {
      params: {
        q: query,
        max_results: maxResults,
        categories,
        expand,
        include_answer: includeAnswer,
        include_domains: join(includeDomains),
        exclude_domains: join(excludeDomains),
        time_range: timeRange,
        topic,
        include_images: includeImages,
        include_raw_content: includeRawContent,
      },
    });
  }

  /**
   * GET /v1/extract for a single URL.
   * @param {string} url
   * @param {object} [options]
   * @param {string} [options.query]
   * @param {number} [options.maxPassages]
   */
  extract(url, options = {}) {
    const { query, maxPassages } = options;
    return this._request("GET", "/v1/extract", {
      params: { url, query, max_passages: maxPassages },
    });
  }

  /**
   * POST /v1/extract/batch for up to the server's configured cap (20 by
   * default). Returns `{ results: [{ url, document, error }, ...] }`, one
   * entry per URL in the same order - a failure on one URL never throws
   * for the others.
   * @param {string[]} urls
   * @param {object} [options]
   * @param {string} [options.query]
   * @param {number} [options.maxPassages]
   */
  extractBatch(urls, options = {}) {
    const { query, maxPassages } = options;
    const body = { urls };
    if (query !== undefined) body.query = query;
    if (maxPassages !== undefined) body.max_passages = maxPassages;
    return this._request("POST", "/v1/extract/batch", { body });
  }

  /** GET /v1/health. No API key required, but harmless to send one. */
  health() {
    return this._request("GET", "/v1/health");
  }

  /**
   * POST /v1/crawl. Starts a bounded crawl from `url`, following
   * same-domain links and extracting each page's main content as Markdown.
   * Returns the job immediately in "queued" status - poll
   * `getCrawlJob(job.id)` for progress and results.
   * @param {string} url
   * @param {object} [options]
   * @param {number} [options.maxPages]
   * @param {number} [options.maxDepth]
   * @param {string[]} [options.selectPaths] - regex allowlist matched
   *   against each discovered link's URL path
   * @param {string[]} [options.excludePaths] - regex denylist, checked
   *   after selectPaths
   * @param {string[]} [options.selectDomains] - extra domains (beyond
   *   `url`'s own) that links are allowed to follow into
   * @param {boolean} [options.allowExternal] - follow links off the
   *   starting domain entirely; every such link still goes through the
   *   same SSRF guard as `extract`
   */
  crawl(url, options = {}) {
    return this._createCrawlJob("/v1/crawl", url, options);
  }

  /** GET /v1/crawl/{jobId} */
  getCrawlJob(jobId) {
    return this._request("GET", `/v1/crawl/${jobId}`);
  }

  /**
   * POST /v1/map. Same job model and filter options as `crawl`, but
   * discovers URLs without extracting page content - faster and cheaper.
   * Poll `getMapJob(job.id)` for progress and results.
   * @param {string} url
   * @param {object} [options]
   * @param {number} [options.maxPages]
   * @param {number} [options.maxDepth]
   * @param {string[]} [options.selectPaths]
   * @param {string[]} [options.excludePaths]
   * @param {string[]} [options.selectDomains]
   * @param {boolean} [options.allowExternal]
   */
  map(url, options = {}) {
    return this._createCrawlJob("/v1/map", url, options);
  }

  /** GET /v1/map/{jobId} */
  getMapJob(jobId) {
    return this._request("GET", `/v1/map/${jobId}`);
  }

  _createCrawlJob(
    path,
    url,
    { maxPages, maxDepth, selectPaths, excludePaths, selectDomains, allowExternal } = {}
  ) {
    const body = { url };
    if (maxPages !== undefined) body.max_pages = maxPages;
    if (maxDepth !== undefined) body.max_depth = maxDepth;
    if (selectPaths !== undefined) body.select_paths = selectPaths;
    if (excludePaths !== undefined) body.exclude_paths = excludePaths;
    if (selectDomains !== undefined) body.select_domains = selectDomains;
    if (allowExternal !== undefined) body.allow_external = allowExternal;
    return this._request("POST", path, { body });
  }
}
