from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


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


TermsKind = Literal[
    "terms", "returns", "warranty", "cancel", "subscription",
    "contract_summary", "price_guide", "privacy", "other",
]


class TermsDocIn(BaseModel):
    """A T&C page or PDF the extension fetched from the user's browser.

    Mirrors terms_document in contracts/request.schema.json.
    Send ``text`` for HTML pages and ``pdf_b64`` (base64 PDF bytes) for PDFs.
    If the browser fetch failed, send ``fetch_failed: true`` with no content
    and, optionally, ``error``; the backend then falls back to search and
    labels the card that way.
    """

    url: str
    kind: TermsKind = "terms"
    text: str | None = Field(default=None, max_length=500_000)
    pdf_b64: str | None = Field(default=None, max_length=20_000_000)
    fetch_failed: bool = False
    error: str | None = None

    @model_validator(mode="after")
    def content_present_unless_failed(self) -> "TermsDocIn":
        if not self.fetch_failed and not self.text and not self.pdf_b64:
            raise ValueError("text or pdf_b64 is required unless fetch_failed is true")
        return self


class AnalyseRequest(BaseModel):
    item: ItemIn
    purchase_type_signals: list[str] = []
    links: list[LinkIn] = []
    page_text_snippets: list[str] = []
    terms: list[TermsDocIn] = []
    # Deprecated: send the X-Install-Id header instead. Kept so existing clients work.
    install_id: str | None = None

    @field_validator("install_id")
    @classmethod
    def install_id_not_empty(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("install_id must not be empty")
        return v


class FlagCompanyMatchBody(BaseModel):
    """Body for POST /flag/company-match.

    All fields except page_url are optional so the client can send whatever
    context it has without risk of a validation error.
    """
    brand: str | None = None
    matched_parent: str | None = None
    ch_number: str | None = None
    match_via: str | None = None
    page_url: str = ""
    correction: str | None = Field(default=None, max_length=500)
    install_id: str | None = None
