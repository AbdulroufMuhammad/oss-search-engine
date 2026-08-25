import math
from datetime import datetime, timedelta, timezone

from shared.ranking import (
    FRESHNESS_DECAY_DAYS,
    content_fingerprint,
    content_quality_score,
    domain_of,
    final_score,
    freshness_score,
    keyword_relevance,
)


def test_keyword_relevance_full_title_match():
    score = keyword_relevance("python testing", "python testing guide", "irrelevant content")
    assert score > 0.5


def test_keyword_relevance_no_overlap_is_zero():
    assert keyword_relevance("python testing", "cooking recipes", "how to bake bread") == 0.0


def test_keyword_relevance_empty_query_is_zero():
    assert keyword_relevance("", "some title", "some content") == 0.0


def test_keyword_relevance_bounded_at_one():
    score = keyword_relevance("python", "python python python", "python python python")
    assert score <= 1.0


def test_freshness_score_unknown_date_is_neutral():
    assert freshness_score(None) == 0.5
    assert freshness_score("") == 0.5


def test_freshness_score_unparseable_date_is_neutral():
    assert freshness_score("not-a-date") == 0.5


def test_freshness_score_now_is_near_one():
    now = datetime.now(timezone.utc).isoformat()
    assert freshness_score(now) > 0.99


def test_freshness_score_decay_matches_exp_formula_at_decay_constant():
    # exp(-age/N) gives exp(-1) ~= 0.368 at age == N (1/e, "time constant"),
    # not 0.5 (that would be a true half-life, which needs a ln(2) factor).
    decay_days_ago = (datetime.now(timezone.utc) - timedelta(days=FRESHNESS_DECAY_DAYS)).isoformat()
    score = freshness_score(decay_days_ago)
    assert math.isclose(score, math.exp(-1), abs_tol=0.01)


def test_freshness_score_decreases_with_age():
    recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    assert freshness_score(recent) > freshness_score(old)


def test_content_quality_score_empty_is_zero():
    assert content_quality_score("", "") == 0.0


def test_content_quality_score_title_only_nonzero():
    assert content_quality_score("A Title", "") > 0.0


def test_content_quality_score_long_content_scores_higher_than_short():
    short = content_quality_score("Title", "short")
    long = content_quality_score("Title", "x" * 300)
    assert long > short


def test_domain_of_strips_www():
    assert domain_of("https://www.example.com/path") == "example.com"


def test_domain_of_keeps_subdomain():
    assert domain_of("https://en.wikipedia.org/wiki/Cat") == "en.wikipedia.org"


def test_content_fingerprint_same_content_same_fingerprint():
    a = content_fingerprint("Hello World, this is a test.")
    b = content_fingerprint("hello world, this is a test.")
    assert a == b, "fingerprint should be case-insensitive"


def test_content_fingerprint_ignores_whitespace_differences():
    a = content_fingerprint("Hello   World this is   a test")
    b = content_fingerprint("Hello World this is a test")
    assert a == b


def test_content_fingerprint_different_content_different_fingerprint():
    a = content_fingerprint("This is the first article about cats.")
    b = content_fingerprint("This is a completely different article about dogs.")
    assert a != b


def test_final_score_weights_sum_to_full_score_with_no_penalty():
    score = final_score(relevance=1.0, authority=1.0, freshness=1.0, content_quality=1.0, duplicate_penalty=0.0)
    assert score == 1.0


def test_final_score_zero_inputs_is_zero():
    score = final_score(relevance=0.0, authority=0.0, freshness=0.0, content_quality=0.0, duplicate_penalty=0.0)
    assert score == 0.0


def test_final_score_duplicate_penalty_multiplies_down():
    base = final_score(relevance=1.0, authority=1.0, freshness=1.0, content_quality=1.0, duplicate_penalty=0.0)
    penalized = final_score(relevance=1.0, authority=1.0, freshness=1.0, content_quality=1.0, duplicate_penalty=0.5)
    assert penalized == round(base * 0.5, 4)
