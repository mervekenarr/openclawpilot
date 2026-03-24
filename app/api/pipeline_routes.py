from fastapi import APIRouter

from app.services.openclaw_service import pipeline_summary


router = APIRouter(tags=["pipeline"])


@router.get("/pipeline/summary")
def get_pipeline_summary():
    return pipeline_summary()
