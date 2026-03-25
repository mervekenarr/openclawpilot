import json
import os
import subprocess
from urllib import error, request

from app.services.research_service import build_seed_enrichment_result


class OpenClawAdapterError(RuntimeError):
    pass


def get_runtime_info() -> dict:
    raw_mode = _get_env_value("OPENCLAW_MODE", "sandbox").lower() or "sandbox"
    mode = "sandbox" if raw_mode == "mock" else raw_mode
    channel = _get_env_value("OPENCLAW_CHANNEL", "api") or "api"
    workspace_tag = _get_env_value("OPENCLAW_WORKSPACE_TAG", "sales-pilot") or "sales-pilot"
    gateway_url = _get_env_value("OPENCLAW_GATEWAY_URL", "")
    api_key = _get_env_value("OPENCLAW_API_KEY", "")
    dry_run_only = _get_env_flag("OPENCLAW_DRY_RUN_ONLY", True)

    model_provider = _get_env_value("OPENCLAW_MODEL_PROVIDER", "none").lower() or "none"
    configured_model_name = _get_env_value("OPENCLAW_MODEL_NAME", "")
    ollama_base_url = _get_env_value("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    ollama_model = _get_env_value("OLLAMA_MODEL", configured_model_name)
    model_name = configured_model_name or ollama_model

    browser_automation_enabled = _get_env_flag("OPENCLAW_ALLOW_BROWSER_AUTOMATION", False)
    live_send_enabled = _get_env_flag("OPENCLAW_ALLOW_LIVE_SEND", False)
    agent_discovery_enabled = _get_env_flag("OPENCLAW_AGENT_DISCOVERY_ENABLED", True)
    agent_research_enabled = _get_env_flag("OPENCLAW_AGENT_RESEARCH_ENABLED", True)

    gateway_ready = bool(gateway_url and api_key)
    ollama_ready = model_provider == "ollama" and bool(ollama_base_url and ollama_model)
    can_generate_drafts = dry_run_only or (model_provider == "ollama" and ollama_ready)

    warnings = []
    if mode == "gateway" and not gateway_url:
        warnings.append("OpenClaw gateway URL eksik.")
    if mode == "gateway" and not api_key:
        warnings.append("OpenClaw API key eksik.")
    if model_provider == "ollama" and not ollama_ready:
        warnings.append("Ollama model ayari eksik.")
    if raw_mode == "mock":
        warnings.append("OPENCLAW_MODE=mock artik kullanilmiyor; sandbox olarak ele alindi.")
    if browser_automation_enabled:
        warnings.append("Browser otomasyonu acik; dikkatli kullan.")
    if live_send_enabled:
        warnings.append("Canli gonderim acik; insan onayi disina cikma.")
    if dry_run_only:
        warnings.append("Dry run acik; canli OpenClaw cagrisi yapilmayacak.")

    setup_state, recommended_next_step = _resolve_setup_state(
        mode=mode,
        dry_run_only=dry_run_only,
        gateway_ready=gateway_ready,
        model_provider=model_provider,
        ollama_ready=ollama_ready,
    )

    return {
        "provider": "openclaw",
        "mode": mode,
        "channel": channel,
        "workspace_tag": workspace_tag,
        "gateway_url": gateway_url or None,
        "gateway_configured": bool(gateway_url),
        "api_key_configured": bool(api_key),
        "gateway_ready": gateway_ready,
        "dry_run_only": dry_run_only,
        "can_generate_drafts": can_generate_drafts,
        "live_calls_enabled": model_provider == "ollama" and ollama_ready and not dry_run_only,
        "agent_discovery_enabled": agent_discovery_enabled,
        "agent_research_enabled": agent_research_enabled,
        "setup_state": setup_state,
        "recommended_next_step": recommended_next_step,
        "warnings": warnings,
        "direct_db_access": False,
        "model_provider": model_provider,
        "model_name": model_name or None,
        "ollama": {
            "configured": ollama_ready,
            "base_url": ollama_base_url if model_provider == "ollama" else None,
            "model": ollama_model if model_provider == "ollama" else None,
        },
        "safety": {
            "browser_automation_enabled": browser_automation_enabled,
            "live_send_enabled": live_send_enabled,
            "direct_db_access": False,
        },
    }


def get_ollama_probe() -> dict:
    runtime = get_runtime_info()
    ollama_runtime = runtime.get("ollama") or {}
    model_provider = runtime.get("model_provider")
    configured_model = ollama_runtime.get("model")
    base_url = ollama_runtime.get("base_url")

    if model_provider != "ollama":
        return {
            "enabled": False,
            "configured": False,
            "reachable": False,
            "model": configured_model,
            "base_url": base_url,
            "installed_models": [],
            "model_installed": False,
            "status": "disabled",
            "message": "Ollama secili provider degil.",
        }

    if not ollama_runtime.get("configured"):
        return {
            "enabled": True,
            "configured": False,
            "reachable": False,
            "model": configured_model,
            "base_url": base_url,
            "installed_models": [],
            "model_installed": False,
            "status": "config_missing",
            "message": "Ollama ayarlari eksik.",
        }

    try:
        installed_models = _fetch_ollama_tags(base_url)
    except OpenClawAdapterError as exc:
        return {
            "enabled": True,
            "configured": True,
            "reachable": False,
            "model": configured_model,
            "base_url": base_url,
            "installed_models": [],
            "model_installed": False,
            "status": "unreachable",
            "message": str(exc),
        }

    model_installed = configured_model in installed_models
    status = "ready" if model_installed else "model_missing"
    message = (
        "Ollama hazir, smoke test icin uygun."
        if model_installed
        else "Ollama acik ama secili model henuz indirilmemis."
    )

    return {
        "enabled": True,
        "configured": True,
        "reachable": True,
        "model": configured_model,
        "base_url": base_url,
        "installed_models": installed_models,
        "model_installed": model_installed,
        "status": status,
        "message": message,
    }


def create_enrichment_draft(payload: dict) -> dict:
    runtime = get_runtime_info()

    if runtime["dry_run_only"]:
        provider_label = (
            "openclaw-ollama-sandbox"
            if runtime["model_provider"] == "ollama"
            else "openclaw-sandbox"
        )
        notes = [
            "OpenClaw sandbox modunda guvenli taslak olusturuldu.",
            "Canli entegrasyon kapali; FastAPI ana kontrol siniri olarak kalir.",
        ]
        if runtime["model_provider"] == "ollama":
            notes.append("Ollama baglantisi acildiginda ayni akista canli taslak uretilir.")

        return _build_fallback_adapter_result(
            payload,
            provider=provider_label,
            mode=runtime["mode"],
            extra_notes=notes,
        )

    if runtime["model_provider"] == "ollama":
        return _build_ollama_adapter_result(payload, runtime)

    if not runtime["gateway_ready"]:
        raise OpenClawAdapterError(
            "OpenClaw gateway config eksik. OPENCLAW_GATEWAY_URL ve OPENCLAW_API_KEY ayarlarini tamamla."
        )

    raise OpenClawAdapterError(
        "Canli OpenClaw gateway cagrisi bu pilotta henuz acilmadi. Once dry run ve guvenlik onayini tamamla."
    )


def plan_research_tools(payload: dict) -> dict:
    runtime = get_runtime_info()
    allowed_tools = list(payload.get("allowed_tools") or [])

    if runtime["dry_run_only"]:
        return {
            "provider": "openclaw-sandbox",
            "mode": runtime["mode"],
            "plan": {
                "goal": "Sirket icin guvenli web arastirmasi planlandi.",
                "tool_calls": [
                    {
                        "tool": tool_name,
                        "reason": (
                            "Resmi site icerigiyle sirketin ne yaptigini ve uygunluk sinyalini dogrulamak icin."
                            if tool_name == "website_fetch"
                            else "Halka acik yeni sinyal veya duyuru aramak icin."
                        ),
                    }
                    for tool_name in allowed_tools[:2]
                ],
            },
        }

    if runtime["model_provider"] != "ollama":
        raise OpenClawAdapterError("OpenClaw arastirma plani icin aktif model provider bulunamadi.")

    prompt = _build_research_plan_prompt(payload)
    raw_response = _call_ollama_generate(
        base_url=runtime["ollama"]["base_url"],
        model=runtime["ollama"]["model"],
        prompt=prompt,
        timeout_seconds=_get_env_int("OLLAMA_TIMEOUT", 300),
    )
    parsed_plan = _extract_research_plan_payload(raw_response, allowed_tools=allowed_tools)
    return {
        "provider": "openclaw-ollama-live",
        "mode": runtime["mode"],
        "plan": parsed_plan,
    }


def plan_company_search(payload: dict) -> dict:
    runtime = get_runtime_info()

    if runtime["dry_run_only"]:
        return {
            "provider": "openclaw-sandbox",
            "mode": runtime["mode"],
            "plan": {
                "goal": "Guvenli firma aramasi icin temel sorgular olusturuldu.",
                "queries": [
                    {
                        "query": query,
                        "reason": "Anahtar kelime ve sektorle uyumlu firma adaylarini bulmak icin.",
                    }
                    for query in _build_default_discovery_queries(
                        payload.get("keyword"),
                        payload.get("sector"),
                    )[:3]
                ],
            },
        }

    if runtime["model_provider"] != "ollama":
        raise OpenClawAdapterError("OpenClaw firma arama plani icin aktif model provider bulunamadi.")

    prompt = _build_company_search_plan_prompt(payload)
    raw_response = _call_ollama_generate(
        base_url=runtime["ollama"]["base_url"],
        model=runtime["ollama"]["model"],
        prompt=prompt,
        timeout_seconds=_get_env_int("OLLAMA_TIMEOUT", 300),
    )
    parsed_plan = _extract_company_search_plan_payload(raw_response)
    return {
        "provider": "openclaw-ollama-live",
        "mode": runtime["mode"],
        "plan": parsed_plan,
    }


def select_company_candidates(payload: dict) -> dict:
    runtime = get_runtime_info()
    search_results = list(payload.get("search_results") or [])

    if runtime["dry_run_only"]:
        return {
            "provider": "openclaw-sandbox",
            "mode": runtime["mode"],
            "selection": {
                "goal": "Ilk uygun firma adaylari secildi.",
                "selected_candidates": [
                    {
                        "candidate_id": item["candidate_id"],
                        "reason": "Guvenli arama sonucunda ilk uygun aday olarak secildi.",
                        "confidence": "medium",
                    }
                    for item in search_results[: int(payload.get("limit") or 5)]
                ],
            },
        }

    if runtime["model_provider"] != "ollama":
        raise OpenClawAdapterError("OpenClaw firma secimi icin aktif model provider bulunamadi.")

    prompt = _build_company_selection_prompt(payload)
    raw_response = _call_ollama_generate(
        base_url=runtime["ollama"]["base_url"],
        model=runtime["ollama"]["model"],
        prompt=prompt,
        timeout_seconds=_get_env_int("OLLAMA_TIMEOUT", 300),
    )
    parsed_selection = _extract_company_selection_payload(
        raw_response,
        allowed_candidate_ids=[item["candidate_id"] for item in search_results],
        limit=int(payload.get("limit") or 5),
    )
    return {
        "provider": "openclaw-ollama-live",
        "mode": runtime["mode"],
        "selection": parsed_selection,
    }


def _build_fallback_adapter_result(
    payload: dict,
    provider: str,
    mode: str,
    extra_notes: list[str] | None = None,
) -> dict:
    lead_stub = {
        "id": payload["raw_lead_id"],
        "company_name": payload["company_name"],
        "keyword": payload["keyword"],
        "sector": payload["sector"],
    }
    draft = build_seed_enrichment_result(lead_stub)
    draft["source_notes"] = list(extra_notes or [])

    return {
        "provider": provider,
        "mode": mode,
        "draft": draft,
    }


def _build_ollama_adapter_result(payload: dict, runtime: dict) -> dict:
    ollama_runtime = runtime.get("ollama") or {}
    if not ollama_runtime.get("configured"):
        raise OpenClawAdapterError("Ollama ayarlari eksik.")

    prompt = _build_ollama_prompt(payload)
    raw_response = _call_ollama_generate(
        base_url=ollama_runtime.get("base_url"),
        model=ollama_runtime.get("model"),
        prompt=prompt,
        timeout_seconds=_get_env_int("OLLAMA_TIMEOUT", 300),
    )
    draft_payload = _extract_ollama_draft_payload(raw_response)
    draft_payload.setdefault("source_notes", [])
    draft_payload["source_notes"] = [
        *draft_payload["source_notes"],
        "Ollama uzerinden sanitize edilmis payload ile taslak uretildi.",
        "Taslak hala kullanici onayi bekler.",
    ][:10]

    return {
        "provider": "openclaw-ollama-live",
        "mode": runtime["mode"],
        "draft": draft_payload,
    }


def _resolve_setup_state(
    mode: str,
    dry_run_only: bool,
    gateway_ready: bool,
    model_provider: str,
    ollama_ready: bool,
) -> tuple[str, str]:
    if model_provider == "ollama" and not ollama_ready:
        return (
            "ollama_config_needed",
            "Yarin OLLAMA_BASE_URL ve OLLAMA_MODEL ayarlarini tamamla.",
        )

    if model_provider == "ollama" and dry_run_only:
        return (
            "ollama_sandbox_ready",
            "Yarin local Ollama baglantisini smoke test et; browser otomasyonu ve canli gonderim kapali kalsin.",
        )

    if model_provider == "ollama" and ollama_ready:
        return (
            "ollama_live_ready",
            "Ollama canli draft uretimine hazir. Browser otomasyonu ve canli gonderim kapali kalmali.",
        )

    if dry_run_only:
        return (
            "sandbox_ready",
            "Gateway URL ve API key ekle; sonra canli call karari ver.",
        )

    if gateway_ready:
        return (
            "configured_waiting_live",
            "Canli OpenClaw cagrisi icin ayri onay ve adapter implementasyonu ekle.",
        )

    return (
        "config_needed",
        "OPENCLAW_GATEWAY_URL ve OPENCLAW_API_KEY degerlerini tamamla.",
    )


def _fetch_ollama_tags(base_url: str | None) -> list[str]:
    if not base_url:
        raise OpenClawAdapterError("Ollama base URL eksik.")

    normalized_url = base_url.rstrip("/")
    tags_url = f"{normalized_url}/api/tags"

    try:
        with request.urlopen(tags_url, timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.URLError as exc:
        if os.name == "nt":
            payload = _call_powershell_rest(tags_url, method="GET", timeout_seconds=10)
        else:
            raise OpenClawAdapterError("Ollama ulasilamiyor.") from exc
    except TimeoutError as exc:
        raise OpenClawAdapterError("Ollama zaman asimina ugradi.") from exc
    except json.JSONDecodeError as exc:
        raise OpenClawAdapterError("Ollama cevabi okunamadi.") from exc

    models = payload.get("models") or []
    names = []
    for model in models:
        model_name = (model or {}).get("name")
        if model_name:
            names.append(model_name)

    return names


def _call_ollama_generate(
    base_url: str | None,
    model: str | None,
    prompt: str,
    timeout_seconds: int,
) -> dict:
    if not base_url:
        raise OpenClawAdapterError("Ollama base URL eksik.")
    if not model:
        raise OpenClawAdapterError("Ollama model adi eksik.")

    endpoint = f"{base_url.rstrip('/')}/api/generate"
    request_payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }
    ).encode("utf-8")
    http_request = request.Request(
        endpoint,
        data=request_payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.URLError as exc:
        if os.name == "nt":
            return _call_powershell_rest(
                endpoint,
                method="POST",
                body={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                },
                timeout_seconds=timeout_seconds,
            )
        raise OpenClawAdapterError("Ollama generate cagrisi basarisiz oldu.") from exc
    except TimeoutError as exc:
        raise OpenClawAdapterError("Ollama generate zaman asimina ugradi.") from exc
    except json.JSONDecodeError as exc:
        raise OpenClawAdapterError("Ollama generate cevabi okunamadi.") from exc


def _extract_ollama_draft_payload(response_payload: dict) -> dict:
    response_text = response_payload.get("response")
    if not response_text:
        raise OpenClawAdapterError("Ollama bos draft cevabi dondu.")

    try:
        parsed_payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise OpenClawAdapterError("Ollama JSON disi bir cevap dondu.") from exc

    if not isinstance(parsed_payload, dict):
        raise OpenClawAdapterError("Ollama draft formati gecersiz.")

    return parsed_payload


def _build_ollama_prompt(payload: dict) -> str:
    safe_payload = json.dumps(payload, ensure_ascii=True, indent=2)
    return (
        "You are preparing a structured enrichment draft for a B2B sales pilot.\n"
        "Your goal is to help a human reviewer quickly understand whether this company is worth sales follow-up.\n"
        "Use only the provided sanitized input and evidence bundle. Do not invent private, hidden, or sensitive data.\n"
        "Ignore website navigation noise, repeated menu text, generic slogans, and boilerplate unless they clearly support the sales fit.\n"
        "Focus only on what matters for outreach quality: what the company does, what public signal exists, why the lead may fit, and what is still missing.\n"
        "If a field is unknown, use null for decision maker subfields and include the gap in missing_fields.\n"
        "Keep text concise, professional, and useful for a sales operator.\n"
        "Write all prose fields in Turkish.\n"
        "The following fields must be Turkish sentences or short phrases: company_summary, recent_signal, fit_reason, summary, source_notes.\n"
        "Keep JSON keys and enum values in English exactly as requested.\n"
        "Return only valid JSON with these exact keys:\n"
        "{\n"
        '  "company_summary": string,\n'
        '  "recent_signal": string,\n'
        '  "fit_reason": string,\n'
        '  "summary": string,\n'
        '  "priority": "high"|"medium"|"low",\n'
        '  "confidence": "high"|"medium"|"low",\n'
        '  "data_reliability": "high"|"medium"|"low",\n'
        '  "decision_maker": {\n'
        '    "name": string|null,\n'
        '    "title": string|null,\n'
        '    "email": string|null,\n'
        '    "linkedin_hint": string|null\n'
        "  },\n"
        '  "missing_fields": [string],\n'
        '  "source_notes": [string]\n'
        "}\n"
        "Rules:\n"
        "- Do not fabricate a real email address.\n"
        "- company_summary should explain in one or two short Turkish sentences what the company appears to do.\n"
        "- recent_signal should mention only a concrete public signal. If none exists, say in Turkish that no concrete public signal is verified yet.\n"
        "- fit_reason should explain sales relevance in one short Turkish sentence.\n"
        "- summary should be a short sales-ready reviewer summary, not a copy of company_summary.\n"
        "- source_notes should be short Turkish evidence notes, maximum 5 items, no fluff.\n"
        "- Mention uncertainty in source_notes when inference is generic or weak.\n"
        "- If the evidence is weak, keep confidence low and avoid overclaiming.\n"
        "- Do not restate every keyword or every source line unless it materially helps the decision.\n"
        "- Do not mention LinkedIn unless it explicitly exists in the provided sanitized input.\n"
        "- Use English enum values exactly as requested.\n"
        "- Do not answer in English prose.\n"
        "- Output JSON only, no markdown.\n"
        "Sanitized input:\n"
        f"{safe_payload}\n"
    )


def _build_research_plan_prompt(payload: dict) -> str:
    safe_payload = json.dumps(payload, ensure_ascii=True, indent=2)
    return (
        "You are OpenClaw research planner for a B2B sales pilot.\n"
        "Choose only from the allowed research tools provided in the sanitized input.\n"
        "Never mention or choose LinkedIn, browser automation, private login, cookie usage, or live messaging.\n"
        "Prefer website_fetch first when an official website is present.\n"
        "Use news_search only if a recent public signal could improve the sales assessment.\n"
        "Choose at most 2 tools.\n"
        "Return JSON only with this exact shape:\n"
        "{\n"
        '  "goal": string,\n'
        '  "tool_calls": [\n'
        '    {"tool": string, "reason": string}\n'
        "  ]\n"
        "}\n"
        "Rules:\n"
        "- tool must be one of the allowed_tools values.\n"
        "- reason must be a short Turkish sentence.\n"
        "- If only one tool is enough, return one tool.\n"
        "- If no tool should run, return an empty tool_calls array.\n"
        "Sanitized input:\n"
        f"{safe_payload}\n"
    )


def _build_company_search_plan_prompt(payload: dict) -> str:
    safe_payload = json.dumps(payload, ensure_ascii=True, indent=2)
    return (
        "You are OpenClaw company discovery planner for a B2B sales pilot.\n"
        "You are not allowed to use LinkedIn, browser automation, private logins, cookies, or live messaging.\n"
        "Your job is to propose safe public web search queries that can help find official company websites related to the keyword and sector.\n"
        "Use at most 3 queries.\n"
        "Prefer official company sites, manufacturers, suppliers, and sector-specific firms.\n"
        "Avoid social media, directories without an official company domain, marketplaces, and generic blog results.\n"
        "Return JSON only with this exact shape:\n"
        "{\n"
        '  "goal": string,\n'
        '  "queries": [\n'
        '    {"query": string, "reason": string}\n'
        "  ]\n"
        "}\n"
        "Rules:\n"
        "- reason must be a short Turkish sentence.\n"
        "- query can be English or Turkish search text.\n"
        "- query must target public web search only.\n"
        "- Output JSON only, no markdown.\n"
        "Sanitized input:\n"
        f"{safe_payload}\n"
    )


def _build_company_selection_prompt(payload: dict) -> str:
    safe_payload = json.dumps(payload, ensure_ascii=True, indent=2)
    return (
        "You are OpenClaw company selector for a B2B sales pilot.\n"
        "You receive safe public web search results that were already collected by trusted backend tools.\n"
        "Select the company candidates most relevant to the requested keyword and sector.\n"
        "Prefer official company websites and ignore social networks, irrelevant domains, and weak matches.\n"
        "Return JSON only with this exact shape:\n"
        "{\n"
        '  "goal": string,\n'
        '  "selected_candidates": [\n'
        '    {"candidate_id": integer, "reason": string, "confidence": "high"|"medium"|"low"}\n'
        "  ]\n"
        "}\n"
        "Rules:\n"
        "- candidate_id must come from the provided search_results.\n"
        "- reason must be a short Turkish sentence.\n"
        "- Select at most the requested limit.\n"
        "- Ignore results that do not look like official company sites.\n"
        "- Output JSON only, no markdown.\n"
        "Sanitized input:\n"
        f"{safe_payload}\n"
    )


def _extract_research_plan_payload(response_payload: dict, allowed_tools: list[str]) -> dict:
    response_text = response_payload.get("response")
    if not response_text:
        raise OpenClawAdapterError("Ollama bos arastirma plani cevabi dondu.")

    try:
        parsed_payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise OpenClawAdapterError("Ollama arastirma plani JSON disi cevap dondu.") from exc

    if not isinstance(parsed_payload, dict):
        raise OpenClawAdapterError("Arastirma plani formati gecersiz.")

    goal = str(parsed_payload.get("goal") or "Guvenli arastirma plani olusturuldu.").strip()
    tool_calls = []

    for item in parsed_payload.get("tool_calls", []):
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("tool") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if tool_name not in allowed_tools:
            continue
        tool_calls.append(
            {
                "tool": tool_name,
                "reason": reason or "Bu kaynak satis kararini desteklemek icin secildi.",
            }
        )

    return {
        "goal": goal[:220],
        "tool_calls": tool_calls[:2],
    }


def _extract_company_search_plan_payload(response_payload: dict) -> dict:
    response_text = response_payload.get("response")
    if not response_text:
        raise OpenClawAdapterError("Ollama bos firma arama plani cevabi dondu.")

    try:
        parsed_payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise OpenClawAdapterError("Ollama firma arama plani JSON disi cevap dondu.") from exc

    if not isinstance(parsed_payload, dict):
        raise OpenClawAdapterError("Firma arama plani formati gecersiz.")

    goal = str(parsed_payload.get("goal") or "Guvenli firma arama plani olusturuldu.").strip()
    queries = []

    for item in parsed_payload.get("queries", []):
        if not isinstance(item, dict):
            continue
        query = str(item.get("query") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if len(query) < 2:
            continue
        queries.append(
            {
                "query": query[:120],
                "reason": reason or "Anahtar kelimeyle uyumlu firma adaylari icin secildi.",
            }
        )

    return {
        "goal": goal[:220],
        "queries": queries[:3],
    }


def _extract_company_selection_payload(
    response_payload: dict,
    allowed_candidate_ids: list[int],
    limit: int,
) -> dict:
    response_text = response_payload.get("response")
    if not response_text:
        raise OpenClawAdapterError("Ollama bos firma secim cevabi dondu.")

    try:
        parsed_payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise OpenClawAdapterError("Ollama firma secim cevabi JSON disi dondu.") from exc

    if not isinstance(parsed_payload, dict):
        raise OpenClawAdapterError("Firma secim formati gecersiz.")

    goal = str(parsed_payload.get("goal") or "Uygun firma adaylari secildi.").strip()
    allowed_ids = set(allowed_candidate_ids)
    selected_candidates = []

    for item in parsed_payload.get("selected_candidates", []):
        if not isinstance(item, dict):
            continue
        candidate_id = item.get("candidate_id")
        if candidate_id not in allowed_ids:
            continue
        confidence = str(item.get("confidence") or "medium").strip().lower()
        if confidence not in {"high", "medium", "low"}:
            confidence = "medium"
        selected_candidates.append(
            {
                "candidate_id": candidate_id,
                "reason": str(item.get("reason") or "OpenClaw bu sonucu uygun buldu.").strip(),
                "confidence": confidence,
            }
        )
        if len(selected_candidates) >= limit:
            break

    return {
        "goal": goal[:220],
        "selected_candidates": selected_candidates,
    }


def _build_default_discovery_queries(keyword: str | None, sector: str | None) -> list[str]:
    normalized_keyword = (keyword or "industrial supplier").strip()
    normalized_sector = (sector or "").strip()
    query_base = " ".join(part for part in [normalized_keyword, normalized_sector] if part)
    if not query_base:
        query_base = "industrial supplier"

    return [
        f"{query_base} manufacturer company Turkey",
        f"{query_base} official website",
        f"{query_base} site:.com.tr",
    ]


def _call_powershell_rest(
    url: str,
    method: str,
    body: dict | None = None,
    timeout_seconds: int = 30,
) -> dict:
    escaped_url = url.replace("'", "''")
    body_json = json.dumps(body, ensure_ascii=True) if body is not None else ""
    script_lines = [
        "$ProgressPreference = 'SilentlyContinue'",
    ]

    if body is not None:
        script_lines.extend(
            [
                "$body = @'",
                body_json,
                "'@",
                f"Invoke-RestMethod -Uri '{escaped_url}' -Method {method} -Body $body -ContentType 'application/json' -TimeoutSec {timeout_seconds} | ConvertTo-Json -Depth 20",
            ]
        )
    else:
        script_lines.append(
            f"Invoke-RestMethod -Uri '{escaped_url}' -Method {method} -TimeoutSec {timeout_seconds} | ConvertTo-Json -Depth 20"
        )

    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "\n".join(script_lines)],
            capture_output=True,
            text=True,
            timeout=timeout_seconds + 5,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise OpenClawAdapterError("Ollama PowerShell cagrisi basarisiz oldu.") from exc
    except subprocess.TimeoutExpired as exc:
        raise OpenClawAdapterError("Ollama PowerShell cagrisi zaman asimina ugradi.") from exc

    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise OpenClawAdapterError("Ollama PowerShell cevabi JSON degildi.") from exc


def _get_env_value(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or default).strip()


def _get_env_flag(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)

    if raw_value is None:
        return default

    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _get_env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        return int(raw_value.strip())
    except ValueError:
        return default
