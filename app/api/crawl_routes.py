from fastapi import APIRouter, HTTPException

from app import store
from app.schemas.leads import CrawlRequest, LeadReviewRequest
from app.services.openclaw_service import enrich_lead, generate_raw_leads, get_raw_lead, review_raw_lead


router = APIRouter(tags=["crawl"])


@router.post("/crawl/start")
def start_crawl(data: CrawlRequest):
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
def list_raw_leads(status: str | None = None):
    if not status:
        return store.raw_leads

    return [item for item in store.raw_leads if item["status"] == status]


@router.post("/raw-leads/{lead_id}/research")
def research_raw_lead(lead_id: int):
    raw_lead = get_raw_lead(lead_id)

    if not raw_lead:
        raise HTTPException(status_code=404, detail="Raw lead not found")

    return enrich_lead(raw_lead)


@router.post("/raw-leads/{lead_id}/review")
def review_lead(lead_id: int, data: LeadReviewRequest):
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
