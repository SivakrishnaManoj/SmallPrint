"""Contract tests: the schemas, the mock fixtures, and the quote-or-null rules.

These check what a consumer of the contract would see, not how the server is built.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import jsonschema
import pytest
from httpx import ASGITransport, AsyncClient

from server.main import app

ROOT = Path(__file__).parent.parent.parent.parent
CONTRACTS = ROOT / "contracts"
FIXTURES = ROOT / "fixtures"

RESPONSE_SCHEMA = json.loads((CONTRACTS / "response.schema.json").read_text())
REQUEST_SCHEMA = json.loads((CONTRACTS / "request.schema.json").read_text())
RESPONSE = jsonschema.Draft202012Validator(RESPONSE_SCHEMA)
REQUEST = jsonschema.Draft202012Validator(REQUEST_SCHEMA)

FIXTURE_NAMES = sorted(p.stem for p in FIXTURES.glob("*.json"))
REQUEST_FIXTURES = sorted((FIXTURES / "requests").glob("*.json"))

LOCK_IN_FIELDS = [
    "min_term_months",
    "exit_fee",
    "notice_days",
    "auto_renews",
    "cancel_method",
    "proprietary_refills",
]
VERDICT_WORDS = re.compile(
    r"\b(unethical|illegal|criminal|corrupt|scam|fraud\w*|shady|broke the law)\b", re.I
)


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from strings(v)


def present(value) -> bool:
    return isinstance(value, str) and value.strip() != ""


# --------------------------------------------------------------------------- fixtures


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixture_matches_response_schema(name: str) -> None:
    errors = [e.message for e in RESPONSE.iter_errors(load(name))]
    assert not errors, errors


@pytest.mark.parametrize("path", REQUEST_FIXTURES, ids=lambda p: p.stem)
def test_request_fixture_matches_request_schema(path: Path) -> None:
    errors = [e.message for e in REQUEST.iter_errors(json.loads(path.read_text()))]
    assert not errors, errors


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_found_cost_streams_carry_quote_and_url(name: str) -> None:
    d = load(name)
    if d["card_states"]["cost"] != "found":
        return
    for stream in d["cost_streams"]:
        ev = stream["evidence"]
        assert present(ev.get("quote")), f"{stream['label']}: no quote"
        assert present(ev.get("url")), f"{stream['label']}: no url"


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_usage_streams_are_ranges(name: str) -> None:
    for stream in load(name)["cost_streams"]:
        if stream["type"] != "usage":
            continue
        rng = stream.get("units_per_month", {})
        assert {"low", "mid", "high"} <= set(rng), f"{stream['label']}: usage needs low/mid/high"
        assert rng["low"] <= rng["mid"] <= rng["high"]
        assert present(stream["evidence"].get("url")), f"{stream['label']}: usage needs a source"


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_found_lock_in_values_each_have_evidence(name: str) -> None:
    d = load(name)
    if d["card_states"]["lock_in"] != "found":
        return
    evidence = {e["field"]: e for e in d["lock_in"].get("evidence", [])}
    for field in LOCK_IN_FIELDS:
        if d["lock_in"].get(field) is None:
            continue
        assert field in evidence, f"lock_in.{field} has a value but no evidence"
        assert present(evidence[field]["quote"]), f"lock_in.{field}: no quote"
        assert present(evidence[field]["url"]), f"lock_in.{field}: no url"


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_not_found_lock_in_is_empty(name: str) -> None:
    d = load(name)
    if d["card_states"]["lock_in"] not in ("not_found", "n_a"):
        return
    assert all(d["lock_in"].get(f) is None for f in LOCK_IN_FIELDS)
    assert d["lock_in"].get("evidence", []) == []


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_small_print_values_carry_quote_and_url(name: str) -> None:
    for item in load(name)["small_print"]:
        if item.get("value") is None:
            continue
        assert present(item.get("quote")), f"{item['field']}: no quote"
        assert present(item.get("url")), f"{item['field']}: no url"


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_company_records_carry_a_source(name: str) -> None:
    for rec in load(name)["company"].get("records", []):
        assert present(rec["source_url"]) and present(rec["date"])


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_no_verdict_words(name: str) -> None:
    hits = [s for s in strings(load(name)) if VERDICT_WORDS.search(s)]
    assert not hits, hits


def test_lock_in_evidence_must_name_a_known_field() -> None:
    d = copy.deepcopy(load("broadband"))
    d["lock_in"]["evidence"] = [{"field": "colour", "quote": "q", "url": "https://x.example"}]
    assert list(RESPONSE.iter_errors(d))


# --------------------------------------------------------------------------- request terms


def base_request() -> dict:
    return json.loads((FIXTURES / "requests" / "req_netflix.json").read_text())


def with_terms(*docs: dict) -> dict:
    req = base_request()
    req["terms"] = list(docs)
    return req


TEXT_DOC = {
    "url": "https://help.netflix.com/legal/termsofuse",
    "kind": "terms",
    "text": "Your membership will continue until terminated.",
}
PDF_DOC = {
    "url": "https://www.bt.com/terms.pdf",
    "kind": "terms",
    "pdf_b64": "JVBERi0xLjQK",
}
FAILED_DOC = {
    "url": "https://www.example.com/terms",
    "kind": "terms",
    "fetch_failed": True,
    "error": "HTTP 403",
}


def test_request_without_terms_is_still_valid() -> None:
    assert not list(REQUEST.iter_errors(base_request()))


@pytest.mark.parametrize("doc", [TEXT_DOC, PDF_DOC, FAILED_DOC], ids=["text", "pdf", "failed"])
def test_request_accepts_terms_documents(doc: dict) -> None:
    errors = [e.message for e in REQUEST.iter_errors(with_terms(doc))]
    assert not errors, errors


def test_document_without_content_must_be_marked_failed() -> None:
    bad = {k: v for k, v in TEXT_DOC.items() if k != "text"}
    assert list(REQUEST.iter_errors(with_terms(bad)))


def test_pdf_document_must_have_bytes() -> None:
    bad = {k: v for k, v in PDF_DOC.items() if k != "pdf_b64"}
    assert list(REQUEST.iter_errors(with_terms(bad)))


def test_unknown_kind_is_rejected() -> None:
    assert list(REQUEST.iter_errors(with_terms({**TEXT_DOC, "kind": "brochure"})))


def test_unknown_field_is_rejected() -> None:
    assert list(REQUEST.iter_errors(with_terms({**FAILED_DOC, "fetch_status": "failed"})))


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.parametrize("doc", [TEXT_DOC, PDF_DOC, FAILED_DOC], ids=["text", "pdf", "failed"])
async def test_server_accepts_terms_documents(client: AsyncClient, doc: dict) -> None:
    req = with_terms(doc)
    req["install_id"] = f"contract-test-{doc['url']}"
    async with client.stream("POST", "/analyse", json=req) as resp:
        assert resp.status_code == 200


async def test_server_rejects_ok_document_without_content(client: AsyncClient) -> None:
    bad = {k: v for k, v in TEXT_DOC.items() if k != "text"}
    req = with_terms(bad)
    req["install_id"] = "contract-test-bad-terms"
    resp = await client.post("/analyse", json=req)
    assert resp.status_code == 422
