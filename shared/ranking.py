"""System 5: Ranking Engine — deterministic, rule-based scoring (no AI/embeddings).

The doc's spec includes "semantic_relevance", which implies embedding-based
similarity — that's explicitly out of scope for this phase ("do NOT implement
AI"). This implements the deterministic components only: keyword (lexical)
relevance, freshness, source authority, content quality, and a duplicate
penalty based on content fingerprinting (distinct from the URL-level dedup
in System 3 — this catches near-identical content at *different* URLs).
"""

import hashlib
import math
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from shared.source_registry import authority_for_domain

_WORD_RE = re.compile(r"[a-z0-9]+")

# weights for the deterministic components that make up final_score (before
# the duplicate penalty is applied multiplicatively on top)
_WEIGHT_RELEVANCE = 0.45
_WEIGHT_AUTHORITY = 0.25
_WEIGHT_FRESHNESS = 0.15
_WEIGHT_CONTENT_QUALITY = 0.15

# exp(-age/FRESHNESS_DECAY_DAYS): at age == this many days, score is 1/e (~0.37),
# not 0.5 — "decay constant"/"time constant", not a true half-life (which would
# need a ln(2) factor). Named for what the code actually computes.
FRESHNESS_DECAY_DAYS = 30


def _tokenize(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def keyword_relevance(query: str, title: str, content: str) -> float:
    q_tokens = _tokenize(query)
    if not q_tokens:
        return 0.0
    title_overlap = len(q_tokens & _tokenize(title)) / len(q_tokens)
    content_overlap = len(q_tokens & _tokenize(content)) / len(q_tokens)
    return round(min(1.0, 0.7 * title_overlap + 0.3 * content_overlap), 4)


def passage_relevance(query: str, passage: str) -> float:
    """Score a single passage's lexical relevance to `query`.

    A passage has no separate "title" concept the way a search result does.
    Passing the passage itself as both the "title" and "content" arguments
    makes the title-overlap and content-overlap terms identical (both just
    "fraction of query tokens present in this passage"), so the 0.7/0.3
    weights collapse to a single 1.0 weight and the result is simply that
    overlap ratio, landing cleanly in [0, 1]. Kept as a thin wrapper rather
    than calling `keyword_relevance` directly at call sites so the "how do
    we score a passage" decision lives in one place.
    """
    return keyword_relevance(query, passage, passage)


def freshness_score(published_at: str | None) -> float:
    if not published_at:
        return 0.5  # unknown date: neutral, not penalized
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return 0.5
    age_days = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400)
    return round(math.exp(-age_days / FRESHNESS_DECAY_DAYS), 4)


def content_quality_score(title: str, content: str) -> float:
    if not title.strip() and not content.strip():
        return 0.0
    length_score = min(1.0, len(content) / 300)
    has_title = 1.0 if title.strip() else 0.0
    return round(0.7 * length_score + 0.3 * has_title, 4)


def domain_of(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def content_fingerprint(content: str) -> str:
    normalized = re.sub(r"\W+", "", content.lower())[:200]
    return hashlib.sha256(normalized.encode()).hexdigest()


def final_score(
    *, relevance: float, authority: float, freshness: float, content_quality: float, duplicate_penalty: float
) -> float:
    base = (
        _WEIGHT_RELEVANCE * relevance
        + _WEIGHT_AUTHORITY * authority
        + _WEIGHT_FRESHNESS * freshness
        + _WEIGHT_CONTENT_QUALITY * content_quality
    )
    return round(base * (1.0 - duplicate_penalty), 4)
