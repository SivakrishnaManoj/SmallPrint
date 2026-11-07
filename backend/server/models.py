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


class AnalyseRequest(BaseModel):
    item: ItemIn
    purchase_type_signals: list[str] = []
    links: list[LinkIn] = []
    page_text_snippets: list[str] = []
    install_id: str

    @field_validator("install_id")
    @classmethod
    def install_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("install_id must not be empty")
        return v
