import os

from app.services.openclaw_service import build_mock_enrichment_result


class OpenClawAdapterError(RuntimeError):
    pass


def get_runtime_info() -> dict:
    mode = _get_env_value("OPENCLAW_MODE", "mock").lower() or "mock"
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

    gateway_ready = bool(gateway_url and api_key)
    ollama_ready = model_provider == "ollama" and bool(ollama_base_url and ollama_model)
    can_generate_drafts = mode == "mock" or dry_run_only

    warnings = []
    if mode == "gateway" and not gateway_url:
        warnings.append("OpenClaw gateway URL eksik.")
    if mode == "gateway" and not api_key:
        warnings.append("OpenClaw API key eksik.")
    if model_provider == "ollama" and not ollama_ready:
        warnings.append("Ollama model ayari eksik.")
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
        "live_calls_enabled": False,
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


def create_enrichment_draft(payload: dict) -> dict:
    runtime = get_runtime_info()

    if runtime["mode"] == "mock":
        return _build_mock_adapter_result(
            payload,
            provider="openclaw-mock",
            mode=runtime["mode"],
            extra_notes=[
                "OpenClaw adapter mock modda taslak uretildi.",
                "Taslak onaylanmadan raw lead kaydi degismez.",
            ],
        )

    if runtime["dry_run_only"]:
        provider_label = (
            "openclaw-ollama-sandbox"
            if runtime["model_provider"] == "ollama"
            else f"openclaw-{runtime['mode']}"
        )
        notes = [
            "OpenClaw dry run modunda request/response sandbox olarak simule edildi.",
            "Canli entegrasyon kapali; FastAPI hala ana kontrol siniri.",
        ]
        if runtime["model_provider"] == "ollama":
            notes.append("Yarin lokal Ollama modeli baglandiginda ilk smoke test burada yapilacak.")

        return _build_mock_adapter_result(
            payload,
            provider=provider_label,
            mode=runtime["mode"],
            extra_notes=notes,
        )

    if not runtime["gateway_ready"]:
        raise OpenClawAdapterError(
            "OpenClaw gateway config eksik. OPENCLAW_GATEWAY_URL ve OPENCLAW_API_KEY ayarlarini tamamla."
        )

    raise OpenClawAdapterError(
        "Canli OpenClaw gateway cagrisi bu pilotta henuz acilmadi. Once dry run ve guvenlik onayini tamamla."
    )


def _build_mock_adapter_result(
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
    draft = build_mock_enrichment_result(lead_stub)
    draft["source_notes"] = list(extra_notes or [])

    return {
        "provider": provider,
        "mode": mode,
        "draft": draft,
    }


def _resolve_setup_state(
    mode: str,
    dry_run_only: bool,
    gateway_ready: bool,
    model_provider: str,
    ollama_ready: bool,
) -> tuple[str, str]:
    if mode == "mock":
        return (
            "mock_ready",
            "OPENCLAW_MODE=sandbox ile guvenli dry run kurulumuna gec.",
        )

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


def _get_env_value(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or default).strip()


def _get_env_flag(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)

    if raw_value is None:
        return default

    return raw_value.strip().lower() in {"1", "true", "yes", "on"}
