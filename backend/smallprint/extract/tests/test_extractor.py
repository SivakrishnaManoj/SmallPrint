"""S3 (#13): extractor tests. The LLM is faked at the network boundary.

The real AsyncOpenAI client runs; only the HTTP transport is replaced,
returning recorded Messages API responses. Done when: every `found` value
has a verified quote and URL.
"""
from __future__ import annotations

import base64
import copy
import json
from pathlib import Path

import httpx2
import jsonschema
import pymupdf
import pytest
from openai import AsyncOpenAI

from smallprint.extract import Document, analyse_documents, build_cards, chunk_text, html_to_text, pdf_b64_to_text
from smallprint.extract.extractor import MAX_INPUT_TOKENS, MODEL, _number_in_quote, verify_extraction
from smallprint.extract.text import estimate_tokens
from smallprint.verify import verify_quote

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[4]
RESPONSE_SCHEMA = json.loads((ROOT / "contracts" / "response.schema.json").read_text(encoding="utf-8"))

GYM_URL = "https://fitbox.example/terms"
RETAIL_URL = "https://retail.example/returns"


def _message(text: str | None, finish_reason: str = "stop", refusal: str | None = None) -> dict:
    return {
        "id": "c", "object": "chat.completion", "created": 0, "model": MODEL,
        "choices": [{"index": 0, "finish_reason": finish_reason,
                     "message": {"role": "assistant", "content": text, "refusal": refusal}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


class FakeOpenAI:
    """Records each request body and replies with queued Chat Completions bodies."""

    def __init__(self, replies: list[dict]):
        self.replies = list(replies)
        self.requests: list[dict] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        return httpx2.Response(200, json=self.replies.pop(0))

    def client(self) -> AsyncOpenAI:
        transport = httpx2.MockTransport(self.handler)
        return AsyncOpenAI(api_key="test", max_retries=0, http_client=httpx2.AsyncClient(transport=transport))


def _llm(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _all_found_values_have_verified_quotes(cards: dict, sources: dict[str, str]) -> None:
    for stream in cards["cost_streams"]:
        ev = stream["evidence"]
        assert ev["url"] in sources, stream
        assert verify_quote(ev["quote"], sources[ev["url"]]), stream
    for row in cards["small_print"]:
        assert row["url"] in sources, row
        assert verify_quote(row["quote"], sources[row["url"]]), row
    lock_in = cards["lock_in"]
    evidenced = set()
    for ev in lock_in["evidence"]:
        assert ev["url"] in sources, ev
        assert verify_quote(ev["quote"], sources[ev["url"]]), ev
        evidenced.add(ev["field"])
    # Contract rule: every non-null lock-in field has an evidence entry.
    non_null = {k for k, v in lock_in.items() if k != "evidence" and v is not None}
    assert non_null == evidenced


def _validate_against_contract(cards: dict) -> None:
    full = json.loads((ROOT / "fixtures" / "netflix.json").read_text(encoding="utf-8"))
    full.update({k: cards[k] for k in ("cost_streams", "lock_in", "small_print")})
    full["card_states"].update(cards["card_states"])
    jsonschema.validate(full, RESPONSE_SCHEMA)


# --- recorded fixtures end to end ----------------------------------------

async def test_gym_terms_every_found_value_is_verified():
    source = (FIX / "gym_terms.txt").read_text(encoding="utf-8")
    fake = FakeOpenAI([_message(_llm("gym_llm.json"))])

    cards = await analyse_documents(fake.client(), [Document(GYM_URL, source)])

    _all_found_values_have_verified_quotes(cards, {GYM_URL: source})
    _validate_against_contract(cards)
    assert cards["card_states"] == {"cost": "found", "lock_in": "found", "small_print": "found"}

    streams = {s["label"]: s for s in cards["cost_streams"]}
    assert streams["Trial"]["amount"] == 9.99 and streams["Trial"]["to_month"] == 2
    assert streams["Monthly fee"]["amount"] == 29.99 and streams["Monthly fee"]["from_month"] == 3
    assert streams["Annual rise"]["amount"] == 2.0 and streams["Annual rise"]["month"] == 13
    # setup_fee said 25.0 but the quote says £20.00: dropped, not shown.
    assert "Setup fee" not in streams

    assert cards["lock_in"]["min_term_months"] == 12
    assert cards["lock_in"]["auto_renews"] is True
    # Straight apostrophe in the model's quote, curly in the source: still verified.
    assert cards["lock_in"]["cancel_method"] == "online in the app"
    # notice_days quote was a paraphrase: dropped.
    assert cards["lock_in"]["notice_days"] is None
    assert "notice_days" not in {e["field"] for e in cards["lock_in"]["evidence"]}
    # Lock-in quotes live in lock_in.evidence, not duplicated in small_print.
    assert {r["field"] for r in cards["small_print"]} == {"Seller"}


async def test_retail_html_page_via_trafilatura():
    html = (FIX / "retail_returns.html").read_text(encoding="utf-8")
    source = html_to_text(html)
    fake = FakeOpenAI([_message(_llm("retail_llm.json"))])

    cards = await analyse_documents(fake.client(), [Document(RETAIL_URL, source)])

    _all_found_values_have_verified_quotes(cards, {RETAIL_URL: source})
    _validate_against_contract(cards)
    fields = {r["field"]: r for r in cards["small_print"]}
    assert fields["Returns window"]["value"] == "30 days"
    assert fields["Seller"]["value"] == "Example Retail UK Ltd"
    assert "Warranty" not in fields  # paraphrased quote dropped
    assert cards["card_states"]["cost"] == "not_found"
    assert cards["card_states"]["lock_in"] == "not_found"
    # The text the model saw is the page's main text, not scripts or nav.
    sent = fake.requests[0]["messages"][1]["content"]
    assert "window.track" not in sent


async def test_two_documents_keep_their_own_urls():
    gym = (FIX / "gym_terms.txt").read_text(encoding="utf-8")
    retail = html_to_text((FIX / "retail_returns.html").read_text(encoding="utf-8"))
    fake = FakeOpenAI([_message(_llm("gym_llm.json")), _message(_llm("retail_llm.json"))])

    cards = await analyse_documents(fake.client(), [Document(GYM_URL, gym), Document(RETAIL_URL, retail)])

    _all_found_values_have_verified_quotes(cards, {GYM_URL: gym, RETAIL_URL: retail})
    rows = {r["field"]: r for r in cards["small_print"]}
    assert rows["Returns window"]["url"] == RETAIL_URL
    assert rows["Seller"]["url"] == GYM_URL  # first verified value wins


# --- request shape -------------------------------------------------------

async def test_request_uses_constrained_json_and_quote_rule():
    source = (FIX / "gym_terms.txt").read_text(encoding="utf-8")
    fake = FakeOpenAI([_message(_llm("gym_llm.json"))])
    await analyse_documents(fake.client(), [Document(GYM_URL, source)])

    body = fake.requests[0]
    assert body["model"] == "gpt-4o-mini"
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    assert set(fmt["json_schema"]["schema"]["required"]) >= {"monthly_price", "min_term_months", "returns_window"}
    assert "return null" in body["messages"][0]["content"]
    assert "character for character" in body["messages"][0]["content"]
    assert '{"value": null, "quote": null}' in body["messages"][0]["content"]  # worked example has a null field


async def test_long_document_is_chunked_under_the_input_cap():
    para = (FIX / "gym_terms.txt").read_text(encoding="utf-8")
    source = "\n\n".join([para] * 40)  # ~40k chars, several chunks
    n_chunks = len(chunk_text(source, 6_000))
    empty = json.dumps({})
    fake = FakeOpenAI([_message(empty)] * 20)

    await analyse_documents(fake.client(), [Document(GYM_URL, source)])

    assert len(fake.requests) >= n_chunks >= 2
    for body in fake.requests:
        total = estimate_tokens(body["messages"][0]["content"]) + estimate_tokens(json.dumps(body["response_format"])) \
            + estimate_tokens(body["messages"][1]["content"])
        assert total <= MAX_INPUT_TOKENS


# --- failure modes -------------------------------------------------------

@pytest.mark.parametrize("reply", [
    _message(None, refusal="I cannot help with that."),
    _message('{"monthly_price": {"value": 29.99, "quote": "costs £29.99"', finish_reason="length"),
    _message("not json"),
])
async def test_bad_llm_reply_gives_not_found_not_a_crash(reply):
    source = (FIX / "gym_terms.txt").read_text(encoding="utf-8")
    fake = FakeOpenAI([reply])
    cards = await analyse_documents(fake.client(), [Document(GYM_URL, source)])
    assert cards["cost_streams"] == [] and cards["small_print"] == []
    assert set(cards["card_states"].values()) == {"not_found"}


async def test_no_documents_gives_not_found():
    cards = await analyse_documents(FakeOpenAI([]).client(), [])
    assert set(cards["card_states"].values()) == {"not_found"}


# --- verification rules --------------------------------------------------

SRC = "Your membership costs £1,029.99 per month. The minimum term is 12 months. It renews automatically."


@pytest.mark.parametrize("name,item,kept", [
    ("monthly_price", {"value": 1029.99, "quote": "costs £1,029.99 per month"}, True),
    ("monthly_price", {"value": 29.99, "quote": "costs £1,029.99 per month"}, False),  # substring of a bigger number
    ("min_term_months", {"value": 12, "quote": "The minimum term is 12 months."}, True),
    ("min_term_months", {"value": 12.5, "quote": "The minimum term is 12 months."}, False),  # integer field
    ("min_term_months", {"value": "12", "quote": "The minimum term is 12 months."}, False),  # wrong type
    ("auto_renews", {"value": True, "quote": "It renews automatically."}, True),
    ("auto_renews", {"value": "yes", "quote": "It renews automatically."}, False),
    ("auto_renews", {"value": True, "quote": None}, False),
    ("exit_fee", {"value": "", "quote": "It renews automatically."}, False),
    ("exit_fee", {"value": None, "quote": None}, False),
])
def test_verify_extraction_rules(name, item, kept):
    assert (name in verify_extraction({name: item}, SRC)) is kept


# Amazon product page lines from the 40-URL run on 2026-11-08 (verbatim quotes, wrong meaning).
AMAZON_SRC = (
    "Free returns are available for the shipping address you chose. "
    "For a full refund with no deduction for return shipping, you can return the item for any reason "
    "in new and unused condition. Credit broker: Amazon EU S.A.R.L. "
    "You can return this item within 30 days of receipt. Sold by Example Retail UK Ltd. "
    "This website is owned and maintained by Amazon Europe Core SARL."
)


@pytest.mark.parametrize("name,item,kept", [
    ("returns_window", {"value": "30 days", "quote": "You can return this item within 30 days of receipt."}, True),
    ("returns_window", {"value": "within 30 days of receipt", "quote": "You can return this item within 30 days of receipt."}, True),
    ("returns_window", {"value": "for free", "quote": "Free returns are available for the shipping address you chose."}, False),
    ("returns_window", {"value": "in new and unused condition",
                        "quote": "you can return the item for any reason in new and unused condition."}, False),
    ("returns_window", {"value": "for a full refund with no deduction for return shipping",
                        "quote": "For a full refund with no deduction for return shipping, you can return the item for any reason in new and unused condition."}, False),
    ("returns_window", {"value": "14 days", "quote": "You can return this item within 30 days of receipt."}, False),  # number not in quote
    ("seller", {"value": "Amazon EU S.A.R.L.", "quote": "Credit broker: Amazon EU S.A.R.L."}, False),
    # The site owner from the footer, not who sells the item (both Amazon demo pages, harness 2026-11-08).
    ("seller", {"value": "Amazon Europe Core SARL", "quote": "This website is owned and maintained by Amazon Europe Core SARL."}, False),
    ("seller", {"value": "Example Retail UK Ltd", "quote": "Sold by Example Retail UK Ltd."}, True),
    ("seller", {"value": "example retail uk ltd", "quote": "Sold by Example Retail UK Ltd."}, True),
    ("seller", {"value": "Spotify Ltd", "quote": "Sold by Example Retail UK Ltd."}, False),  # name not in the quote
])
def test_returns_window_and_seller_rules(name, item, kept):
    assert (name in verify_extraction({name: item}, AMAZON_SRC)) is kept


def test_number_in_quote():
    assert _number_in_quote(29.99, "£29.99 a month")
    assert _number_in_quote(30, "30 days' notice")
    assert _number_in_quote(20.0, "a fee of £20.00")
    assert not _number_in_quote(30, "one month's notice")
    assert not _number_in_quote(9.99, "£19.99")
    # A price cut short shares its digits with the real one: 24 is not £24.99.
    assert not _number_in_quote(24, "costs £24.99 a month")
    assert not _number_in_quote(5, "£5.99 per month")
    assert _number_in_quote(5, "a fee of £5. Cancel any time.")


def test_a_trial_without_its_full_price_gives_no_cost_total():
    """A trial stream on its own makes the panel total the trial price over the whole horizon
    (£0 for a free trial): a wrong number with a verified quote. No full price, no total."""
    quote = "Free for the first 3 months."
    found = {
        "trial_price": {"value": 0, "quote": quote, "url": GYM_URL, "source": None},
        "trial_months": {"value": 3, "quote": quote, "url": GYM_URL, "source": None},
    }
    out = build_cards(found)
    assert out["cost_streams"] == []
    assert out["card_states"]["cost"] == "not_found"


# --- text handling -------------------------------------------------------

def test_pdf_bytes_via_pymupdf():
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Your membership has a minimum term of 12 months.")
    pdf_b64 = base64.b64encode(doc.tobytes()).decode()
    text = pdf_b64_to_text(pdf_b64)
    assert verify_quote("Your membership has a minimum term of 12 months.", text)


def test_chunks_are_exact_substrings_and_cover_the_text():
    text = "\n\n".join(f"Clause {i}. " + "word " * 300 for i in range(60))
    chunks = chunk_text(text, 1_000)
    assert len(chunks) > 1
    assert "".join(chunks) == text
    assert all(len(c) <= 1_000 * 4 for c in chunks)


def test_fixture_llm_output_is_not_mutated():
    raw = json.loads(_llm("gym_llm.json"))
    snapshot = copy.deepcopy(raw)
    verify_extraction(raw, (FIX / "gym_terms.txt").read_text(encoding="utf-8"))
    assert raw == snapshot
