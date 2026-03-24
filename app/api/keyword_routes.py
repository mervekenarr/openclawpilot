from fastapi import APIRouter

from app import store
from app.schemas.keywords import KeywordCreate, KeywordResponse


router = APIRouter(tags=["keywords"])


@router.post("/keywords", response_model=KeywordResponse)
def create_keyword(data: KeywordCreate):
    new_keyword = {
        "id": store.next_id("keyword"),
        "keyword": data.keyword,
        "created_at": store.utc_now(),
    }

    store.keywords.append(new_keyword)
    return new_keyword


@router.get("/keywords")
def list_keywords():
    return store.keywords
