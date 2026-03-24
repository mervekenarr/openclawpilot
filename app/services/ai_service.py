from app import store
from app.adapters.openclaw_client import OpenClawAdapterError, create_enrichment_draft, get_runtime_info
from app.schemas.ai import EnrichmentDraftPayload
from app.services.openclaw_service import apply_enrichment_result, get_raw_lead


class AIDraftValidationError(ValueError):
    pass


ENRICHMENT_PREVIEW_FIELDS = [
    "company_summary",
    "recent_signal",
    "fit_reason",
    "summary",
    "priority",
    "confidence",
    "data_reliability",
    "missing_fields",
]

DECISION_MAKER_FIELDS = ["name", "title", "email", "linkedin_hint"]


def get_ai_runtime_info() -> dict:
    return get_runtime_info()


def get_ai_draft(draft_id: int) -> dict | None:
    return store.get_ai_draft(draft_id)


def build_openclaw_preview(raw_lead_id: int) -> dict:
    raw_lead = get_raw_lead(raw_lead_id)

    if not raw_lead:
        raise AIDraftValidationError("Raw lead not found")

    drafts = list_raw_lead_ai_drafts(raw_lead_id, include_archived=True)
    latest_draft = drafts[0] if drafts else None

    return {
        "runtime": get_ai_runtime_info(),
        "request_payload": build_safe_enrichment_request(raw_lead),
        "drafts_total": len(drafts),
        "latest_draft": (
            {
                **_build_draft_reference(latest_draft),
                "request_payload": latest_draft.get("request_payload", {}),
                "response_payload": latest_draft.get("response_payload", {}),
            }
            if latest_draft
            else None
        ),
    }


def list_raw_lead_ai_drafts(raw_lead_id: int, include_archived: bool = False) -> list[dict]:
    drafts = store.list_ai_drafts(
        entity_type="raw_lead",
        entity_id=raw_lead_id,
        draft_type="enrichment",
    )

    if include_archived:
        return drafts

    return [draft for draft in drafts if draft.get("status") != "archived"]


def build_raw_lead_enrichment_preview(draft: dict) -> dict:
    _validate_draft_entity(draft)
    raw_lead = get_raw_lead(draft["entity_id"])

    if not raw_lead:
        raise AIDraftValidationError("Raw lead for this draft no longer exists")

    draft_payload = _extract_draft_payload(draft)
    changes = []

    for field_name in ENRICHMENT_PREVIEW_FIELDS:
        changes.append(
            _build_change_entry(
                field=field_name,
                label=field_name.replace("_", " "),
                left_value=raw_lead.get(field_name),
                right_value=draft_payload.get(field_name),
                left_key="current_value",
                right_key="draft_value",
            )
        )

    current_decision_maker = raw_lead.get("decision_maker") or {}
    draft_decision_maker = draft_payload.get("decision_maker") or {}

    for field_name in DECISION_MAKER_FIELDS:
        changes.append(
            _build_change_entry(
                field=f"decision_maker.{field_name}",
                label=f"decision maker {field_name}",
                left_value=current_decision_maker.get(field_name),
                right_value=draft_decision_maker.get(field_name),
                left_key="current_value",
                right_key="draft_value",
            )
        )

    notes_to_add = [
        note for note in draft_payload.get("source_notes", [])
        if note not in raw_lead.get("personal_notes", [])
    ]
    changes.append(
        _build_change_entry(
            field="source_notes",
            label="source notes",
            left_value=[],
            right_value=notes_to_add,
            left_key="current_value",
            right_key="draft_value",
        )
    )

    changed_fields = [change for change in changes if change["changed"]]

    return {
        "draft_id": draft["id"],
        "entity_type": draft["entity_type"],
        "entity_id": draft["entity_id"],
        "draft_status": draft["status"],
        "changed_fields_total": len(changed_fields),
        "changes": changes,
    }


