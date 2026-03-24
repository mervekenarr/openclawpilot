from typing import Literal

from pydantic import BaseModel, Field


class DecisionMakerDraft(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    title: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=160)
    linkedin_hint: str | None = Field(default=None, max_length=240)

    class Config:
        extra = "forbid"


class EnrichmentDraftPayload(BaseModel):
    company_summary: str = Field(min_length=5, max_length=300)
    recent_signal: str = Field(min_length=5, max_length=300)
    fit_reason: str = Field(min_length=5, max_length=300)
    summary: str = Field(min_length=5, max_length=300)
    priority: Literal["high", "medium", "low"]
    confidence: Literal["high", "medium", "low"]
    data_reliability: Literal["high", "medium", "low"]
    decision_maker: DecisionMakerDraft
    missing_fields: list[str] = Field(default_factory=list, max_length=10)
    source_notes: list[str] = Field(default_factory=list, max_length=10)

    class Config:
        extra = "forbid"


class AIDraftReviewRequest(BaseModel):
    note: str | None = Field(default=None, max_length=300)
