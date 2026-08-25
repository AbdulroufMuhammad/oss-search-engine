"""URL canonicalization for deduplication (System 3).

Collapses near-duplicate URLs (tracking params, www vs non-www, trailing
slash, fragments) so they dedupe as the same underlying document. Does NOT
follow HTTP redirects — that requires actually fetching the URL, which is
System 4 (Content Extraction) territory, not this.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "gclid",
    "fbclid",
    "msclkid",
}


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url)

    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[len("www.") :]

    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    query_pairs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in _TRACKING_PARAMS]
    query_pairs.sort()
    query = urlencode(query_pairs)

    return urlunsplit((scheme, netloc, path, query, ""))
