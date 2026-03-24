from fastapi import APIRouter, Header, HTTPException

from app.auth import AuthorizationError, ensure_permission
from app import store
from app.schemas.keywords import KeywordCreate, KeywordResponse


router = APIRouter(tags=["keywords"])


@router.post("/keywords", response_model=KeywordResponse)
def create_keyword(
    data: KeywordCreate,
    actor_role: str = Header(default="viewer", alias="X-Actor-Role"),
    actor_name: str = Header(default="anonymous", alias="X-Actor-Name"),
):
    try:
        ensure_permission(actor_role, "intake", actor_name)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    return store.create_keyword(data.keyword)


@router.get("/keywords")
def list_keywords():
    return store.list_keywords()
