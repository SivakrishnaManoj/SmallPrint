#!/usr/bin/env python3
"""Company-matcher coverage: run the live lookup for well-known UK brands and report.

Usage (from the repo root, with the backend's Python environment active):
    python scripts/company_coverage.py                 # the built-in brand list
    python scripts/company_coverage.py "Pepsi Max" Walkers
    COMPANIES_HOUSE_API_KEY=... python scripts/company_coverage.py

Needs network access to Wikidata and GLEIF (and Companies House when a key is set).
Prints, per brand, the owner found, the UK company number, how it was matched and
how many records joined, then the match rates. Run it before and after a matcher
change: a drop in either rate means the change broke matching somewhere.

Nothing here is an expected answer: the script reports what the live sources say.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from smallprint.company import company_lookup  # noqa: E402

# (brand as a shopping page would show it, a page domain for that brand)
BRANDS: list[tuple[str, str]] = [
    ("Pepsi Max", "amazon.co.uk"),
    ("Walkers", "walkers.co.uk"),
    ("Dove", "dove.com"),
    ("Andrex", "andrex.co.uk"),
    ("Cadbury", "cadbury.co.uk"),
    ("Heinz", "heinz.co.uk"),
    ("Lucozade", "lucozade.com"),
    ("Hovis", "hovis.co.uk"),
    ("Warburtons", "warburtons.co.uk"),
    ("Gillette", "gillette.co.uk"),
    ("Nespresso", "nespresso.com"),
    ("SodaStream", "sodastream.co.uk"),
    ("Tesco", "tesco.com"),
    ("Sainsbury's", "sainsburys.co.uk"),
    ("Boots", "boots.com"),
    ("Netflix", "netflix.com"),
    ("Sky", "sky.com"),
    ("BT", "bt.com"),
    ("Virgin Media", "virginmedia.com"),
    ("PureGym", "puregym.com"),
]


async def main(brands: list[tuple[str, str]]) -> int:
    rows = []
    for brand, domain in brands:  # one at a time: be polite to the free APIs
        started = time.monotonic()
        try:
            r = await company_lookup(brand, domain)
        except Exception as e:  # a crash is itself a finding
            r = {"parent": None, "ch_number": None, "match_via": f"ERROR {type(e).__name__}: {e}", "records": []}
        rows.append((brand, r, time.monotonic() - started))

    w = max(len(b) for b, _, _ in rows)
    print(f"{'brand':<{w}}  {'owner':<28} {'UK number':<10} {'records':>7} {'secs':>5}  matched via")
    for brand, r, secs in rows:
        print(f"{brand:<{w}}  {(r.get('parent') or '-')[:28]:<28} {r.get('ch_number') or '-':<10} "
              f"{len(r.get('records') or []):>7} {secs:>5.1f}  {r.get('match_via')}")

    n = len(rows)
    owner = sum(1 for _, r, _ in rows if r.get("parent") or r.get("ch_number"))
    uk = sum(1 for _, r, _ in rows if r.get("ch_number"))
    recs = sum(1 for _, r, _ in rows if r.get("records"))
    slow = sum(1 for _, _, s in rows if s > 5)
    print(f"\nowner found: {owner}/{n} ({owner / n:.0%})   UK company number: {uk}/{n} ({uk / n:.0%})   "
          f"with records: {recs}/{n} ({recs / n:.0%})   over 5 s: {slow}")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    sys.exit(asyncio.run(main([(a, "") for a in args] if args else BRANDS)))
