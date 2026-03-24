from typing import Literal

from pydantic import BaseModel, Field


class CrawlRequest(BaseModel):
    keyword: str = Field(min_length=2, max_length=80)
    sector: str | None = Field(default=None, max_length=80)
    limit: int = Field(default=5, ge=1, le=10)


class LeadReviewRequest(BaseModel):
    action: Literal["approve", "reject", "hold", "revise"]
    reviewer_note: str | None = Field(default=None, max_length=300)


class MessageDraftRequest(BaseModel):
    channel: Literal["email", "linkedin"] = "email"


class CRMUpdateRequest(BaseModel):
    owner: str | None = Field(default=None, max_length=100)


class ReplyUpdateRequest(BaseModel):
    reply_type: Literal["positive", "meeting_request", "negative", "needs_follow_up"]
    detail: str | None = Field(default=None, max_length=400)
