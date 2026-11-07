"""Tests for /health and /analyse endpoints."""
from __future__ import annotations
import json
from pathlib import Path

import jsonschema
import pytest
from httpx import ASGITransport, AsyncClient

from server.main import app

SCHEMA_DIR = Path(__file__).parent.parent.parent.parent / "contracts"
STREAM_EVENT_SCHEMA = json.loads((SCHEMA_DIR / "stream-event.schema.json").read_text())
RESPONSE_SCHEMA = json.loads((SCHEMA_DIR / "response.schema.json").read_text())

_BASE_REQUEST = {
    "item": {"name": "Netflix Standard", "brand": "Netflix", "url": "https://www.netflix.com/gb/signup", "id": None, "seller": None, "price": 4.99},
    "purchase_type_signals": ["subscription"],
    "links": [],
    "page_text_snippets": [],
    "price_drift": {"first_seen": None, "current": 4.99},
    "install_id": "test-install-abc123",
}


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_health(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


async def test_analyse_no_install_id(client: AsyncClient) -> None:
    bad = {**_BASE_REQUEST, "install_id": ""}
    resp = await client.post("/analyse", json=bad)
    assert resp.status_code == 422


async def test_analyse_streams_events_in_order(client: AsyncClient) -> None:
    expected_order = ["item", "price_drift", "cost", "lock_in", "small_print", "company"]
    received_cards: list[str] = []
    got_done = False

    async with client.stream("POST", "/analyse", json=_BASE_REQUEST) as resp:
        assert resp.status_code == 200
        event_name: str | None = None
        async for line in resp.aiter_lines():
            line = line.strip()
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_str = line.split(":", 1)[1].strip()
                data = json.loads(data_str)
                if event_name == "card":
                    # Validate against stream-event schema
                    jsonschema.validate(data, STREAM_EVENT_SCHEMA)
                    received_cards.append(data["card"])
                elif event_name == "done":
                    got_done = True

    assert received_cards == expected_order, f"Card order wrong: {received_cards}"
    assert got_done, "No 'done' event received"


async def test_all_card_events_valid_schema(client: AsyncClient) -> None:
    """Every 'card' event data must pass stream-event schema validation."""
    validator = jsonschema.Draft202012Validator(STREAM_EVENT_SCHEMA)

    async with client.stream("POST", "/analyse", json=_BASE_REQUEST) as resp:
        event_name: str | None = None
        async for line in resp.aiter_lines():
            line = line.strip()
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and event_name == "card":
                data = json.loads(line.split(":", 1)[1].strip())
                errors = list(validator.iter_errors(data))
                assert not errors, f"Schema errors on card '{data.get('card')}': {errors[0].message}"


async def test_rate_limit(client: AsyncClient) -> None:
    """After 60 requests the 61st should be rate-limited."""
    # Use a fresh install_id so this test is isolated
    req = {**_BASE_REQUEST, "install_id": "rate-limit-test-install"}
    # Drain most responses quickly (don't collect body, just fire)
    for _ in range(60):
        async with client.stream("POST", "/analyse", json=req) as resp:
            assert resp.status_code == 200

    resp_61 = await client.post("/analyse", json=req)
    assert resp_61.status_code == 429
