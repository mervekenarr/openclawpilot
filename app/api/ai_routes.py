from fastapi import APIRouter, Header, HTTPException

from app.auth import AuthorizationError, ensure_permission
from app.schemas.ai import AIDraftReviewRequest
from app.services.ai_service import (
    AIDraftValidationError,
    approve_raw_lead_enrichment_draft,
    archive_raw_lead_enrichment_draft,
    build_openclaw_preview,
    build_raw_lead_draft_comparison,
    build_raw_lead_enrichment_preview,
    get_ai_draft,
    list_raw_lead_ai_drafts,
    reject_raw_lead_enrichment_draft,
    restore_raw_lead_enrichment_draft,
    request_raw_lead_enrichment_draft,
)
from app.services.openclaw_service import get_raw_lead


router = APIRouter(tags=["ai"])


def _require_permission(actor_role: str, actor_name: str, permission: str) -> dict:
    try:
        return ensure_permission(actor_role, permission, actor_name)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/ai/raw-leads/{lead_id}/drafts")
def get_raw_lead_drafts(lead_id: int, include_archived: bool = False):
    raw_lead = get_raw_lead(lead_id)

    if not raw_lead:
        raise HTTPException(status_code=404, detail="Raw lead not found")

    return list_raw_lead_ai_drafts(lead_id, include_archived=include_archived)


@router.get("/ai/raw-leads/{lead_id}/openclaw-preview")
def get_raw_lead_openclaw_preview(lead_id: int):
    raw_lead = get_raw_lead(lead_id)

    if not raw_lead:
        raise HTTPException(status_code=404, detail="Raw lead not found")

    try:
        return build_openclaw_preview(lead_id)
    except AIDraftValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ai/raw-leads/{lead_id}/enrichment-draft")
def create_raw_lead_enrichment_draft(
    lead_id: int,
    actor_role: str = Header(default="viewer", alias="X-Actor-Role"),
    actor_name: str = Header(default="anonymous", alias="X-Actor-Name"),
):
    actor = _require_permission(actor_role, actor_name, "raw_lead_write")
    raw_lead = get_raw_lead(lead_id)

    if not raw_lead:
        raise HTTPException(status_code=404, detail="Raw lead not found")

    try:
        return request_raw_lead_enrichment_draft(raw_lead, actor["name"])
    except AIDraftValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/ai/drafts/{draft_id}")
def get_ai_draft_detail(draft_id: int):
    draft = get_ai_draft(draft_id)

    if not draft:
        raise HTTPException(status_code=404, detail="AI draft not found")

    return draft


@router.get("/ai/drafts/{draft_id}/preview")
def get_ai_draft_preview(draft_id: int):
    draft = get_ai_draft(draft_id)

    if not draft:
        raise HTTPException(status_code=404, detail="AI draft not found")

    try:
        return build_raw_lead_enrichment_preview(draft)
    except AIDraftValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/ai/drafts/{draft_id}/compare/{other_draft_id}")
def compare_ai_drafts(draft_id: int, other_draft_id: int):
    draft = get_ai_draft(draft_id)
    other_draft = get_ai_draft(other_draft_id)

    if not draft or not other_draft:
        raise HTTPException(status_code=404, detail="AI draft not found")

    try:
        return build_raw_lead_draft_comparison(draft, other_draft)
    except AIDraftValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ai/drafts/{draft_id}/approve")
def approve_ai_draft(
    draft_id: int,
    actor_role: str = Header(default="viewer", alias="X-Actor-Role"),
    actor_name: str = Header(default="anonymous", alias="X-Actor-Name"),
):
    actor = _require_permission(actor_role, actor_name, "raw_lead_write")
    draft = get_ai_draft(draft_id)

    if not draft:
        raise HTTPException(status_code=404, detail="AI draft not found")

    try:
        return approve_raw_lead_enrichment_draft(draft, actor["name"])
    except AIDraftValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ai/drafts/{draft_id}/reject")
def reject_ai_draft(
    draft_id: int,
    data: AIDraftReviewRequest,
    actor_role: str = Header(default="viewer", alias="X-Actor-Role"),
    actor_name: str = Header(default="anonymous", alias="X-Actor-Name"),
):
    actor = _require_permission(actor_role, actor_name, "raw_lead_write")
    draft = get_ai_draft(draft_id)

    if not draft:
        raise HTTPException(status_code=404, detail="AI draft not found")

    try:
        return reject_raw_lead_enrichment_draft(draft, actor["name"], data.note)
    except AIDraftValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ai/drafts/{draft_id}/archive")
def archive_ai_draft(
    draft_id: int,
    data: AIDraftReviewRequest,
    actor_role: str = Header(default="viewer", alias="X-Actor-Role"),
    actor_name: str = Header(default="anonymous", alias="X-Actor-Name"),
):
    actor = _require_permission(actor_role, actor_name, "raw_lead_write")
    draft = get_ai_draft(draft_id)

    if not draft:
        raise HTTPException(status_code=404, detail="AI draft not found")

    try:
        return archive_raw_lead_enrichment_draft(draft, actor["name"], data.note)
    except AIDraftValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ai/drafts/{draft_id}/restore")
def restore_ai_draft(
    draft_id: int,
    data: AIDraftReviewRequest,
    actor_role: str = Header(default="viewer", alias="X-Actor-Role"),
    actor_name: str = Header(default="anonymous", alias="X-Actor-Name"),
):
    actor = _require_permission(actor_role, actor_name, "raw_lead_write")
    draft = get_ai_draft(draft_id)

    if not draft:
        raise HTTPException(status_code=404, detail="AI draft not found")

    try:
        return restore_raw_lead_enrichment_draft(draft, actor["name"], data.note)
    except AIDraftValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
