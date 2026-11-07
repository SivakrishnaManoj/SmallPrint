"""Tests for the quote verifier (S1, #7).

Quote or null: an LLM-derived value is kept only when its quote appears
verbatim in the source text. Only whitespace and typographic quotes are
normalised. Anything else fails.
"""
from __future__ import annotations

import pytest

from smallprint.verify import normalise, verify_field, verify_quote

SOURCE = (
    "Your membership will automatically renew at the end of the minimum term.\n"
    "You must give us  30 days’ notice to cancel.  An early termination fee of "
    "£45 applies if you cancel within the first 12 months.\n"
    "We’ll refund you within 14 days of receiving the “returned item”."
)


# --- exact match ---------------------------------------------------------

def test_exact_match_passes():
    assert verify_quote("automatically renew at the end of the minimum term", SOURCE)


def test_quote_equal_to_whole_source_passes():
    assert verify_quote("Cancel any time.", "Cancel any time.")


# --- whitespace differences ----------------------------------------------

def test_collapsed_whitespace_passes():
    # source has a double space between "us" and "30"
    assert verify_quote("You must give us 30 days’ notice", SOURCE)


def test_quote_spanning_a_line_break_passes():
    assert verify_quote("first 12 months. We’ll refund you", SOURCE)


def test_non_breaking_space_passes():
    assert verify_quote("An early termination fee of £45", "An early termination fee of £45")


def test_leading_and_trailing_whitespace_in_quote_passes():
    assert verify_quote("  minimum term.\n", SOURCE)


# --- typographic quote differences ---------------------------------------

def test_straight_apostrophe_matches_curly_in_source():
    assert verify_quote("You must give us 30 days' notice to cancel", SOURCE)


def test_curly_apostrophe_matches_straight_in_source():
    assert verify_quote("We’ll refund you", "We'll refund you within 14 days")


def test_straight_double_quotes_match_curly_in_source():
    assert verify_quote('receiving the "returned item"', SOURCE)


def test_curly_double_quotes_match_straight_in_source():
    assert verify_quote("the “basic” plan", 'Upgrade from the "basic" plan')


# --- paraphrase fails ----------------------------------------------------

@pytest.mark.parametrize(
    "paraphrase",
    [
        "Your membership renews automatically at the end of the minimum term",  # reworded
        "You must give us thirty days’ notice to cancel",  # number spelled out
        "An early termination fee of £50 applies",  # wrong value
        "you must give us 30 days’ notice to cancel",  # case differs: not verbatim
        "automatically renew at the end of the minimum term!",  # extra punctuation
        "automatically  renew at the end of minimum term",  # dropped word
    ],
)
def test_paraphrase_fails(paraphrase):
    assert not verify_quote(paraphrase, SOURCE)


# --- missing quote fails -------------------------------------------------

@pytest.mark.parametrize("quote", [None, "", "   ", "\n\t"])
def test_missing_or_blank_quote_fails(quote):
    assert not verify_quote(quote, SOURCE)


@pytest.mark.parametrize("source", [None, "", "   "])
def test_missing_source_fails(source):
    assert not verify_quote("minimum term", source)


def test_quote_not_in_source_fails():
    assert not verify_quote("No contract, cancel any time", SOURCE)


# --- verify_field: value is kept only with a verified quote --------------

def test_field_with_verified_quote_is_kept_unchanged():
    field = {
        "field": "notice_period",
        "value": "30 days",
        "quote": "You must give us 30 days' notice to cancel",
        "url": "https://example.com/terms",
    }
    assert verify_field(field, SOURCE) == field


def test_field_with_paraphrased_quote_becomes_none():
    field = {"field": "notice_period", "value": "30 days", "quote": "30 days notice is required", "url": "https://example.com/terms"}
    assert verify_field(field, SOURCE) is None


def test_field_without_quote_becomes_none():
    assert verify_field({"field": "exit_fee", "value": "£45", "url": "https://example.com/terms"}, SOURCE) is None
    assert verify_field({"field": "exit_fee", "value": "£45", "quote": None}, SOURCE) is None


def test_null_field_stays_null():
    assert verify_field(None, SOURCE) is None


def test_field_with_null_value_stays_null_even_with_valid_quote():
    field = {"field": "exit_fee", "value": None, "quote": "minimum term"}
    assert verify_field(field, SOURCE) is None


def test_verify_field_does_not_mutate_input():
    field = {"field": "notice_period", "value": "30 days", "quote": "made up quote"}
    snapshot = dict(field)
    verify_field(field, SOURCE)
    assert field == snapshot


# --- normalise -----------------------------------------------------------

def test_normalise_only_touches_whitespace_and_quotes():
    assert normalise("  “Hi” ‘there’\n\nFoo-Bar  ") == "\"Hi\" 'there' Foo-Bar"


def test_normalise_keeps_case_and_other_punctuation():
    assert normalise("£45.00 – Fee!") == "£45.00 – Fee!"
