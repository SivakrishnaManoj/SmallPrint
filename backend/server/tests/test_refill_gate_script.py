"""S8 (#21): scripts/refill_gate.py with the real lookup and faked Anthropic/Tavily."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx
import httpx2
import pytest
from anthropic import AsyncAnthropic

from smallprint.search_fallback import TavilySearch
from smallprint.test_refill import GOOD, NONE, PAGE

ROOT = Path(__file__).parent.parent.parent.parent
spec = importlib.util.spec_from_file_location("refill_gate", ROOT / "scripts" / "refill_gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def fake_clients(found_brands: set[str]):
    """Tavily returns a page per brand; the LLM finds a refill only for found_brands."""
    def tavily(request):
        brand = json.loads(request.content)["query"].split(" ")[0]
        return httpx.Response(200, json={"query": "q", "answer": None, "images": [], "response_time": 0.1, "results": [
            {"title": brand, "url": f"https://www.amazon.co.uk/dp/{brand}", "content": "s", "score": 1,
             "raw_content": PAGE.replace("Oral-B", brand)}]})

    def llm(request):
        body = json.loads(request.content)
        # content is "<document>\nProduct: <brand> <name>\n\n<page>\n</document>"
        brand = body["messages"][0]["content"].split("\n")[1].split(" ")[1]
        out = json.loads(json.dumps(GOOD).replace("Oral-B", brand)) if brand in found_brands else NONE
        return httpx2.Response(200, json={
            "id": "m", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
            "content": [{"type": "text", "text": json.dumps(out)}], "stop_reason": "end_turn",
            "stop_sequence": None, "usage": {"input_tokens": 1500, "output_tokens": 200}})

    return lambda: (
        AsyncAnthropic(api_key="t", max_retries=0, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(llm))),
        TavilySearch("tvly-t", http=httpx.AsyncClient(transport=httpx.MockTransport(tavily))),
    )


BRANDS = ["SodaStream", "Canon", "Nespresso", "Gillette", "Brita", "Philips", "Oral-B", "Dyson", "Ninja", "Kindle"]


def write_products(tmp_path: Path, brands=BRANDS) -> Path:
    p = tmp_path / "gate.csv"
    p.write_text("url,name,brand\n# comment\n" + "".join(
        f"https://www.amazon.co.uk/dp/{b},{b} product,{b}\n" for b in brands), encoding="utf-8")
    return p


@pytest.mark.parametrize("n_found,code,verdict", [(7, 0, "7/10, PASS"), (6, 1, "6/10, FAIL")])
def test_gate_counts_and_records_the_result(monkeypatch, tmp_path, n_found, code, verdict):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("TAVILY_API_KEY", "x")
    monkeypatch.setattr(gate, "make_clients", fake_clients(set(BRANDS[:n_found])))
    out = tmp_path / "result.md"

    assert gate.main(["--list", str(write_products(tmp_path)), "--out", str(out)]) == code

    text = out.read_text(encoding="utf-8")
    assert verdict in text
    assert text.count("| found |") == n_found
    assert "https://www.amazon.co.uk/dp/SodaStream" in text  # each pass links its source


def test_gate_needs_exactly_ten(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("TAVILY_API_KEY", "x")
    monkeypatch.setattr(gate, "make_clients", fake_clients(set(BRANDS)))
    out = tmp_path / "r.md"
    gate.main(["--list", str(write_products(tmp_path, BRANDS[:8])), "--out", str(out)])
    assert "FAIL" in out.read_text() and "exactly 10" in out.read_text()


@pytest.mark.parametrize("keys", [{}, {"ANTHROPIC_API_KEY": "x"}])
def test_gate_refuses_without_real_keys(monkeypatch, tmp_path, keys):
    for k in ("ANTHROPIC_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    for k, v in keys.items():
        monkeypatch.setenv(k, v)
    assert gate.main(["--list", str(write_products(tmp_path))]) == 2


def test_example_list_parses_to_ten_products():
    assert len(gate.read_products(ROOT / "demo" / "refill_gate.example.csv")) == 10
