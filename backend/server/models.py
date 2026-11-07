from __future__ import annotations
from typing import Any
from pydantic import BaseModel, field_validator


class ItemIn(BaseModel):
    name: str | None = None
    brand: str | None = None
    price: float | None = None
    seller: str | None = None
    url: str
    id: str | None = None


class LinkIn(BaseModel):
    url: str
    text: str
    kind: str


class PriceDriftIn(BaseModel):
    first_seen: float | None = None
    current: float | None = None


class TermsDocIn(BaseModel):
    """A T&C / contract document the extension fetched from the user's browser.

    Send ``text`` for HTML pages and ``pdf_b64`` (base64 PDF bytes) for PDFs.
    If the browser fetch failed, send ``fetch_failed: true`` with no content;
    the backend then falls back to search and labels the card that way.
    """
    url: str
    text: str | None = None
    pdf_b64: str | None = None
    fetch_failed: bool = False


class AnalyseRequest(BaseModel):
    item: ItemIn
    purchase_type_signals: list[str] = []
    links: list[LinkIn] = []
    page_text_snippets: list[str] = []
    price_drift: PriceDriftIn = PriceDriftIn()
    terms: list[TermsDocIn] = []
    # Deprecated: send the X-Install-Id header instead. Kept so existing clients work.
    install_id: str | None = None

    @field_validator("install_id")
    @classmethod
    def install_id_not_empty(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("install_id must not be empty")
        return v
