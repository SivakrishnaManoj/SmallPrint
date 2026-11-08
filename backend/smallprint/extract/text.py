"""Turn fetched T&C documents into plain text, and chunk it for the LLM (S3, #13).

HTML goes through trafilatura, PDFs through PyMuPDF. The text produced here
is the *source* the quote verifier checks against, so it must be the same
text the LLM saw.
"""
from __future__ import annotations

import base64
import re

import pymupdf
import trafilatura

# Rough token estimate: ~4 characters per token for English legal text.
# Deliberately conservative; the hard 8k cap is enforced on this estimate.
CHARS_PER_TOKEN = 4
CHUNK_TOKENS = 6_000


def estimate_tokens(text: str) -> int:
    return -(-len(text) // CHARS_PER_TOKEN)  # ceil


def html_to_text(html: str) -> str:
    """Main text of a T&C page. Falls back to tag-stripping if trafilatura finds nothing."""
    text = trafilatura.extract(html, include_comments=False, include_tables=True, favor_recall=True)
    if text:
        return text
    stripped = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S | re.I)
    stripped = re.sub(r"<[^>]+>", " ", stripped)
    return " ".join(stripped.split())


def pdf_to_text(pdf_bytes: bytes) -> str:
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)


def pdf_b64_to_text(pdf_b64: str) -> str:
    return pdf_to_text(base64.b64decode(pdf_b64))


def chunk_text(text: str, max_tokens: int = CHUNK_TOKENS) -> list[str]:
    """Split ``text`` into chunks of at most ``max_tokens`` (estimated).

    Splits on paragraph breaks, then lines, then sentence ends, and only
    hard-cuts a single run with no break in it. Every chunk is an exact
    substring of ``text``, so quotes verified against a chunk are also in
    the document.
    """
    max_chars = max_tokens * CHARS_PER_TOKEN
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            window = text[start:end]
            for sep in ("\n\n", "\n", ". "):
                cut = window.rfind(sep)
                if cut > max_chars // 2:
                    end = start + cut + len(sep)
                    break
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        start = end
    return chunks
