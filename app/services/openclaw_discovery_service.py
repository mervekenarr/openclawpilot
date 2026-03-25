from app.adapters.company_discovery_client import CompanyDiscoveryError, search_company_candidates
from app.adapters.openclaw_client import (
    OpenClawAdapterError,
    get_runtime_info,
    plan_company_search,
    select_company_candidates,
)


class OpenClawDiscoveryError(ValueError):
    pass


def openclaw_guided_discovery_enabled() -> bool:
    runtime = get_runtime_info()
    return bool(runtime.get("agent_discovery_enabled") and runtime.get("live_calls_enabled"))


def build_openclaw_guided_candidates(keyword: str, sector: str | None, limit: int) -> list[dict]:
    plan_request = {
        "keyword": keyword,
        "sector": sector,
        "limit": limit,
        "blocked_tools": ["linkedin", "browser_automation", "live_messaging"],
        "allowed_tools": ["web_search"],
    }

    try:
        plan_result = plan_company_search(plan_request)
    except OpenClawAdapterError as exc:
        raise OpenClawDiscoveryError(str(exc)) from exc

    query_rows = list((plan_result.get("plan") or {}).get("queries") or [])
    queries = [item.get("query") for item in query_rows if (item.get("query") or "").strip()]
    if not queries:
        queries = _build_fallback_queries(keyword, sector)

    aggregated_results = []
    seen_websites = set()

    for query in queries[:3]:
        for item in search_company_candidates(query, max_results=max(limit * 4, 8)):
            website = item.get("website")
            if not website or website in seen_websites:
                continue
            seen_websites.add(website)
            aggregated_results.append(
                {
                    "candidate_id": len(aggregated_results) + 1,
                    "company_name": item["company_name"],
                    "website": item["website"],
                    "title": item.get("title"),
                    "snippet": item.get("snippet"),
                    "query": item.get("query") or query,
                    "source": "openclaw_discovery",
                }
            )

    if not aggregated_results:
        raise OpenClawDiscoveryError("OpenClaw guvenli web aramasinda uygun firma adayi bulamadi.")

    selection_request = {
        "keyword": keyword,
        "sector": sector,
        "limit": limit,
        "search_results": aggregated_results,
    }

    try:
        selection_result = select_company_candidates(selection_request)
    except OpenClawAdapterError as exc:
        raise OpenClawDiscoveryError(str(exc)) from exc

    selected_rows = list((selection_result.get("selection") or {}).get("selected_candidates") or [])
    selected_by_id = {
        row["candidate_id"]: {
            "reason": row.get("reason"),
            "confidence": row.get("confidence"),
        }
        for row in selected_rows
        if row.get("candidate_id") is not None
    }

    if not selected_by_id:
        fallback_rows = aggregated_results[:limit]
        return [
            {
                **row,
                "source": "openclaw_discovery_fallback",
                "selection_reason": "OpenClaw sorgulari ile bulunan ilk guvenli aday olarak alindi.",
                "selection_confidence": "medium",
            }
            for row in fallback_rows
        ]

    selected_candidates = []
    for row in aggregated_results:
        selection_meta = selected_by_id.get(row["candidate_id"])
        if not selection_meta:
            continue
        selected_candidates.append(
            {
                **row,
                "selection_reason": selection_meta.get("reason"),
                "selection_confidence": selection_meta.get("confidence"),
            }
        )
        if len(selected_candidates) >= limit:
            break

    if not selected_candidates:
        raise OpenClawDiscoveryError("OpenClaw firma secimi yapamadi.")

    return selected_candidates


def _build_fallback_queries(keyword: str, sector: str | None) -> list[str]:
    parts = [keyword]
    if sector:
        parts.append(sector)
    base = " ".join(part for part in parts if part).strip()
    return [
        f"{base} manufacturer company Turkey",
        f"{base} official website",
        f"{base} site:.com.tr",
    ]
