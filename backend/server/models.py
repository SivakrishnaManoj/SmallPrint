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


class PriceDriftIn(BaseModel):
    first_seen: float | None = None
    current: float | None = None


class TermsDocumentIn(BaseModel):
    """A T&C page or PDF fetched by the extension. Mirrors terms_document in request.schema.json."""

    url: str
    kind: Literal[
        "terms", "returns", "warranty", "cancel", "subscription",
        "contract_summary", "price_guide", "privacy", "other",
    ] = "terms"
    fetch_status: Literal["ok", "failed"]
    content_type: Literal["text", "pdf"] | None = None
    text: str | None = Field(default=None, max_length=500_000)
    pdf_base64: str | None = Field(default=None, max_length=20_000_000)
    error: str | None = None

    @model_validator(mode="after")
    def content_present_when_ok(self) -> "TermsDocumentIn":
        if self.fetch_status != "ok":
            return self
        if self.content_type is None:
            raise ValueError("content_type is required when fetch_status is 'ok'")
        if self.content_type == "text" and not self.text:
            raise ValueError("text is required when content_type is 'text'")
        if self.content_type == "pdf" and not self.pdf_base64:
            raise ValueError("pdf_base64 is required when content_type is 'pdf'")
        return self


class AnalyseRequest(BaseModel):
    item: ItemIn
    purchase_type_signals: list[str] = []
    links: list[LinkIn] = []
    page_text_snippets: list[str] = []
    terms: list[TermsDocumentIn] = []
    price_drift: PriceDriftIn = PriceDriftIn()
    install_id: str

    @field_validator("install_id")
    @classmethod
    def install_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("install_id must not be empty")
        return v
