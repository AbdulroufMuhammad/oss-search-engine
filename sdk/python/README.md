# seekly (Python client)

A thin client for the internal Seekly search API. See the repo root's
`API_GUIDE.md` for the underlying HTTP API this wraps.

## Install

From within this repo:

```bash
pip install -e sdk/python
```

Or point at the repo directly (e.g. from another project's requirements):

```bash
pip install "git+https://github.com/AbdulroufMuhammad/Seekly.git#subdirectory=sdk/python"
```

## Usage

```python
from seekly import SeeklyClient, RateLimitError

client = SeeklyClient(api_key="sk_live_...", base_url="https://api.your-domain.com")

resp = client.search("rust async runtimes", max_results=5, include_answer=True)
print(resp.answer)
for r in resp.results:
    print(r.final_score, r.title, r.url)

# skip a separate extract() call - get each result's full page text inline
resp = client.search("rust async runtimes", include_raw_content=True)
print(resp.results[0].raw_content)

# re-judge the top results with a DeepSeek call for fuzzy/ambiguous queries
resp = client.search("that thing about quantum computers and encryption", semantic_rerank=True)
if resp.fallback_used:
    print("served by the Tavily fallback, not Seekly's own upstream")

doc = client.extract("https://example.com/article", query="pricing")
print(doc.content)

batch = client.extract_batch(["https://a.example.com", "https://b.example.com"])
for item in batch.results:
    if item.error:
        print(f"{item.url} failed: {item.error}")
    else:
        print(f"{item.url}: {item.document.word_count} words")

job = client.crawl("https://example.com", max_pages=20, max_depth=2)
while job.status in ("queued", "running"):
    time.sleep(2)
    job = client.get_crawl_job(job.id)
for page in job.results or []:
    print(page.url, page.title)

# map is the same job model, without page content extraction
map_job = client.map("https://example.com", max_depth=1)

# restrict crawling to /blog/ paths, plus a second domain, and skip drafts
job = client.crawl(
    "https://example.com",
    select_paths=[r"^/blog/"],
    exclude_paths=[r"^/blog/drafts/"],
    select_domains=["blog.example.com"],
)
```

Responses are attribute-accessible objects built directly from the
server's JSON (`resp.results[0].title`), not a separate hand-maintained
schema — new fields the server adds show up automatically without an SDK
release.

## Errors

```python
from seekly import AuthenticationError, RateLimitError, APIError

try:
    client.search("q")
except AuthenticationError:
    ...  # bad/revoked key
except RateLimitError as e:
    time.sleep(e.retry_after)  # at most 60s, then retry
except APIError as e:
    print(e.status_code, e.detail)
```

## Development

```bash
pip install -e sdk/python
pip install pytest
pytest sdk/python/tests
```
