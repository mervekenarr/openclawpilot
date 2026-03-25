from fastapi import APIRouter, Header, HTTPException

from app.auth import AuthorizationError, get_role_catalog, normalize_actor
from app.adapters.openclaw_client import get_ollama_probe
from app.research_policy import get_research_policy
from app.services.ai_service import get_ai_runtime_info

from app import store


router = APIRouter(tags=["system"])


@router.get("/system/info")
def get_system_info(
    actor_role: str = Header(default="viewer", alias="X-Actor-Role"),
    actor_name: str = Header(default="anonymous", alias="X-Actor-Name"),
):
    try:
        actor = normalize_actor(actor_role, actor_name)
    except AuthorizationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "runtime": store.get_runtime_info(),
        "health": store.healthcheck(),
        "actor": actor,
        "roles": get_role_catalog(),
        "ai": get_ai_runtime_info(),
        "ollama": get_ollama_probe(),
        "research_policy": get_research_policy(),
    }


@router.get("/system/ollama-check")
def get_ollama_check():
    return get_ollama_probe()


@router.get("/system/research-policy")
def get_system_research_policy():
    return get_research_policy()
