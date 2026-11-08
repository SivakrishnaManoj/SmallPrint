"""S7 (#16): the T&C cache itself."""
from __future__ import annotations

from smallprint.tc_cache import TermsCache

FIELDS = {"min_term_months": {"value": 12, "quote": "minimum term of 12 months", "url": "https://a.example/t", "source": None}}


def test_doc_hit_needs_the_same_url_text_and_source():
    c = TermsCache()
    c.put_doc("https://a.example/t", "terms text", None, FIELDS)
    assert c.get_doc("https://a.example/t", "terms text", None) == FIELDS
    assert c.get_doc("https://a.example/t", "terms text changed", None) is None
    assert c.get_doc("https://a.example/other", "terms text", None) is None
    assert c.get_doc("https://a.example/t", "terms text", "tavily_search") is None


def test_entries_expire():
    now = [1000.0]
    c = TermsCache(ttl_s=60, clock=lambda: now[0])
    c.put_doc("u", "t", None, FIELDS)
    c.put_site("a.example", FIELDS)
    now[0] += 61
    assert c.get_doc("u", "t", None) is None
    assert c.get_site("a.example") is None
    assert not c.has_doc("u", "t", None)


def test_an_empty_result_is_never_cached_for_a_site():
    c = TermsCache()
    c.put_site("a.example", {})
    assert c.get_site("a.example") is None


def test_callers_cannot_change_what_is_cached():
    c = TermsCache()
    c.put_site("a.example", FIELDS)
    got = c.get_site("a.example")
    got["min_term_months"]["value"] = 99
    assert c.get_site("a.example")["min_term_months"]["value"] == 12


def test_hit_and_miss_counts():
    c = TermsCache()
    c.get_site("a.example")
    c.put_site("a.example", FIELDS)
    c.get_site("a.example")
    assert (c.hits, c.misses) == (1, 1)
