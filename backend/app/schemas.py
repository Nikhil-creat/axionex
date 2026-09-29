"""Pydantic v2 request/response contracts."""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RunRequest(BaseModel):
    product_id: uuid.UUID | None = None
    sku: str | None = None
    auto_apply: bool = False
    customer_lat: float = Field(17.385, ge=-90, le=90)
    customer_lon: float = Field(78.4867, ge=-180, le=180)
    min_margin: float = Field(0.25, ge=0.0, le=0.9)
    max_change_pct: float = Field(0.12, gt=0.0, le=0.5)

    @model_validator(mode="after")
    def _need_target(self) -> "RunRequest":
        if not self.product_id and not self.sku:
            raise ValueError("Provide product_id or sku")
        return self


class RunAccepted(BaseModel):
    run_id: uuid.UUID
    stream_url: str


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    product_id: uuid.UUID
    status: str
    decision: dict[str, Any] | None
    trace: list[dict[str, Any]]
    applied: bool
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class ProductOut(BaseModel):
    id: uuid.UUID
    sku: str
    name: str
    category: str
    cost: float
    current_price: float
    map_price: float | None
    available_units: int
    last_decision: dict[str, Any] | None = None


class RagDocument(BaseModel):
    text: str = Field(min_length=10, max_length=20_000)
    source: str = "manual"
    kind: str = Field("market_trend", description="market_trend | competitor | brand_guideline | scrape_log")
    sku: str | None = None


class RagIngestRequest(BaseModel):
    documents: list[RagDocument] = Field(min_length=1, max_length=100)


class RagQueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    k: int = Field(6, ge=1, le=20)
    sku: str | None = None
    kind: str | None = None


class RagSource(BaseModel):
    text: str
    source: str
    kind: str
    score: float


class RagAnswer(BaseModel):
    answer: str
    mode: str
    sources: list[RagSource]


class WebhookEvent(BaseModel):
    event_type: str = Field(description="competitor.price_changed | inventory.adjusted | order.created")
    data: dict[str, Any]
