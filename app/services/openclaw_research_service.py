from copy import deepcopy

from app import store
from app.adapters.news_signal_client import search_company_news_signals
from app.adapters.openclaw_client import (
    OpenClawAdapterError,
    create_enrichment_draft,
    get_runtime_info,
    plan_research_tools,
)
from app.adapters.safe_research_client import fetch_company_website_summary
from app.schemas.ai import EnrichmentDraftPayload
from app.services import research_service


class OpenClawResearchError(ValueError):
    pass


def openclaw_guided_research_enabled() -> bool:
    runtime = get_runtime_info()
    return bool(runtime.get("agent_research_enabled") and runtime.get("live_calls_enabled"))


def build_openclaw_guided_research_result(raw_lead: dict) -> dict:
    bundle = build_openclaw_guided_research_bundle(raw_lead)
    enrichment = deepcopy(bundle["enrichment"])
    enrichment["research_bundle"] = bundle
    return enrichment


def build_openclaw_guided_research_bundle(raw_lead: dict) -> dict:
    request_payload = _build_planner_request(raw_lead)
    try:
        plan_result = plan_research_tools(request_payload)
    except OpenClawAdapterError as exc:
        raise OpenClawResearchError(str(exc)) from exc

    sources = []
    executed_tools = []

    for tool_call in (plan_result.get("plan") or {}).get("tool_calls", [])[:2]:
        tool_name = tool_call.get("tool")

        if tool_name == "website_fetch" and raw_lead.get("website"):
            snapshot = fetch_company_website_summary(
                website_url=raw_lead["website"],
                company_name=raw_lead["company_name"],
            )
            sources.append(research_service._build_website_source(raw_lead, snapshot))
            executed_tools.append(
                {
                    "tool": "website_fetch",
                    "reason": tool_call.get("reason"),
                    "status": "completed",
                    "output": {
                        "url": snapshot.get("final_url") or raw_lead.get("website"),
                        "title": snapshot.get("title"),
                        "best_summary": snapshot.get("best_summary"),
                        "text_excerpt": snapshot.get("text_excerpt"),
                        "relevance": snapshot.get("relevance"),
                    },
                }
            )

        if tool_name == "news_search":
            news_items = search_company_news_signals(
                company_name=raw_lead["company_name"],
                keyword=raw_lead.get("keyword"),
                max_results=3,
            )
            if news_items:
                for item in news_items:
                    sources.append(
                        {
                            "source_id": "news_scan",
                            "label": "Haber taramasi",
                            "status": "reviewed",
                            "risk": "low",
                            "url": item.get("url"),
                            "title": item.get("title"),
                            "snippet": item.get("snippet"),
                            "confidence": "medium",
                            "relevance": "medium",
                            "published_at": item.get("published_at"),
                        }
                    )
                executed_tools.append(
                    {
                        "tool": "news_search",
                        "reason": tool_call.get("reason"),
                        "status": "completed",
                        "output": news_items,
                    }
                )

    evidence_bundle = _build_evidence_bundle(raw_lead, sources, plan_result)
    enrichment_request = _build_synthesis_request(raw_lead, evidence_bundle)

    try:
        adapter_result = create_enrichment_draft(enrichment_request)
    except OpenClawAdapterError as exc:
        raise OpenClawResearchError(str(exc)) from exc

    enrichment = _validate_enrichment_payload(adapter_result["draft"])
    bundle = {
        "version": 1,
        "mode": "openclaw_guided",
        "built_at": store.utc_now(),
        "inputs": {
            "raw_lead_id": raw_lead["id"],
            "company_name": raw_lead["company_name"],
            "keyword": raw_lead["keyword"],
            "sector": raw_lead["sector"],
            "website": raw_lead.get("website"),
        },
        "tool_plan": plan_result.get("plan") or {},
        "tool_provider": plan_result.get("provider"),
        "tool_mode": plan_result.get("mode"),
        "executed_tools": executed_tools,
        "sources": sources,
        "evidence_summary": evidence_bundle["evidence_summary"],
        "enrichment": enrichment,
    }
    return bundle


def _build_planner_request(raw_lead: dict) -> dict:
    allowed_tools = []
    if raw_lead.get("website"):
        allowed_tools.append("website_fetch")
    if research_service._get_env_flag("SAFE_NEWS_SEARCH_ENABLED", False):
        allowed_tools.append("news_search")

    return {
        "raw_lead_id": raw_lead["id"],
        "company_name": raw_lead["company_name"],
        "website": raw_lead.get("website"),
        "sector": raw_lead["sector"],
        "keyword": raw_lead["keyword"],
        "allowed_tools": allowed_tools,
        "blocked_tools": ["linkedin", "browser_automation", "live_messaging"],
    }


def _build_evidence_bundle(raw_lead: dict, sources: list[dict], plan_result: dict) -> dict:
    reviewed_count = sum(1 for item in sources if item.get("status") == "reviewed")
    high_confidence_count = sum(1 for item in sources if item.get("confidence") == "high")
    news_count = sum(
        1
        for item in sources
        if item.get("source_id") == "news_scan" and item.get("status") == "reviewed"
    )

    return {
        "mode": "openclaw_guided",
        "built_at": store.utc_now(),
        "inputs": {
            "raw_lead_id": raw_lead["id"],
            "company_name": raw_lead["company_name"],
            "keyword": raw_lead["keyword"],
            "sector": raw_lead["sector"],
            "website": raw_lead.get("website"),
        },
        "tool_plan": plan_result.get("plan") or {},
        "evidence_summary": {
            "source_count": len(sources),
            "reviewed_count": reviewed_count,
            "high_confidence_count": high_confidence_count,
            "news_count": news_count,
        },
        "sources": sources,
    }


def _build_synthesis_request(raw_lead: dict, evidence_bundle: dict) -> dict:
    return {
        "raw_lead_id": raw_lead["id"],
        "company_name": raw_lead["company_name"],
        "website": raw_lead.get("website"),
        "sector": raw_lead["sector"],
        "keyword": raw_lead["keyword"],
        "source": raw_lead.get("source"),
        "missing_fields": list(raw_lead.get("missing_fields", [])),
        "research_bundle": {
            "mode": evidence_bundle["mode"],
            "built_at": evidence_bundle["built_at"],
            "inputs": evidence_bundle["inputs"],
            "evidence_summary": evidence_bundle["evidence_summary"],
            "sources": evidence_bundle["sources"][:6],
        },
    }


def _validate_enrichment_payload(payload: dict) -> dict:
    try:
        if hasattr(EnrichmentDraftPayload, "model_validate"):
            validated = EnrichmentDraftPayload.model_validate(payload)
            return validated.model_dump()

        validated = EnrichmentDraftPayload.parse_obj(payload)
        return validated.dict()
    except Exception as exc:
        raise OpenClawResearchError(f"OpenClaw research payload gecersiz: {exc}") from exc
