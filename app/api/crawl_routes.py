from fastapi import APIRouter, Header, HTTPException, Query

from app.auth import AuthorizationError, ensure_permission
from app import store
from app.schemas.leads import CrawlRequest, LeadReviewRequest, NoteCreateRequest, RawLeadUpdateRequest
from app.services.openclaw_service import (
    add_raw_lead_note,
    build_raw_lead_timeline,
    enrich_lead,
    generate_raw_leads,
    get_raw_lead,
    review_raw_lead,
    update_raw_lead,
)


router = APIRouter(tags=["crawl"])


def _payload(model) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_none=True)

    return model.dict(exclude_none=True)


def _require_permission(actor_role: str, actor_name: str, permission: str) -> dict:
    try:
        return ensure_permission(actor_role, permission, actor_name)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/crawl/start")
def start_crawl(
    data: CrawlRequest,
    actor_role: str = Header(default="viewer", alias="X-Actor-Role"),
    actor_name: str = Header(default="anonymous", alias="X-Actor-Name"),
):
    _require_permission(actor_role, actor_name, "intake")

    generated_leads = generate_raw_leads(
        keyword=data.keyword,
        sector=data.sector,
        limit=data.limit,
    )

    return {
        "message": "Mock crawl tamamlandi.",
        "generated_count": len(generated_leads),
        "raw_leads": generated_leads,
    }


@router.get("/raw-leads")
def list_raw_leads(
    status: str | None = None,
    research_status: str | None = None,
    priority: str | None = None,
    data_reliability: str | None = None,
    search: str | None = None,
    limit: int | None = Query(default=None, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    return store.list_raw_leads(
        status=status,
        research_status=research_status,
        priority=priority,
        data_reliability=data_reliability,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get("/raw-leads/{lead_id}")
def get_raw_lead_detail(lead_id: int):
    raw_lead = get_raw_lead(lead_id)

    if not raw_lead:
        raise HTTPException(status_code=404, detail="Raw lead not found")

    return raw_lead


@router.get("/raw-leads/{lead_id}/timeline")
def get_raw_lead_timeline(lead_id: int):
    raw_lead = get_raw_lead(lead_id)

    if not raw_lead:
        raise HTTPException(status_code=404, detail="Raw lead not found")

    return {
        "raw_lead_id": lead_id,
        "entries": build_raw_lead_timeline(raw_lead),
    }


@router.post("/raw-leads/{lead_id}/research")
def research_raw_lead(
    lead_id: int,
    actor_role: str = Header(default="viewer", alias="X-Actor-Role"),
    actor_name: str = Header(default="anonymous", alias="X-Actor-Name"),
):
    _require_permission(actor_role, actor_name, "raw_lead_write")

    raw_lead = get_raw_lead(lead_id)

    if not raw_lead:
        raise HTTPException(status_code=404, detail="Raw lead not found")

    return enrich_lead(raw_lead)


@router.patch("/raw-leads/{lead_id}")
def patch_raw_lead(
    lead_id: int,
    data: RawLeadUpdateRequest,
    actor_role: str = Header(default="viewer", alias="X-Actor-Role"),
    actor_name: str = Header(default="anonymous", alias="X-Actor-Name"),
):
    _require_permission(actor_role, actor_name, "raw_lead_write")

    raw_lead = get_raw_lead(lead_id)

    if not raw_lead:
        raise HTTPException(status_code=404, detail="Raw lead not found")

    updates = _payload(data)
    if not updates:
        raise HTTPException(status_code=400, detail="No update fields provided")

    return update_raw_lead(raw_lead, updates=updates)


@router.post("/raw-leads/{lead_id}/notes")
def create_raw_lead_note(
    lead_id: int,
    data: NoteCreateRequest,
    actor_role: str = Header(default="viewer", alias="X-Actor-Role"),
    actor_name: str = Header(default="anonymous", alias="X-Actor-Name"),
):
    _require_permission(actor_role, actor_name, "raw_lead_write")

    raw_lead = get_raw_lead(lead_id)

    if not raw_lead:
        raise HTTPException(status_code=404, detail="Raw lead not found")

    return add_raw_lead_note(raw_lead, note=data.note)


@router.post("/raw-leads/{lead_id}/review")
def review_lead(
    lead_id: int,
    data: LeadReviewRequest,
    actor_role: str = Header(default="viewer", alias="X-Actor-Role"),
    actor_name: str = Header(default="anonymous", alias="X-Actor-Name"),
):
    _require_permission(actor_role, actor_name, "raw_lead_write")

    raw_lead = get_raw_lead(lead_id)

    if not raw_lead:
        raise HTTPException(status_code=404, detail="Raw lead not found")
    if raw_lead.get("status") not in {"needs_review", "needs_revision", "on_hold"}:
        raise HTTPException(status_code=400, detail="Raw lead is not in a reviewable state")

    if raw_lead.get("research_status") != "completed" and data.action == "approve":
        raise HTTPException(status_code=400, detail="Lead must be researched before approval")

    return review_raw_lead(
        raw_lead=raw_lead,
        action=data.action,
        reviewer_note=data.reviewer_note,
    )
