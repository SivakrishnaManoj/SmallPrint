"""Per-domain T&C cache (S7, #16).

Two levels, both holding *verified* fields only (the output of the quote
verifier, never raw LLM output):

* Per document, keyed on (url, sha256 of its text, source). Same text, same
  quotes, so the verification still holds and the LLM isn't called again.
  A changed page has a different hash and is extracted afresh.
* Per site (the shopping page's domain): the merged T&C fields last extracted
  for that site. Used when a request sends no usable T&C documents, so a
  repeat visit gets its T&C cards straight away without fetching, searching or
  calling the LLM.

Entries expire after 24 h. Nothing user-specific is stored: only T&C content
and the quotes taken from it. The cache lives in memory (one Railway
instance), so a redeploy empties it: run the pre-warm after the final deploy.
"""
from __future__ import annotations

import copy
import hashlib
import time
from dataclasses import dataclass, field
from typing import Callable

TTL_S = 24 * 60 * 60
MAX_ENTRIES = 5_000  # oldest dropped beyond this

Fields = dict[str, dict]


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class TermsCache:
    ttl_s: float = TTL_S
    clock: Callable[[], float] = time.monotonic
    _docs: dict[tuple[str, str, str | None], tuple[float, Fields]] = field(default_factory=dict)
    _sites: dict[str, tuple[float, Fields]] = field(default_factory=dict)
    _refills: dict[str, tuple[float, dict]] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def _get(self, store: dict, key) -> Fields | None:
        entry = store.get(key)
        if entry is None or self.clock() - entry[0] > self.ttl_s:
            store.pop(key, None)
            self.misses += 1
            return None
        self.hits += 1
        return copy.deepcopy(entry[1])

    def _put(self, store: dict, key, fields: Fields) -> None:
        store[key] = (self.clock(), copy.deepcopy(fields))
        while len(store) > MAX_ENTRIES:
            store.pop(next(iter(store)))

    def get_doc(self, url: str, text: str, source: str | None) -> Fields | None:
        return self._get(self._docs, (url, text_hash(text), source))

    def has_doc(self, url: str, text: str, source: str | None) -> bool:
        entry = self._docs.get((url, text_hash(text), source))
        return entry is not None and self.clock() - entry[0] <= self.ttl_s

    def put_doc(self, url: str, text: str, source: str | None, fields: Fields) -> None:
        self._put(self._docs, (url, text_hash(text), source), fields)

    def get_site(self, site: str) -> Fields | None:
        return self._get(self._sites, site)

    def put_site(self, site: str, fields: Fields) -> None:
        if fields:  # never cache "nothing found" for a whole site
            self._put(self._sites, site, fields)

    # Refill lookups (S8): {"stream": usage stream or None}, keyed on site|brand|name.
    def get_refill(self, key: str) -> dict | None:
        return self._get(self._refills, key)

    def put_refill(self, key: str, entry: dict) -> None:
        self._put(self._refills, key, entry)

    def clear(self) -> None:
        self._docs.clear()
        self._sites.clear()
        self._refills.clear()
        self.hits = self.misses = 0


# Shared by the app. Tests make their own.
cache = TermsCache()
