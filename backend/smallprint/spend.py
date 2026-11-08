"""Per-install daily LLM spend limit and token caps (S4, #14).

Every LLM call goes through ``SpendTracker.guard``:
  1. Before the call, reserve its worst-case cost (input estimate + max_tokens
     of output). If that would take the install over today's limit, raise
     ``SpendLimitReached`` and the call is never made.
  2. After the call, settle the reservation to the real cost from
     ``response.usage`` and log the running total.

Reserving the worst case first means concurrent calls (asyncio.gather) can't
overshoot the limit together. Spend is keyed on the install UUID and resets
at midnight UTC. It lives in memory: a restart resets it, which is fine for
a single Railway instance.
"""
from __future__ import annotations

import hashlib
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator, Callable

log = logging.getLogger(__name__)

# Hard caps per call (CLAUDE.md: chunk ~6k, cap input at 8k).
MAX_INPUT_TOKENS = 8_000
MAX_OUTPUT_TOKENS = 4_000

# claude-haiku-5-5, USD per token, prompts up to 100K tokens.
PRICE_IN = 0.10 / 1_000_000
PRICE_OUT = 0.50 / 1_000_000

# About 75 worst-case extraction calls per install per day.
DEFAULT_DAILY_LIMIT_USD = float(os.environ.get("SMALLPRINT_DAILY_LIMIT_USD", "0.20"))


class SpendLimitReached(Exception):
    """Today's limit for this install is used up. The card state is ``limit_reached``."""


class TokenCapExceeded(ValueError):
    """A single call would go over the per-call input cap."""


def call_cost(input_tokens: int, output_tokens: int) -> float:
    return input_tokens * PRICE_IN + output_tokens * PRICE_OUT


def _utc_day() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _short(install_id: str) -> str:
    """Log a hash, not the raw install UUID."""
    return hashlib.sha256(install_id.encode()).hexdigest()[:10]


@dataclass
class Usage:
    """Filled in by the caller with the response's token usage."""
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class SpendTracker:
    daily_limit_usd: float = DEFAULT_DAILY_LIMIT_USD
    today: Callable[[], str] = _utc_day
    _spent: dict[tuple[str, str], float] = field(default_factory=dict)
    # Per-install overrides of daily_limit_usd (used for the pre-warm run).
    _limits: dict[str, float] = field(default_factory=dict)

    def limit_for(self, install_id: str) -> float:
        return self._limits.get(install_id, self.daily_limit_usd)

    def set_limit(self, install_id: str, usd: float) -> None:
        self._limits[install_id] = usd

    def spent(self, install_id: str) -> float:
        return self._spent.get((install_id, self.today()), 0.0)

    def remaining(self, install_id: str) -> float:
        return max(0.0, self.limit_for(install_id) - self.spent(install_id))

    @asynccontextmanager
    async def guard(self, install_id: str, input_tokens: int, max_output_tokens: int = MAX_OUTPUT_TOKENS) -> AsyncIterator[Usage]:
        """Reserve, run the call inside the block, then settle on the real usage.

        If the block raises before filling in usage, the full reservation is kept:
        a failed call may still have been billed.
        """
        if not install_id:
            raise SpendLimitReached("no install id")
        if input_tokens > MAX_INPUT_TOKENS:
            raise TokenCapExceeded(f"{input_tokens} input tokens > cap {MAX_INPUT_TOKENS}")
        max_output_tokens = min(max_output_tokens, MAX_OUTPUT_TOKENS)

        key = (install_id, self.today())
        reserved = call_cost(input_tokens, max_output_tokens)
        before = self._spent.get(key, 0.0)
        limit = self.limit_for(install_id)
        if before + reserved > limit:
            log.warning("spend limit reached install=%s day=%s spent=$%.4f limit=$%.2f",
                        _short(install_id), key[1], before, limit)
            raise SpendLimitReached(f"daily limit ${limit:.2f} reached")
        # No await between the check and the reservation, so this is atomic in asyncio.
        self._spent[key] = before + reserved

        usage = Usage()
        yield usage

        if usage.input_tokens or usage.output_tokens:
            actual = call_cost(usage.input_tokens, usage.output_tokens)
            self._spent[key] = self._spent.get(key, 0.0) - reserved + actual
        else:
            actual = reserved
        log.info("spend install=%s day=%s call=$%.5f total=$%.4f limit=$%.2f",
                 _short(install_id), key[1], actual, self._spent[key], limit)


# Shared by the app. Tests make their own.
tracker = SpendTracker()
