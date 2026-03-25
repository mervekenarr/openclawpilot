from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.ai_routes import router as ai_router
from app.api.crawl_routes import router as crawl_router
from app.api.keyword_routes import router as keyword_router
from app.api.lead_routes import router as lead_router
from app.api.pipeline_routes import router as pipeline_router
from app.api.system_routes import router as system_router
from app.env_loader import load_env_file
from app import store


load_env_file()

app = FastAPI(
    title="OpenClaw Pilot API",
    version="0.2.0",
    description="Sales pilot with safe web research, review, outreach, and CRM steps.",
)

base_dir = Path(__file__).resolve().parent
ui_dir = base_dir / "ui"

app.include_router(keyword_router)
app.include_router(crawl_router)
app.include_router(ai_router)
app.include_router(lead_router)
app.include_router(pipeline_router)
app.include_router(system_router)
app.mount("/dashboard-assets", StaticFiles(directory=ui_dir), name="dashboard-assets")


@app.on_event("startup")
def on_startup():
    store.init_db()


@app.get("/")
def read_root():
    return {
        "message": "OpenClaw Pilot API is running.",
        "docs": "/docs",
        "dashboard": "/dashboard",
    }


@app.get("/dashboard", include_in_schema=False)
def read_dashboard():
    return FileResponse(ui_dir / "index.html")
