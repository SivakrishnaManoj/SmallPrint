"""S4 (#14): per-install daily spend limit and token caps."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import jsonschema
import pytest

from smallprint.extract import Document, analyse_documents
from smallprint.extract.tests.test_extractor import FIX, GYM_URL, FakeAnthropic, _llm
from smallprint.spend import (
    MAX_INPUT_TOKENS, MAX_OUTPUT_TOKENS, SpendLimitReached, SpendTracker, TokenCapExceeded, call_cost,
)

ROOT = Path(__file__).resolve().parents[2]
STREAM_EVENT_SCHEMA = json.loads((ROOT / "contracts" / "stream-event.schema.json").read_text(encoding="utf-8"))

A = "install-aaaa-1111"
B = "install-bbbb-2222"


def _reply(text: str, input_tokens: int = 7_000, output_tokens: int = 1_000) -> dict:
    return {
        "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
        "content": [{"type": "text", "text": text}], "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


def _long_doc() -> str:
    para = (FIX / "gym_terms.txt").read_text(encoding="utf-8")
    return "\n\n".join([para] * 300)  # ~15 chunks, so ~15 calls without a limit


# --- done when: the limit stops calls for one UUID and not for another ----

async def test_limit_stops_llm_calls_for_one_install_not_another():
    tracker = SpendTracker(daily_limit_usd=0.005)  # room for ~3 calls
    doc = [Document(GYM_URL, _long_doc())]

    fake_a = FakeAnthropic([_reply("{}")] * 50)
    cards_a = await analyse_documents(fake_a.client(), doc, A, tracker)
    calls_a = len(fake_a.requests)
    assert 0 < calls_a < 10, "A should be cut off after a few calls, not process every chunk"
    assert set(cards_a["card_states"].values()) == {"limit_reached"}

    # A again, same day: no LLM call at all.
    fake_a2 = FakeAnthropic([_reply("{}")] * 50)
    cards_a2 = await analyse_documents(fake_a2.client(), doc, A, tracker)
    assert fake_a2.requests == []
    assert set(cards_a2["card_states"].values()) == {"limit_reached"}

    # B is unaffected.
    fake_b = FakeAnthropic([_reply("{}")] * 50)
    await analyse_documents(fake_b.client(), doc, B, tracker)
    assert len(fake_b.requests) == calls_a
    assert tracker.spent(A) <= tracker.daily_limit_usd
    assert tracker.spent(B) <= tracker.daily_limit_usd


async def test_values_verified_before_the_limit_still_show():
    tracker = SpendTracker(daily_limit_usd=0.003)  # one call, then the limit
    source = (FIX / "gym_terms.txt").read_text(encoding="utf-8")
    docs = [Document(GYM_URL, source), Document("https://other.example/terms", source)]
    fake = FakeAnthropic([_reply(_llm("gym_llm.json"))] * 5)

    cards = await analyse_documents(fake.client(), docs, A, tracker)

    assert len(fake.requests) == 1
    assert cards["card_states"]["cost"] == "found"
    assert cards["card_states"]["lock_in"] == "found"


async def test_without_a_tracker_nothing_is_limited():
    fake = FakeAnthropic([_reply("{}")] * 50)
    cards = await analyse_documents(fake.client(), [Document(GYM_URL, _long_doc())])
    assert len(fake.requests) > 10
    assert "limit_reached" not in cards["card_states"].values()


# --- the tracker itself --------------------------------------------------

async def test_settles_to_actual_usage():
    tracker = SpendTracker(daily_limit_usd=1.0)
    async with tracker.guard(A, 5_000) as usage:
        usage.input_tokens, usage.output_tokens = 5_000, 300
    assert tracker.spent(A) == pytest.approx(call_cost(5_000, 300))


async def test_failed_call_keeps_the_full_reservation():
    tracker = SpendTracker(daily_limit_usd=1.0)
    with pytest.raises(RuntimeError):
        async with tracker.guard(A, 5_000):
            raise RuntimeError("network error after the request was sent")
    assert tracker.spent(A) == pytest.approx(call_cost(5_000, MAX_OUTPUT_TOKENS))


async def test_concurrent_calls_cannot_overshoot_the_limit():
    worst = call_cost(MAX_INPUT_TOKENS, MAX_OUTPUT_TOKENS)
    tracker = SpendTracker(daily_limit_usd=worst * 3.5)
    ran = 0

    async def one_call():
        nonlocal ran
        try:
            async with tracker.guard(A, MAX_INPUT_TOKENS):
                ran += 1
                await asyncio.sleep(0.01)  # usage never filled: worst case stays charged
        except SpendLimitReached:
            pass

    await asyncio.gather(*(one_call() for _ in range(10)))
    assert ran == 3
    assert tracker.spent(A) <= tracker.daily_limit_usd


async def test_input_over_the_token_cap_is_refused():
    tracker = SpendTracker(daily_limit_usd=1.0)
    with pytest.raises(TokenCapExceeded):
        async with tracker.guard(A, MAX_INPUT_TOKENS + 1):
            pass
    assert tracker.spent(A) == 0


async def test_output_is_capped_too():
    tracker = SpendTracker(daily_limit_usd=1.0)
    async with tracker.guard(A, 1_000, max_output_tokens=100_000):
        pass
    assert tracker.spent(A) == pytest.approx(call_cost(1_000, MAX_OUTPUT_TOKENS))


async def test_missing_install_id_is_refused():
    tracker = SpendTracker(daily_limit_usd=1.0)
    with pytest.raises(SpendLimitReached):
        async with tracker.guard("", 1_000):
            pass


async def test_limit_resets_the_next_day():
    day = ["2026-11-07"]
    tracker = SpendTracker(daily_limit_usd=call_cost(1_000, MAX_OUTPUT_TOKENS) * 1.5, today=lambda: day[0])
    async with tracker.guard(A, 1_000):
        pass
    with pytest.raises(SpendLimitReached):
        async with tracker.guard(A, 1_000):
            pass
    day[0] = "2026-11-08"
    async with tracker.guard(A, 1_000):
        pass
    assert tracker.spent(A) > 0


async def test_logs_spend_without_the_raw_install_id(caplog):
    tracker = SpendTracker(daily_limit_usd=1.0)
    with caplog.at_level(logging.INFO, logger="smallprint.spend"):
        async with tracker.guard(A, 1_000) as usage:
            usage.input_tokens, usage.output_tokens = 1_000, 50
    assert "total=$" in caplog.text
    assert A not in caplog.text


def test_limit_reached_is_a_valid_card_state():
    event = {"card": "cost", "state": "limit_reached", "payload": {"cost_streams": []}}
    jsonschema.validate(event, STREAM_EVENT_SCHEMA)
