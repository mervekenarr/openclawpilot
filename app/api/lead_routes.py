from fastapi import APIRouter, HTTPException

from app import store
from app.schemas.leads import CRMUpdateRequest, MessageDraftRequest, ReplyUpdateRequest
from app.services.openclaw_service import (
    approve_message,
    generate_first_message,
    generate_follow_up,
    get_lead,
    mark_message_sent,
    record_reply,
    sync_crm,
)


router = APIRouter(tags=["leads"])


@router.get("/leads")
def list_leads(status: str | None = None):
    if not status:
        return store.leads

    return [item for item in store.leads if item["status"] == status]


@router.get("/leads/{lead_id}")
def get_lead_detail(lead_id: int):
    lead = get_lead(lead_id)

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    return lead


@router.post("/leads/{lead_id}/crm-sync")
def crm_sync(lead_id: int, data: CRMUpdateRequest):
    lead = get_lead(lead_id)

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    return sync_crm(lead, owner=data.owner)


@router.post("/leads/{lead_id}/draft-first-message")
def draft_first_message(lead_id: int, data: MessageDraftRequest):
    lead = get_lead(lead_id)

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if lead.get("crm_status") != "synced":
        raise HTTPException(status_code=400, detail="Lead must be synced to CRM before drafting outreach")

    return generate_first_message(lead, channel=data.channel)


@router.post("/leads/{lead_id}/approve-first-message")
def approve_first_message(lead_id: int):
    lead = get_lead(lead_id)

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if not lead.get("first_message"):
        raise HTTPException(status_code=400, detail="First message draft does not exist")

    return approve_message(lead, field_name="first_message")


@router.post("/leads/{lead_id}/mark-first-message-sent")
def send_first_message(lead_id: int):
    lead = get_lead(lead_id)

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if not lead.get("first_message"):
        raise HTTPException(status_code=400, detail="First message draft does not exist")
    if lead["first_message"]["status"] != "approved":
        raise HTTPException(status_code=400, detail="First message must be approved before send")

    return mark_message_sent(lead, field_name="first_message")


@router.post("/leads/{lead_id}/draft-follow-up")
def draft_follow_up(lead_id: int):
    lead = get_lead(lead_id)

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if lead.get("outreach_status") != "awaiting_reply":
        raise HTTPException(status_code=400, detail="Follow-up can be drafted after the first message is sent")

    return generate_follow_up(lead)


@router.post("/leads/{lead_id}/approve-follow-up")
def approve_follow_up(lead_id: int):
    lead = get_lead(lead_id)

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if not lead.get("follow_up_message"):
        raise HTTPException(status_code=400, detail="Follow-up draft does not exist")

    return approve_message(lead, field_name="follow_up_message")


@router.post("/leads/{lead_id}/mark-follow-up-sent")
def send_follow_up(lead_id: int):
    lead = get_lead(lead_id)

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if not lead.get("follow_up_message"):
        raise HTTPException(status_code=400, detail="Follow-up draft does not exist")
    if lead["follow_up_message"]["status"] != "approved":
        raise HTTPException(status_code=400, detail="Follow-up must be approved before send")

    return mark_message_sent(lead, field_name="follow_up_message")


@router.post("/leads/{lead_id}/record-reply")
def save_reply(lead_id: int, data: ReplyUpdateRequest):
    lead = get_lead(lead_id)

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if lead.get("outreach_status") not in {"awaiting_reply", "follow_up_sent"}:
        raise HTTPException(status_code=400, detail="Reply can be recorded after an outreach message is sent")

    return record_reply(lead, reply_type=data.reply_type, detail=data.detail)
