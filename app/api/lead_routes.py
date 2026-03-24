from fastapi import APIRouter, Header, HTTPException, Query

from app.auth import AuthorizationError, ensure_permission
from app import store
from app.schemas.leads import (
    CRMUpdateRequest,
    LeadUpdateRequest,
    MessageDraftRequest,
    NoteCreateRequest,
    ReplyUpdateRequest,
)
from app.services.openclaw_service import (
    WorkflowValidationError,
    add_lead_note,
    approve_message,
    build_lead_timeline,
    generate_first_message,
    generate_follow_up,
    get_lead,
    mark_message_sent,
    record_reply,
    sync_crm,
    update_lead,
)


router = APIRouter(tags=["leads"])


def _payload(model) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_none=True)

    return model.dict(exclude_none=True)


def _require_permission(actor_role: str, actor_name: str, permission: str) -> dict:
    try:
        return ensure_permission(actor_role, permission, actor_name)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/leads")
def list_leads(
    status: str | None = None,
    crm_status: str | None = None,
    outreach_status: str | None = None,
    priority: str | None = None,
    owner: str | None = None,
    search: str | None = None,
    limit: int | None = Query(default=None, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    return store.list_leads(
        status=status,
        crm_status=crm_status,
        outreach_status=outreach_status,
        priority=priority,
        owner=owner,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get("/leads/{lead_id}")
def get_lead_detail(lead_id: int):
    lead = get_lead(lead_id)

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    return lead


@router.get("/leads/{lead_id}/timeline")
def get_lead_timeline(lead_id: int):
    lead = get_lead(lead_id)

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    return {
        "lead_id": lead_id,
        "entries": build_lead_timeline(lead),
    }


@router.patch("/leads/{lead_id}")
def patch_lead(
    lead_id: int,
    data: LeadUpdateRequest,
    actor_role: str = Header(default="viewer", alias="X-Actor-Role"),
    actor_name: str = Header(default="anonymous", alias="X-Actor-Name"),
):
    _require_permission(actor_role, actor_name, "lead_write")

    lead = get_lead(lead_id)

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    updates = _payload(data)
    if not updates:
        raise HTTPException(status_code=400, detail="No update fields provided")

    return update_lead(lead, updates=updates)


@router.post("/leads/{lead_id}/notes")
def create_lead_note(
    lead_id: int,
    data: NoteCreateRequest,
    actor_role: str = Header(default="viewer", alias="X-Actor-Role"),
    actor_name: str = Header(default="anonymous", alias="X-Actor-Name"),
):
    _require_permission(actor_role, actor_name, "lead_write")

    lead = get_lead(lead_id)

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    return add_lead_note(lead, note=data.note)


@router.post("/leads/{lead_id}/crm-sync")
def crm_sync(
    lead_id: int,
    data: CRMUpdateRequest,
    actor_role: str = Header(default="viewer", alias="X-Actor-Role"),
    actor_name: str = Header(default="anonymous", alias="X-Actor-Name"),
):
    _require_permission(actor_role, actor_name, "lead_write")

    lead = get_lead(lead_id)

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    try:
        return sync_crm(lead, owner=data.owner)
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/leads/{lead_id}/draft-first-message")
def draft_first_message(
    lead_id: int,
    data: MessageDraftRequest,
    actor_role: str = Header(default="viewer", alias="X-Actor-Role"),
    actor_name: str = Header(default="anonymous", alias="X-Actor-Name"),
):
    _require_permission(actor_role, actor_name, "lead_write")

    lead = get_lead(lead_id)

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    try:
        return generate_first_message(lead, channel=data.channel)
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/leads/{lead_id}/approve-first-message")
def approve_first_message(
    lead_id: int,
    actor_role: str = Header(default="viewer", alias="X-Actor-Role"),
    actor_name: str = Header(default="anonymous", alias="X-Actor-Name"),
):
    _require_permission(actor_role, actor_name, "lead_write")

    lead = get_lead(lead_id)

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    try:
        return approve_message(lead, field_name="first_message")
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/leads/{lead_id}/mark-first-message-sent")
def send_first_message(
    lead_id: int,
    actor_role: str = Header(default="viewer", alias="X-Actor-Role"),
    actor_name: str = Header(default="anonymous", alias="X-Actor-Name"),
):
    _require_permission(actor_role, actor_name, "lead_write")

    lead = get_lead(lead_id)

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    try:
        return mark_message_sent(lead, field_name="first_message")
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/leads/{lead_id}/draft-follow-up")
def draft_follow_up(
    lead_id: int,
    actor_role: str = Header(default="viewer", alias="X-Actor-Role"),
    actor_name: str = Header(default="anonymous", alias="X-Actor-Name"),
):
    _require_permission(actor_role, actor_name, "lead_write")

    lead = get_lead(lead_id)

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    try:
        return generate_follow_up(lead)
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/leads/{lead_id}/approve-follow-up")
def approve_follow_up(
    lead_id: int,
    actor_role: str = Header(default="viewer", alias="X-Actor-Role"),
    actor_name: str = Header(default="anonymous", alias="X-Actor-Name"),
):
    _require_permission(actor_role, actor_name, "lead_write")

    lead = get_lead(lead_id)

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    try:
        return approve_message(lead, field_name="follow_up_message")
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/leads/{lead_id}/mark-follow-up-sent")
def send_follow_up(
    lead_id: int,
    actor_role: str = Header(default="viewer", alias="X-Actor-Role"),
    actor_name: str = Header(default="anonymous", alias="X-Actor-Name"),
):
    _require_permission(actor_role, actor_name, "lead_write")

    lead = get_lead(lead_id)

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    try:
        return mark_message_sent(lead, field_name="follow_up_message")
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/leads/{lead_id}/record-reply")
def save_reply(
    lead_id: int,
    data: ReplyUpdateRequest,
    actor_role: str = Header(default="viewer", alias="X-Actor-Role"),
    actor_name: str = Header(default="anonymous", alias="X-Actor-Name"),
):
    _require_permission(actor_role, actor_name, "lead_write")

    lead = get_lead(lead_id)

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    try:
        return record_reply(lead, reply_type=data.reply_type, detail=data.detail)
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
