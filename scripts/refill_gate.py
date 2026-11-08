#!/usr/bin/env python3
"""The H10 refill gate (S8, #21): do at least 7 of 10 Amazon test products return a refill price with a source?

    OPENAI_API_KEY=... TAVILY_API_KEY=... python scripts/refill_gate.py

Reads demo/refill_gate.csv (url,name,brand: exactly 10 rows, picked by someone
who didn't build the lookup), runs the real refill lookup on each, prints the
result and writes demo/refill_gate_result.md. It posts nothing: to record the
result on the ticket,

    gh issue comment 21 --repo j0h4nn1410/SmallPrint --body-file demo/refill_gate_result.md

If it passes, set SMALLPRINT_REFILL=1 on Railway. If it fails, close #21 as not shipped.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

from smallprint.refill import find_refill  # noqa: E402
from smallprint.search_fallback import TavilySearch  # noqa: E402
from smallprint.spend import SpendTracker  # noqa: E402

DEFAULT_LIST = REPO / "demo" / "refill_gate.csv"
DEFAULT_OUT = REPO / "demo" / "refill_gate_result.md"
PASS_MARK = 7
GATE_INSTALL = "refill-gate"


def make_clients():
    from openai import AsyncOpenAI
    return AsyncOpenAI(), TavilySearch(os.environ["TAVILY_API_KEY"])


def read_products(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        # k is None for overflow cells (e.g. commas in a comment row): ignore them.
        rows = [{k: (v or "").strip() for k, v in r.items() if k is not None} for r in csv.DictReader(f)]
    return [r for r in rows if r.get("url") and not r["url"].startswith("#")]


def passed(stream: dict | None) -> bool:
    """A refill price with a source: a price, its verified quote and the page it came from."""
    if not stream:
        return False
    ev = stream.get("evidence") or {}
    return bool(stream.get("unit_price") and ev.get("quote") and ev.get("url"))


async def run_gate(products: list[dict]) -> list[dict]:
    client, search = make_clients()
    tracker = SpendTracker(daily_limit_usd=2.0)
    results = []
    for p in products:
        try:
            stream = await find_refill(client, search, name=p.get("name"), brand=p.get("brand"),
                                       page_url=p["url"], install_id=GATE_INSTALL, tracker=tracker)
        except Exception as e:  # one bad product must not stop the gate
            stream, err = None, type(e).__name__
        else:
            err = ""
        results.append({**p, "stream": stream, "pass": passed(stream), "error": err})
    return results


def report(results: list[dict]) -> str:
    n = sum(r["pass"] for r in results)
    verdict = "PASS: refill ships" if n >= PASS_MARK and len(results) == 10 else "FAIL: refill does not ship"
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"## Refill gate (H10): {n}/{len(results)}, {verdict}",
        "",
        f"Measured {when} with `scripts/refill_gate.py`. Pass mark: {PASS_MARK} of 10 with a refill price and a source.",
        "",
        "| Product | Result | Refill | Price | Source |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        s = r["stream"]
        if s:
            lines.append(f"| {r.get('name') or r['url']} | found | {s['label']} | £{s['unit_price']:.2f} | {s['evidence']['url']} |")
        else:
            lines.append(f"| {r.get('name') or r['url']} | not found{' (' + r['error'] + ')' if r['error'] else ''} | | | |")
    if len(results) != 10:
        lines += ["", f"Note: the gate needs exactly 10 products; this run had {len(results)}."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="H10 refill gate")
    ap.add_argument("--list", type=Path, default=DEFAULT_LIST)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    missing = [k for k in ("OPENAI_API_KEY", "TAVILY_API_KEY") if not os.environ.get(k)]
    if missing:
        print(f"Set {', '.join(missing)}: the gate measures the real lookup.", file=sys.stderr)
        return 2
    if not args.list.exists():
        print(f"No product list at {args.list}. Copy demo/refill_gate.example.csv and pick the 10.", file=sys.stderr)
        return 2

    results = asyncio.run(run_gate(read_products(args.list)))
    text = report(results)
    args.out.write_text(text, encoding="utf-8")
    print(text)
    print(f"Written to {args.out}")
    return 0 if sum(r["pass"] for r in results) >= PASS_MARK else 1


if __name__ == "__main__":
    sys.exit(main())
