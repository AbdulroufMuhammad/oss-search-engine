"""System 1: Query Intelligence — deterministic, rule-based query understanding (no AI/LLM).

Given a raw search query, this module extracts a lightweight structured
understanding of it: a coarse intent label, candidate entities/topics, a
freshness signal, and a short list of rule-based query expansions. Every
piece of this is regex/keyword-list driven, in the same spirit as
`shared/ranking.py` and `shared/canonical_url.py` — no model calls, no
embeddings, no external NLP libraries.

Known limitations (expected for a rule-based v1, not bugs):
  - Entity extraction is a capitalized-word heuristic. It will miss
    lowercase entity mentions ("tesla") and can occasionally pick up
    proper nouns that aren't really "entities" in the business-intent
    sense (e.g. a capitalized brand used as an adjective). It explicitly
    guards against the most common failure mode of this class of
    heuristic — treating a capitalized sentence-initial word ("How ...",
    "What ...") as an entity — via a stopword list checked regardless of
    position.
  - Topic extraction is just "remaining meaningful tokens after removing
    entities and stopwords" — there's no real noun-phrase parsing.
  - Language detection is NOT implemented. Real language detection needs
    either a model or a statistical n-gram library, both out of scope for
    a keyword/regex-only v1 per the no-AI constraint. `detect_language`
    always returns None; the field exists so the shape is stable if a
    real implementation lands later.
"""

import re
import string

from api.models.query_intelligence import QueryIntelligence

# Words excluded from entity-candidacy regardless of capitalization. This is
# what prevents sentence-initial capitalization ("How to bake bread") from
# being misread as an entity: we check `word.lower() in STOPWORDS`
# independent of position, so "How" is excluded the same way "how" would be.
STOPWORDS = {
    "how", "what", "why", "when", "where", "who", "which", "whose",
    "is", "are", "was", "were", "do", "does", "did", "can", "could",
    "should", "would", "will", "the", "a", "an", "this", "that", "these",
    "those", "latest", "recent", "today", "breaking", "news", "define",
    "definition", "explain", "about", "for", "of", "in", "on", "at", "to",
    "and", "or", "history", "historical", "current", "currently", "now",
    "i", "you", "we", "they", "it", "he", "she", "please", "tell", "me",
    "give", "show", "find", "get", "with", "vs", "versus",
}

FINANCE_KEYWORDS = {
    "stock", "shares", "earnings", "ticker", "nasdaq", "nyse",
    "sec filing", "ipo", "dividend", "market cap", "valuation",
    "stock price", "quarterly results", "shareholder", "stock market",
}

RECENT_KEYWORDS = {
    "latest", "recent", "today", "this week", "breaking", "currently",
    "right now", "just announced",
}

HOW_TO_PREFIXES = re.compile(r"^(how to|how do i|how does|how can i|how can we)\b")
DEFINITION_PREFIXES = re.compile(r"^(what is|what are|what's|define|definition of|who is|who was)\b")
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

_PUNCT = string.punctuation


def _clean_word(word: str) -> str:
    return word.strip(_PUNCT)


def extract_entities(query: str) -> list[str]:
    """Capitalized-word heuristic. See module docstring for limitations."""
    raw_words = query.split()
    candidates: list[str | None] = []
    for w in raw_words:
        clean = _clean_word(w)
        if not clean:
            candidates.append(None)
            continue
        is_capitalized = clean[0].isupper() or clean.isupper()
        if len(clean) > 1 and is_capitalized and clean.lower() not in STOPWORDS:
            candidates.append(clean)
        else:
            candidates.append(None)

    # merge runs of consecutive capitalized words into a single entity
    # (e.g. a two-word proper noun), dedupe case-insensitively, keep order
    entities: list[str] = []
    seen: set[str] = set()
    current: list[str] = []

    def _flush():
        if current:
            phrase = " ".join(current)
            if phrase.lower() not in seen:
                seen.add(phrase.lower())
                entities.append(phrase)
            current.clear()

    for c in candidates:
        if c is not None:
            current.append(c)
        else:
            _flush()
    _flush()

    return entities


def extract_topics(query: str, entities: list[str]) -> list[str]:
    entity_words = {w.lower() for e in entities for w in e.split()}
    topics: list[str] = []
    for w in query.split():
        clean = _clean_word(w).lower()
        if not clean or clean in entity_words or clean in STOPWORDS:
            continue
        if clean not in topics:
            topics.append(clean)
    return topics


def detect_finance(query_lower: str) -> bool:
    return any(kw in query_lower for kw in FINANCE_KEYWORDS)


def detect_time_range(query_lower: str) -> str | None:
    if any(kw in query_lower for kw in RECENT_KEYWORDS):
        return "recent"
    if YEAR_RE.search(query_lower) or "history of" in query_lower:
        return "historical"
    return None


def detect_language(query: str) -> str | None:
    """Not implemented: real language detection is out of scope for a
    keyword/regex-only v1 (see module docstring). Always returns None."""
    return None


def classify_intent(query_lower: str, entities: list[str], is_finance: bool) -> str:
    if HOW_TO_PREFIXES.match(query_lower):
        return "how_to"
    if DEFINITION_PREFIXES.match(query_lower):
        return "definition"
    if is_finance:
        return "finance"
    if entities and any(kw in query_lower for kw in RECENT_KEYWORDS | {"news"}):
        return "company_news"
    return "general"


def _dedupe_cap(items: list[str], cap: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        item = re.sub(r"\s+", " ", item).strip()
        if item and item.lower() not in seen:
            seen.add(item.lower())
            result.append(item)
        if len(result) >= cap:
            break
    return result


def expand_queries(
    query: str, intent: str, entities: list[str], topics: list[str]
) -> list[str]:
    """Rule-based query expansion: 2-4 variants combining the original query
    with detected entities/topics and intent-specific modifiers. Same style
    as the hardcoded `f"{q} news"` / `f"{q} latest"` expansion already used
    by `/v1/search?expand=true` (api/providers/searxng.py), just driven by
    the detected intent/entities instead of two fixed suffixes."""
    entity_str = " ".join(entities)
    topic_str = " ".join(topics[:2])

    variants = [query]
    if intent == "finance":
        base = entity_str or query
        variants += [f"{base} earnings", f"{base} SEC filing", f"{base} stock price"]
    elif intent == "company_news":
        base = f"{entity_str} {topic_str}".strip() or query
        variants += [f"{base} production news", f"{base} technology Reuters", f"{base} SEC filing"]
    elif intent == "how_to":
        variants += [f"{query} step by step", f"{query} guide"]
    elif intent == "definition":
        base = entity_str or topic_str or query
        variants += [f"{base} explained", f"{base} overview"]
    else:
        variants += [f"{query} guide", f"{query} overview"]

    return _dedupe_cap(variants, 4)


def analyze_query(query: str) -> QueryIntelligence:
    query = query.strip()
    query_lower = query.lower()

    entities = extract_entities(query)
    topics = extract_topics(query, entities)
    is_finance = detect_finance(query_lower)
    time_range = detect_time_range(query_lower)
    intent = classify_intent(query_lower, entities, is_finance)
    queries = expand_queries(query, intent, entities, topics)

    return QueryIntelligence(
        intent=intent,
        entities=entities,
        topics=topics,
        time_range=time_range,
        queries=queries,
    )