def build_raw_lead_draft_comparison(base_draft: dict, compare_draft: dict) -> dict:
    _validate_draft_entity(base_draft)
    _validate_draft_entity(compare_draft)

    if base_draft["entity_id"] != compare_draft["entity_id"]:
        raise AIDraftValidationError("Only drafts for the same raw lead can be compared")

    base_payload = _extract_draft_payload(base_draft)
    compare_payload = _extract_draft_payload(compare_draft)
    changes = []

    for field_name in ENRICHMENT_PREVIEW_FIELDS:
        changes.append(
            _build_change_entry(
                field=field_name,
                label=field_name.replace("_", " "),
                left_value=base_payload.get(field_name),
                right_value=compare_payload.get(field_name),
                left_key="base_value",
                right_key="compare_value",
            )
        )

    base_decision_maker = base_payload.get("decision_maker") or {}
    compare_decision_maker = compare_payload.get("decision_maker") or {}

    for field_name in DECISION_MAKER_FIELDS:
        changes.append(
            _build_change_entry(
                field=f"decision_maker.{field_name}",
                label=f"decision maker {field_name}",
                left_value=base_decision_maker.get(field_name),
                right_value=compare_decision_maker.get(field_name),
                left_key="base_value",
                right_key="compare_value",
            )
        )

    changes.append(
        _build_change_entry(
            field="source_notes",
            label="source notes",
            left_value=base_payload.get("source_notes", []),
            right_value=compare_payload.get("source_notes", []),
            left_key="base_value",
            right_key="compare_value",
        )
    )

    changed_fields = [change for change in changes if change["changed"]]

    return {
        "entity_type": base_draft["entity_type"],
        "entity_id": base_draft["entity_id"],
        "draft_type": base_draft["draft_type"],
        "base_draft": _build_draft_reference(base_draft),
        "compare_draft": _build_draft_reference(compare_draft),
        "changed_fields_total": len(changed_fields),
        "changes": changes,
    }


def build_safe_enrichment_request(raw_lead: dict) -> dict:
    return {
        "raw_lead_id": raw_lead["id"],
        "company_name": raw_lead["company_name"],
        "website": raw_lead["website"],
        "sector": raw_lead["sector"],
        "keyword": raw_lead["keyword"],
        "source": raw_lead["source"],
        "missing_fields": list(raw_lead.get("missing_fields", [])),
    }


def request_raw_lead_enrichment_draft(raw_lead: dict, actor_name: str) -> dict:
    _validate_raw_lead_ai_request_allowed(raw_lead)
    _supersede_pending_drafts(raw_lead["id"], actor_name)

    request_payload = build_safe_enrichment_request(raw_lead)

    try:
        adapter_result = create_enrichment_draft(request_payload)
    except OpenClawAdapterError as exc:
        raise AIDraftValidationError(str(exc)) from exc

    validated_draft = _validate_enrichment_draft_payload(adapter_result["draft"])

    current_at = store.utc_now()
    draft_record = {
        "entity_type": "raw_lead",
        "entity_id": raw_lead["id"],
        "draft_type": "enrichment",
        "provider": adapter_result["provider"],
        "status": "pending",
        "actor_name": actor_name,
        "created_at": current_at,
        "updated_at": current_at,
        "approved_at": None,
        "approved_by": None,
        "request_payload": request_payload,
        "response_payload": _build_response_payload(
            validated_draft,
            provider_mode=adapter_result.get("mode", "unknown"),
        ),
    }

    return store.create_ai_draft(draft_record)


