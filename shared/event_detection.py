"""System 9: Event Detection -- deterministic, keyword-pattern classification
of news/filing text into structured market events (no AI/NLP model).

Same spirit as shared/query_intelligence.py's intent classification: a small
set of keyword/regex patterns checked in priority order. Honest about its
limits -- if nothing matches, `detect_event()` returns None rather than
forcing every piece of text into a category.
"""

import re

from api.models.event import Event

# checked in order; first match wins. Order matters: more specific event
# types are checked before generic ones (e.g. "earnings" before "regulation").
EVENT_PATTERNS: list[tuple[str, re.Pattern]] = [
    (
        "earnings_release",
        re.compile(
            r"\b(earnings (report|release|call|beat|miss)|quarterly (results|revenue)|"
            r"q[1-4] (results|earnings)|reports? (record )?(revenue|profit|earnings))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "acquisition",
        re.compile(
            r"\b(acqui(res?|sition|ring)|to (buy|acquire)|merger|merges? with|"
            r"take(s|over)|buyout)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "layoffs",
        re.compile(r"\b(lay(s)?[ -]?off(s)?|job cuts?|workforce reduction|cuts? \d+%? of (its )?(staff|jobs))\b", re.IGNORECASE),
    ),
    (
        "lawsuit",
        re.compile(r"\b(law ?suit|sues?|sued|litigation|court (ruling|case)|files? suit)\b", re.IGNORECASE),
    ),
    (
        "regulation",
        re.compile(
            r"\b(regulat(ion|or|ory)|antitrust|sec\b[\w\s]{0,30}\b(probe|investigation|charges)|"
            r"ftc|export (control|ban|restriction)|sanction)\b",
            re.IGNORECASE,
        ),
    ),
    (
        # bare "launch(es)" is deliberately excluded: it's too generic (an
        # investigation, a lawsuit, an attack can all be "launched") and was
        # a real false-positive source -- require an actual product noun.
        "product_launch",
        re.compile(
            r"\b(unveils?|debuts?|introduces? (its |a |new )?(product|device|phone|app|service|feature|model)|"
            r"launches? (its |a |new )?(product|device|phone|app|service|feature|model|chip|smartphone|"
            r"smartwatch|vehicle|platform))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "central_bank_decision",
        re.compile(r"\b(federal reserve|fed (rate|decision|cuts?|hikes?)|interest rate (cut|hike|decision)|ecb|central bank)\b", re.IGNORECASE),
    ),
    (
        "macro_release",
        re.compile(r"\b(gdp|inflation|cpi|jobs report|unemployment rate|nonfarm payrolls|consumer confidence)\b", re.IGNORECASE),
    ),
    (
        "geopolitical",
        re.compile(r"\b(tariff|trade war|export ban|geopolitical|sanctions? on|conflict in)\b", re.IGNORECASE),
    ),
]

_POSITIVE_WORDS = {
    "surge", "surges", "soar", "soars", "beat", "beats", "record", "growth", "gain", "gains",
    "profit", "profits", "rally", "rallies", "upgrade", "upgraded", "strong", "boost", "boosts",
    "outperform", "positive", "win", "wins", "success", "successful", "rise", "rises", "jump", "jumps",
}
_NEGATIVE_WORDS = {
    "plunge", "plunges", "miss", "misses", "loss", "losses", "decline", "declines", "cut", "cuts",
    "downgrade", "downgraded", "weak", "warning", "lawsuit", "sued", "fraud", "crash", "crashes",
    "layoff", "layoffs", "recall", "fall", "falls", "drop", "drops", "concern", "concerns", "fail", "fails",
}

_SECTOR_KEYWORDS: dict[str, list[str]] = {
    "Semiconductors": ["chip", "semiconductor", "gpu", "cpu", "wafer", "foundry"],
    "Technology": ["software", "cloud", "ai", "artificial intelligence", "app", "platform", "saas"],
    "Financials": ["bank", "banking", "insurer", "insurance", "lender", "financial services"],
    "Energy": ["oil", "gas", "energy", "crude", "opec", "renewable", "solar", "wind power"],
    "Healthcare": ["drug", "pharma", "pharmaceutical", "biotech", "fda", "clinical trial", "vaccine"],
    "Automotive": ["ev", "evs", "electric vehicle", "automaker", "car maker", "vehicle production"],
    "Retail": ["retailer", "e-commerce", "consumer spending", "store sales"],
}
# word-boundary regexes, compiled once -- a naive substring check would let
# short keywords like "ev" false-match inside unrelated words (e.g. "revenue")
_SECTOR_PATTERNS: dict[str, list[re.Pattern]] = {
    sector: [re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE) for kw in keywords]
    for sector, keywords in _SECTOR_KEYWORDS.items()
}

_MAGNITUDE_WORDS = {"record", "unprecedented", "billion", "massive", "historic", "major", "significant"}

EVENT_TYPE_BASE_IMPORTANCE = {
    "regulation": 0.7,
    "acquisition": 0.7,
    "central_bank_decision": 0.65,
    "macro_release": 0.6,
    "geopolitical": 0.6,
    "earnings_release": 0.55,
    "lawsuit": 0.5,
    "layoffs": 0.5,
    "product_launch": 0.4,
}


def detect_event_type(text: str) -> str | None:
    for event_type, pattern in EVENT_PATTERNS:
        if pattern.search(text):
            return event_type
    return None


def detect_sentiment(text: str) -> str:
    """Lexicon-based (word-count) sentiment -- has no notion of context, so
    e.g. "Fed cuts rates" scores negative (via "cuts") even though a rate
    cut is often market-positive. A known, accepted limitation of word-level
    sentiment without real NLP; not attempting to special-case it here."""
    words = re.findall(r"[a-z]+", text.lower())
    pos = sum(1 for w in words if w in _POSITIVE_WORDS)
    neg = sum(1 for w in words if w in _NEGATIVE_WORDS)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


def detect_market_sector(text: str) -> str | None:
    best_sector, best_hits = None, 0
    for sector, patterns in _SECTOR_PATTERNS.items():
        hits = sum(1 for p in patterns if p.search(text))
        if hits > best_hits:
            best_sector, best_hits = sector, hits
    return best_sector


def compute_importance(text: str, event_type: str, authority_score: float) -> float:
    base = EVENT_TYPE_BASE_IMPORTANCE.get(event_type, 0.5)
    words = set(re.findall(r"[a-z]+", text.lower()))
    magnitude_bonus = 0.1 if words & _MAGNITUDE_WORDS else 0.0
    score = 0.5 * base + 0.3 * authority_score + 0.2 * (base + magnitude_bonus)
    return round(min(1.0, score), 4)


def detect_event(
    title: str,
    content: str,
    *,
    entity: str | None = None,
    authority_score: float = 0.5,
    published_at: str | None = None,
    source_url: str | None = None,
) -> Event | None:
    text = f"{title} {content}"
    event_type = detect_event_type(text)
    if event_type is None:
        return None

    return Event(
        event_type=event_type,
        entity=entity,
        sentiment=detect_sentiment(text),
        importance=compute_importance(text, event_type, authority_score),
        market_sector=detect_market_sector(text),
        time_detected=published_at,
        source_url=source_url,
        source_title=title or None,
    )
