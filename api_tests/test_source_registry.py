from shared.source_registry import authority_for_domain


def test_known_domain_exact_match():
    assert authority_for_domain("wikipedia.org") == 0.95
    assert authority_for_domain("reuters.com") == 0.95


def test_known_domain_case_insensitive():
    assert authority_for_domain("Wikipedia.ORG") == 0.95


def test_subdomain_inherits_parent_score():
    assert authority_for_domain("en.wikipedia.org") == 0.95


def test_deep_subdomain_inherits_parent_score():
    assert authority_for_domain("mobile.en.wikipedia.org") == 0.95


def test_unrelated_domain_containing_known_domain_as_substring_not_matched():
    assert authority_for_domain("notwikipedia.org") == 0.5
    assert authority_for_domain("wikipedia.org.evil.com") == 0.5


def test_unknown_domain_gets_default():
    assert authority_for_domain("some-random-blog.example") == 0.5


def test_gov_tld_heuristic():
    assert authority_for_domain("nasa.gov") == 0.9


def test_mil_tld_heuristic():
    assert authority_for_domain("army.mil") == 0.9


def test_edu_tld_heuristic():
    assert authority_for_domain("mit.edu") == 0.8


def test_known_domain_takes_precedence_over_gov_default():
    assert authority_for_domain("sec.gov") == 0.98