def approve_raw_lead_enrichment_draft(draft: dict, actor_name: str) -> dict:
    _validate_draft_approval_allowed(draft)
    raw_lead = get_raw_lead(draft["entity_id"])

    if not raw_lead:
        raise AIDraftValidationError("Raw lead for this draft no longer exists")

    approved_raw_lead = apply_enrichment_result(
        raw_lead,
        _extract_draft_payload(draft),
        applied_note=f"AI enrichment draft approved by {actor_name}.",
    )

    current_at = store.utc_now()
    draft["status"] = "approved"
    draft["approved_at"] = current_at
    draft["approved_by"] = actor_name
    draft["updated_at"] = current_at
    draft["response_payload"] = _set_review_state(
        draft["response_payload"],
        status="approved",
        actor_name=actor_name,
        note="Draft manuel onayla kayda uygulandi.",
    )
    saved_draft = store.save_ai_draft(draft)

    return {
        "draft": saved_draft,
        "raw_lead": approved_raw_lead,
    }


def reject_raw_lead_enrichment_draft(draft: dict, actor_name: str, note: str | None) -> dict:
    _validate_draft_approval_allowed(draft)

    draft["status"] = "rejected"
    draft["updated_at"] = store.utc_now()
    draft["response_payload"] = _set_review_state(
        draft["response_payload"],
        status="rejected",
        actor_name=actor_name,
        note=note or "Draft kullanici tarafindan reddedildi.",
    )
    return store.save_ai_draft(draft)


def archive_raw_lead_enrichment_draft(draft: dict, actor_name: str, note: str | None) -> dict:
    _validate_draft_archive_allowed(draft)

    previous_status = draft["status"]
    draft["status"] = "archived"
    draft["updated_at"] = store.utc_now()
    draft["response_payload"] = _set_archive_state(
        draft["response_payload"],
        actor_name=actor_name,
        note=note or "Draft history listesinden arsivlendi.",
        previous_status=previous_status,
    )
    return store.save_ai_draft(draft)


def restore_raw_lead_enrichment_draft(draft: dict, actor_name: str, note: str | None) -> dict:
    _validate_draft_restore_allowed(draft)

    restored_status = _resolve_restored_status(draft)
    draft["status"] = restored_status
    draft["updated_at"] = store.utc_now()
    draft["response_payload"] = _set_restore_state(
        draft["response_payload"],
        actor_name=actor_name,
        note=note or "Draft arsivden geri alindi.",
        restored_status=restored_status,
    )
    return store.save_ai_draft(draft)


def _validate_raw_lead_ai_request_allowed(raw_lead: dict) -> None:
    if raw_lead.get("status") in {"approved", "rejected"}:
        raise AIDraftValidationError("AI draft cannot be generated for closed raw lead states")


def _validate_draft_approval_allowed(draft: dict) -> None:
    _validate_draft_entity(draft)
    if draft.get("status") != "pending":
        raise AIDraftValidationError("Only pending AI drafts can be approved")


def _validate_draft_archive_allowed(draft: dict) -> None:
    _validate_draft_entity(draft)

    if draft.get("status") == "archived":
        raise AIDraftValidationError("AI draft is already archived")

    if draft.get("status") == "pending":
        raise AIDraftValidationError("Pending AI drafts cannot be archived")


def _validate_draft_restore_allowed(draft: dict) -> None:
    _validate_draft_entity(draft)

    if draft.get("status") != "archived":
        raise AIDraftValidationError("Only archived AI drafts can be restored")


def _validate_draft_entity(draft: dict) -> None:
    if draft.get("entity_type") != "raw_lead" or draft.get("draft_type") != "enrichment":
        raise AIDraftValidationError("Only raw lead enrichment drafts can be used here")


def _supersede_pending_drafts(raw_lead_id: int, actor_name: str) -> None:
    for pending_draft in store.list_ai_drafts(
        entity_type="raw_lead",
        entity_id=raw_lead_id,
        draft_type="enrichment",
        status="pending",
    ):
        pending_draft["status"] = "superseded"
        pending_draft["updated_at"] = store.utc_now()
        pending_draft["response_payload"] = _set_review_state(
            pending_draft["response_payload"],
            status="superseded",
            actor_name=actor_name,
            note="Yeni draft olusturuldugu icin onceki pending draft supersede edildi.",
        )
        store.save_ai_draft(pending_draft)


