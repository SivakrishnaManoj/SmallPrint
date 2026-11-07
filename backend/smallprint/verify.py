"""Quote verifier: the single choke point for every LLM-derived value (S1, #7).

Rule: quote or null. A value from the LLM is shown only when its quote
appears verbatim in the source text it was extracted from. If not, the
caller emits the card as ``not_found``.

The match is deterministic and exact after two normalisations only:
  * runs of whitespace (spaces, tabs, newlines, non-breaking spaces, ...)
    collapse to a single space, and leading/trailing whitespace is dropped;
  * typographic quotes map to their ASCII forms (‘ ’ ‚ ‛ -> ', “ ” „ ‟ -> ").

Nothing else is normalised: case, punctuation, dashes, digits and wording
must match exactly. There is no fuzzy matching, by design.
"""
from __future__ import annotations

from typing import Any, Mapping

_QUOTE_MAP = str.maketrans({
    "‘": "'",  # ‘ left single
    "’": "'",  # ’ right single / apostrophe
    "‚": "'",  # ‚ single low-9
    "‛": "'",  # ‛ single high-reversed-9
    "“": '"',  # “ left double
    "”": '"',  # ” right double
    "„": '"',  # „ double low-9
    "‟": '"',  # ‟ double high-reversed-9
})


def normalise(text: str) -> str:
    """Collapse whitespace and map typographic quotes to ASCII. Nothing else."""
    # str.split() with no argument splits on any Unicode whitespace,
    # including U+00A0 (no-break space) and the thin/narrow spaces.
    return " ".join(text.translate(_QUOTE_MAP).split())


def verify_quote(quote: str | None, source: str | None) -> bool:
    """True only if ``quote`` appears verbatim in ``source`` (after normalise).

    A missing or blank quote, or a missing or blank source, always fails.
    An empty string would otherwise match every source.
    """
    if not quote or not source:
        return False
    needle = normalise(quote)
    if not needle:
        return False
    return needle in normalise(source)


def verify_field(field: Mapping[str, Any] | None, source: str | None) -> Mapping[str, Any] | None:
    """Return ``field`` unchanged if its value is backed by a verified quote, else None.

    ``field`` is an extracted item with at least ``value`` and ``quote`` keys.
    A null field stays null; a null value stays null; a field whose quote is
    missing or not found in ``source`` becomes None. The caller turns None
    into the ``not_found`` card state. The input is never mutated.
    """
    if field is None or field.get("value") is None:
        return None
    if not verify_quote(field.get("quote"), source):
        return None
    return field
