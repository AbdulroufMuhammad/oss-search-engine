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

FRESHNESS_HALF_LIFE_DAYS = 30


def _tokenize(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def keyword_relevance(query: str, title: str, content: str) -> float:
    q_tokens = _tokenize(query)
    if not q_tokens:
        return 0.0
    title_overlap = len(q_tokens & _tokenize(title)) / len(q_tokens)
    content_overlap = len(q_tokens & _tokenize(content)) / len(q_tokens)
    return round(min(1.0, 0.7 * title_overlap + 0.3 * content_overlap), 4)


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
    return round(math.exp(-age_days / FRESHNESS_HALF_LIFE_DAYS), 4)


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