def _validate_enrichment_draft_payload(payload: dict) -> dict:
    try:
        if hasattr(EnrichmentDraftPayload, "model_validate"):
            validated = EnrichmentDraftPayload.model_validate(payload)
            return validated.model_dump()

        validated = EnrichmentDraftPayload.parse_obj(payload)
        return validated.dict()
    except Exception as exc:
        raise AIDraftValidationError(f"AI draft payload is invalid: {exc}") from exc


def _build_response_payload(draft_payload: dict, provider_mode: str) -> dict:
    return {
        "draft": draft_payload,
        "meta": {
            "provider_mode": provider_mode,
            "review": None,
        },
    }


def _extract_draft_payload(draft: dict) -> dict:
    response_payload = draft.get("response_payload") or {}

    if "draft" in response_payload:
        return response_payload["draft"]

    return response_payload


def _set_review_state(
    response_payload: dict,
    status: str,
    actor_name: str,
    note: str,
) -> dict:
    normalized_payload = response_payload
    if "draft" not in normalized_payload:
        normalized_payload = _build_response_payload(response_payload, provider_mode="legacy")

    normalized_payload["meta"] = normalized_payload.get("meta") or {}
    normalized_payload["meta"]["review"] = {
        "status": status,
        "actor_name": actor_name,
        "note": note,
        "at": store.utc_now(),
    }
    return normalized_payload


def _set_archive_state(
    response_payload: dict,
    actor_name: str,
    note: str,
    previous_status: str,
) -> dict:
    normalized_payload = response_payload
    if "draft" not in normalized_payload:
        normalized_payload = _build_response_payload(response_payload, provider_mode="legacy")

    normalized_payload["meta"] = normalized_payload.get("meta") or {}
    normalized_payload["meta"]["archive"] = {
        "status": "archived",
        "previous_status": previous_status,
        "actor_name": actor_name,
        "note": note,
        "at": store.utc_now(),
    }
    return normalized_payload


def _set_restore_state(
    response_payload: dict,
    actor_name: str,
    note: str,
    restored_status: str,
) -> dict:
    normalized_payload = response_payload
    if "draft" not in normalized_payload:
        normalized_payload = _build_response_payload(response_payload, provider_mode="legacy")

    normalized_payload["meta"] = normalized_payload.get("meta") or {}
    normalized_payload["meta"]["restore"] = {
        "status": "restored",
        "restored_to": restored_status,
        "actor_name": actor_name,
        "note": note,
        "at": store.utc_now(),
    }
    return normalized_payload


def _normalize_preview_value(value):
    if isinstance(value, list):
        return tuple(value)
    if isinstance(value, dict):
        return tuple(sorted(value.items()))
    return value


def _resolve_restored_status(draft: dict) -> str:
    response_payload = draft.get("response_payload") or {}
    meta = response_payload.get("meta") or {}
    archive_meta = meta.get("archive") or {}
    previous_status = archive_meta.get("previous_status")

    if previous_status and previous_status != "archived":
        return previous_status

    review_meta = meta.get("review") or {}
    review_status = review_meta.get("status")

    if review_status and review_status != "pending":
        return review_status

    return "superseded"


def _build_change_entry(
    field: str,
    label: str,
    left_value,
    right_value,
    left_key: str,
    right_key: str,
) -> dict:
    is_changed = _normalize_preview_value(left_value) != _normalize_preview_value(right_value)
    return {
        "field": field,
        "label": label,
        left_key: left_value,
        right_key: right_value,
        "changed": is_changed,
    }


def _build_draft_reference(draft: dict) -> dict:
    return {
        "id": draft["id"],
        "status": draft.get("status"),
        "provider": draft.get("provider"),
        "actor_name": draft.get("actor_name"),
        "created_at": draft.get("created_at"),
        "updated_at": draft.get("updated_at"),
        "approved_at": draft.get("approved_at"),
        "approved_by": draft.get("approved_by"),
    }
