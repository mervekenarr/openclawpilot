from pydantic import BaseModel, Field


class KeywordCreate(BaseModel):
    keyword: str = Field(min_length=2, max_length=80)


class KeywordResponse(BaseModel):
    id: int
    keyword: str
    created_at: str
