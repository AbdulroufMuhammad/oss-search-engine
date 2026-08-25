"""Minimal Source Quality Registry: per-domain authority scores used by ranking.

A real registry (per the doc) would be a much larger, curated dataset with
tiers/types/countries. This is a small, honest starting point: a handful of
well-known high-authority domains, plus TLD heuristics (.gov/.edu), falling
back to a neutral baseline for anything unknown.
"""

_KNOWN_AUTHORITY = {
    "wikipedia.org": 0.95,
    "reuters.com": 0.95,
    "apnews.com": 0.92,
    "bbc.com": 0.9,
    "bbc.co.uk": 0.9,
    "nature.com": 0.92,
    "nytimes.com": 0.85,
    "theguardian.com": 0.85,
    "npr.org": 0.85,
    "sec.gov": 0.98,
    "who.int": 0.9,
}

_DEFAULT_AUTHORITY = 0.5


def authority_for_domain(domain: str) -> float:
    domain = domain.lower()
    # exact match, or a subdomain of a known domain (e.g. en.wikipedia.org -> wikipedia.org)
    for known, score in _KNOWN_AUTHORITY.items():
        if domain == known or domain.endswith("." + known):
            return score
    if domain.endswith(".gov") or domain.endswith(".mil"):
        return 0.9
    if domain.endswith(".edu"):
        return 0.8
    return _DEFAULT_AUTHORITY
