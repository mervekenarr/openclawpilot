from copy import deepcopy

from app import store


COMPANY_ROOTS = [
    "Atlas",
    "Nova",
    "Meridyen",
    "Pioneer",
    "Orbit",
    "Veri",
    "Mikro",
    "Zenith",
]

COMPANY_SUFFIXES = [
    "Metal",
    "Otomasyon",
    "Makina",
    "Lojistik",
    "Teknik",
    "Endustri",
    "Yazilim",
    "Dis Ticaret",
]

SOURCES = [
    "sector_directory",
    "company_website",
    "news_scan",
    "public_registry",
]

RECENT_SIGNALS = [
    "kapasite artisi sinyali veriyor",
    "ihracat odakli buyume mesaji paylasmis",
    "yeni hat yatirimi hakkinda yayin yapmis",
    "operasyonel verimlilik odaqli bir donemden geciyor",
]

FIT_REASONS = [
    "ekibin maliyet avantaji odakli bir teklif acisina ihtiyaci olabilir",
    "surec standardizasyonu ve operasyon hizi bu firma icin kritik gorunuyor",
    "B2B satin alma akisina uygun bir karar yapisi goruluyor",
    "yeni yatirim donemi, dis destekli cozum ihtimalini arttiriyor",
]

SUMMARIES = [
    "Ilk temas icin uygun gorunen bir aday.",
    "Kisa surede geri donus alinabilecek bir profil sunuyor.",
    "Satis ekibinin onceliklendirebilecegi bir lead gorunuyor.",
    "Dogru mesajla toplantiya donme ihtimali tasiyan bir hesap.",
]

ROLE_TITLES = [
    "Satin Alma Muduru",
    "Operasyon Direktoru",
    "Genel Mudur",
    "CEO",
]

FIRST_NAMES = [
    "Mert",
    "Ece",
    "Can",
    "Selin",
    "Deniz",
    "Bora",
    "Irem",
    "Yigit",
]

LAST_NAMES = [
    "Kaya",
    "Yildiz",
    "Arslan",
    "Demir",
    "Aydin",
    "Celik",
    "Sahin",
    "Kurt",
]

TERMINAL_LEAD_STATUSES = {
    "meeting_requested",
    "closed_negative",
}


class WorkflowValidationError(ValueError):
    pass


def _pick(values: list[str], seed: int) -> str:
    return values[seed % len(values)]


def _slugify(value: str) -> str:
    return (
        value.lower()
        .replace(" ", "")
        .replace(".", "")
        .replace(",", "")
        .replace("&", "and")
    )


def _quality_from_missing(missing_fields: list[str]) -> str:
    if not missing_fields:
        return "high"
    if len(missing_fields) == 1:
        return "medium"
    return "low"


def _normalize_owner(owner: str | None) -> str | None:
    if owner is None:
        return None

    normalized = owner.strip()
    return normalized or None


def _ensure_lead_is_not_terminal(lead: dict) -> None:
    if lead.get("status") in TERMINAL_LEAD_STATUSES:
        raise WorkflowValidationError("Closed leads cannot continue in the outreach workflow")


def _resolve_sales_owner(lead: dict, owner: str | None = None) -> str:
    resolved_owner = _normalize_owner(owner) or _normalize_owner(lead.get("sales_owner"))

    if not resolved_owner:
        raise WorkflowValidationError("Sales owner is required before this workflow step")

    return resolved_owner


def _validate_crm_sync_allowed(lead: dict, owner: str | None = None) -> str:
    _ensure_lead_is_not_terminal(lead)

    if lead.get("crm_status") == "synced":
        raise WorkflowValidationError("Lead is already synced to CRM")
    if lead.get("status") != "approved":
        raise WorkflowValidationError("Only approved leads can be synced to CRM")

    return _resolve_sales_owner(lead, owner)


def _validate_first_message_draft_allowed(lead: dict) -> None:
    _ensure_lead_is_not_terminal(lead)
    _resolve_sales_owner(lead)

    if lead.get("crm_status") != "synced":
        raise WorkflowValidationError("Lead must be synced to CRM before drafting outreach")
    if lead.get("outreach_status") not in {"not_started", "draft_ready"}:
        raise WorkflowValidationError("First message can only be drafted before outreach starts")

    first_message = lead.get("first_message")
    if first_message and first_message.get("status") in {"approved", "sent"}:
        raise WorkflowValidationError("First message cannot be regenerated after approval or send")


def _validate_follow_up_draft_allowed(lead: dict) -> None:
    _ensure_lead_is_not_terminal(lead)
    _resolve_sales_owner(lead)

    if lead.get("outreach_status") not in {"awaiting_reply", "follow_up_due", "follow_up_draft_ready"}:
        raise WorkflowValidationError("Follow-up can be drafted after outreach is awaiting a reply")
    if not lead.get("first_message") or lead["first_message"].get("status") != "sent":
        raise WorkflowValidationError("First message must be sent before drafting a follow-up")

    follow_up_message = lead.get("follow_up_message")
    if follow_up_message and follow_up_message.get("status") in {"approved", "sent"}:
        raise WorkflowValidationError("Follow-up cannot be regenerated after approval or send")


def _validate_message_approval_allowed(lead: dict, field_name: str) -> None:
    _ensure_lead_is_not_terminal(lead)

    message = lead.get(field_name)
    if not message:
        label = "Follow-up" if field_name == "follow_up_message" else "First message"
        raise WorkflowValidationError(f"{label} draft does not exist")
    if message.get("status") != "draft":
        raise WorkflowValidationError("Only draft messages can be approved")


def _validate_message_send_allowed(lead: dict, field_name: str) -> None:
    _ensure_lead_is_not_terminal(lead)

    message = lead.get(field_name)
    if not message:
        label = "Follow-up" if field_name == "follow_up_message" else "First message"
        raise WorkflowValidationError(f"{label} draft does not exist")
    if message.get("status") != "approved":
        raise WorkflowValidationError("Only approved messages can be sent")


def _validate_reply_record_allowed(lead: dict) -> None:
    _ensure_lead_is_not_terminal(lead)

    if lead.get("outreach_status") not in {"awaiting_reply", "follow_up_sent"}:
        raise WorkflowValidationError("Reply can be recorded after an outreach message is sent")


def get_raw_lead(lead_id: int) -> dict | None:
    return store.get_raw_lead(lead_id)


def get_lead(lead_id: int) -> dict | None:
    return store.get_lead(lead_id)


def update_raw_lead(raw_lead: dict, updates: dict) -> dict:
    editable_fields = [
        "priority",
        "confidence",
        "review_note",
        "summary",
        "fit_reason",
        "company_summary",
    ]
    current_at = store.utc_now()
    changed_fields = []

    for field_name in editable_fields:
        if field_name in updates:
            raw_lead[field_name] = updates[field_name]
            changed_fields.append(field_name)

    if not changed_fields:
        return raw_lead

    raw_lead["updated_at"] = current_at
    raw_lead.setdefault("personal_notes", []).append(
        f"[{current_at}] Kayit guncellendi: {', '.join(changed_fields)}"
    )
    return store.save_raw_lead(raw_lead)


def add_raw_lead_note(raw_lead: dict, note: str) -> dict:
    current_at = store.utc_now()
    raw_lead.setdefault("personal_notes", []).append(f"[{current_at}] {note}")
    raw_lead["updated_at"] = current_at
    return store.save_raw_lead(raw_lead)


def update_lead(lead: dict, updates: dict) -> dict:
    editable_fields = [
        "sales_owner",
        "priority",
        "confidence",
        "summary",
        "fit_reason",
    ]
    current_at = store.utc_now()
    changed_fields = []

    for field_name in editable_fields:
        if field_name in updates:
            lead[field_name] = updates[field_name]
            changed_fields.append(field_name)

    if not changed_fields:
        return lead

    if lead.get("crm_record") is not None and "sales_owner" in updates:
        lead["crm_record"]["owner"] = lead["sales_owner"]

    lead.setdefault("activity_log", []).append(
        {
            "type": "lead_updated",
            "note": f"Alanlar guncellendi: {', '.join(changed_fields)}",
            "at": current_at,
        }
    )
    return store.save_lead(lead)


def add_lead_note(lead: dict, note: str) -> dict:
    lead.setdefault("activity_log", []).append(
        {
            "type": "user_note",
            "note": note,
            "at": store.utc_now(),
        }
    )
    return store.save_lead(lead)


def build_raw_lead_timeline(raw_lead: dict) -> list[dict]:
    entries = [
        {
            "type": "created",
            "note": "Raw lead olusturuldu.",
            "at": raw_lead["created_at"],
        }
    ]

    if raw_lead.get("research_status") == "completed":
        entries.append(
            {
                "type": "research_completed",
                "note": "Arastirma ve zenginlestirme tamamlandi.",
                "at": raw_lead.get("updated_at") or raw_lead["created_at"],
            }
        )

    if raw_lead.get("reviewed_at"):
        entries.append(
            {
                "type": "reviewed",
                "note": raw_lead.get("review_note") or f"Raw lead durumu: {raw_lead['status']}",
                "at": raw_lead["reviewed_at"],
            }
        )

    for note in raw_lead.get("personal_notes", []):
        parsed_at, parsed_note = _extract_timestamped_note(note)
        entries.append(
            {
                "type": "note",
                "note": parsed_note,
                "at": parsed_at or raw_lead.get("updated_at") or raw_lead["created_at"],
            }
        )

    return sorted(entries, key=lambda entry: entry["at"] or "", reverse=True)


def build_lead_timeline(lead: dict) -> list[dict]:
    entries = [
        {
            "type": "created",
            "note": "Lead olusturuldu.",
            "at": lead["created_at"],
        }
    ]

    for entry in lead.get("activity_log", []):
        entries.append(
            {
                "type": entry.get("type", "activity"),
                "note": entry.get("note", "Lead aktivitesi kaydedildi."),
                "at": entry.get("at") or lead["created_at"],
            }
        )

    return sorted(entries, key=lambda entry: entry["at"] or "", reverse=True)


def generate_raw_leads(keyword: str, sector: str | None, limit: int) -> list[dict]:
    normalized_sector = sector or keyword.title()
    generated_leads = []

    for offset in range(limit):
        raw_lead_id = store.next_raw_lead_id()
        seed = raw_lead_id + len(keyword) + offset
        company_name = f"{_pick(COMPANY_ROOTS, seed)} {_pick(COMPANY_SUFFIXES, seed + 1)}"

        lead = {
            "keyword": keyword,
            "sector": normalized_sector,
            "company_name": company_name,
            "website": f"https://www.{_slugify(company_name)}.com",
            "source": _pick(SOURCES, seed + 2),
            "status": "new",
            "research_status": "pending",
            "created_at": store.utc_now(),
            "updated_at": None,
            "reviewed_at": None,
            "review_note": None,
            "company_summary": None,
            "recent_signal": None,
            "fit_reason": None,
            "summary": None,
            "priority": None,
            "confidence": None,
            "data_reliability": None,
            "decision_maker": None,
            "missing_fields": [],
            "personal_notes": [],
        }

        generated_leads.append(store.create_raw_lead(lead))

    return generated_leads


def build_mock_enrichment_result(raw_lead: dict) -> dict:
    seed = raw_lead["id"] + len(raw_lead["company_name"]) + len(raw_lead["keyword"])
    contact_name = f"{_pick(FIRST_NAMES, seed)} {_pick(LAST_NAMES, seed + 2)}"
    email_local = contact_name.lower().replace(" ", ".")
    company_slug = _slugify(raw_lead["company_name"])

    decision_maker = {
        "name": contact_name,
        "title": _pick(ROLE_TITLES, seed + 1),
        "email": f"{email_local}@{company_slug}.com",
        "linkedin_hint": f"https://linkedin.com/in/{email_local}",
    }

    missing_fields = []
    if raw_lead["id"] % 3 == 0:
        decision_maker["email"] = None
        missing_fields.append("contact_email")
    if raw_lead["id"] % 4 == 0:
        decision_maker["linkedin_hint"] = None
        missing_fields.append("linkedin_profile")
    if raw_lead["id"] % 5 == 0:
        decision_maker["name"] = None
        missing_fields.append("decision_maker_name")

    quality = _quality_from_missing(missing_fields)
    confidence = "high" if quality == "high" else "medium" if quality == "medium" else "low"
    priority = "high" if quality == "high" else "medium" if quality == "medium" else "low"

    return {
        "decision_maker": decision_maker,
        "company_summary": (
            f"{raw_lead['company_name']} {raw_lead['sector']} alaninda aktif gorunen bir firma."
        ),
        "recent_signal": _pick(RECENT_SIGNALS, seed + 3),
        "fit_reason": _pick(FIT_REASONS, seed + 4),
        "summary": _pick(SUMMARIES, seed + 5),
        "priority": priority,
        "confidence": confidence,
        "data_reliability": quality,
        "missing_fields": missing_fields,
        "source_notes": [
            f"{raw_lead['sector']} keyword seti ile uyumlu bulundu.",
            "Ilk temas oncesi insan onayi beklenmeli.",
        ],
    }


def apply_enrichment_result(
    raw_lead: dict,
    enrichment: dict,
    applied_note: str | None = None,
) -> dict:
    current_at = store.utc_now()
    existing_notes = list(raw_lead.get("personal_notes", []))
    source_notes = list(enrichment.get("source_notes", []))

    if applied_note:
        source_notes.append(applied_note)

    raw_lead.update(
        {
            "research_status": "completed",
            "status": "needs_review",
            "decision_maker": deepcopy(enrichment.get("decision_maker", {})),
            "company_summary": enrichment.get("company_summary"),
            "recent_signal": enrichment.get("recent_signal"),
            "fit_reason": enrichment.get("fit_reason"),
            "summary": enrichment.get("summary"),
            "priority": enrichment.get("priority"),
            "confidence": enrichment.get("confidence"),
            "data_reliability": enrichment.get("data_reliability"),
            "missing_fields": deepcopy(enrichment.get("missing_fields", [])),
            "personal_notes": existing_notes + source_notes,
            "updated_at": current_at,
        }
    )

    return store.save_raw_lead(raw_lead)


def enrich_lead(raw_lead: dict) -> dict:
    enrichment = build_mock_enrichment_result(raw_lead)
    return apply_enrichment_result(
        raw_lead,
        enrichment,
        applied_note="Mock research sonucu kayda uygulandi.",
    )


def approve_raw_lead(raw_lead: dict, reviewer_note: str | None) -> tuple[dict, dict]:
    raw_lead["status"] = "approved"
    raw_lead["review_note"] = reviewer_note
    raw_lead["reviewed_at"] = store.utc_now()
    saved_raw_lead = store.save_raw_lead(raw_lead)

    lead = {
        "raw_lead_id": saved_raw_lead["id"],
        "company_name": saved_raw_lead["company_name"],
        "keyword": saved_raw_lead["keyword"],
        "sector": saved_raw_lead["sector"],
        "website": saved_raw_lead["website"],
        "decision_maker": deepcopy(saved_raw_lead.get("decision_maker", {})),
        "company_summary": saved_raw_lead.get("company_summary"),
        "recent_signal": saved_raw_lead.get("recent_signal"),
        "fit_reason": saved_raw_lead.get("fit_reason"),
        "summary": saved_raw_lead.get("summary"),
        "priority": saved_raw_lead.get("priority"),
        "confidence": saved_raw_lead.get("confidence"),
        "data_reliability": saved_raw_lead.get("data_reliability"),
        "missing_fields": deepcopy(saved_raw_lead.get("missing_fields", [])),
        "status": "approved",
        "crm_status": "pending",
        "outreach_status": "not_started",
        "first_message": None,
        "follow_up_message": None,
        "crm_record": None,
        "last_reply": None,
        "sales_owner": None,
        "created_at": store.utc_now(),
        "activity_log": [
            {
                "type": "approved",
                "note": reviewer_note or "Lead kullanici tarafindan onaylandi.",
                "at": store.utc_now(),
            }
        ],
    }

    saved_lead = store.create_lead(lead)
    return saved_raw_lead, saved_lead


def review_raw_lead(raw_lead: dict, action: str, reviewer_note: str | None) -> dict:
    raw_lead["review_note"] = reviewer_note
    raw_lead["reviewed_at"] = store.utc_now()

    if action == "approve":
        saved_raw_lead, lead = approve_raw_lead(raw_lead, reviewer_note)
        return {"raw_lead": saved_raw_lead, "lead": lead}

    status_map = {
        "reject": "rejected",
        "hold": "on_hold",
        "revise": "needs_revision",
    }
    raw_lead["status"] = status_map[action]
    raw_lead["updated_at"] = store.utc_now()
    return {"raw_lead": store.save_raw_lead(raw_lead)}


def sync_crm(lead: dict, owner: str | None) -> dict:
    resolved_owner = _validate_crm_sync_allowed(lead, owner)

    lead["crm_status"] = "synced"
    lead["status"] = "sales_ready"
    lead["sales_owner"] = resolved_owner
    lead["crm_record"] = {
        "pipeline_stage": "sales_ready",
        "owner": resolved_owner,
        "synced_at": store.utc_now(),
    }
    lead["activity_log"].append(
        {
            "type": "crm_sync",
            "note": f"Lead CRM'e kaydedildi. Owner: {lead['sales_owner']}",
            "at": store.utc_now(),
        }
    )
    return store.save_lead(lead)


def generate_first_message(lead: dict, channel: str) -> dict:
    _validate_first_message_draft_allowed(lead)

    contact_name = lead.get("decision_maker", {}).get("name") or "merhaba"
    company_name = lead["company_name"]
    recent_signal = lead.get("recent_signal", "guncel bir hareketlilik gosteriyor")
    fit_reason = lead.get("fit_reason", "ek bir arastirmaya deger")

    body = (
        f"Merhaba {contact_name},\n\n"
        f"{company_name} icin yaptigimiz arastirmada ekibinizin {recent_signal} goruldu. "
        f"Bu nedenle {fit_reason} diye dusunduk.\n\n"
        "Uygun gorurseniz 15 dakikalik bir gorusmede nasil katki sunabilecegimizi paylasmak isterim.\n\n"
        "Selamlar"
    )

    lead["first_message"] = {
        "channel": channel,
        "subject": f"{company_name} icin kisa bir gorusme onerisi",
        "body": body,
        "status": "draft",
        "generated_at": store.utc_now(),
    }
    lead["status"] = "draft_ready"
    lead["outreach_status"] = "draft_ready"
    lead["activity_log"].append(
        {
            "type": "first_message_drafted",
            "note": f"Ilk temas mesaji {channel} icin taslak olarak hazirlandi.",
            "at": store.utc_now(),
        }
    )
    return store.save_lead(lead)


def approve_message(lead: dict, field_name: str) -> dict:
    _validate_message_approval_allowed(lead, field_name)

    lead[field_name]["status"] = "approved"
    lead[field_name]["approved_at"] = store.utc_now()
    lead["status"] = "ready_to_send"
    lead["outreach_status"] = "approved_to_send"
    lead["activity_log"].append(
        {
            "type": f"{field_name}_approved",
            "note": "Taslak kullanici tarafindan onaylandi.",
            "at": store.utc_now(),
        }
    )
    return store.save_lead(lead)


def mark_message_sent(lead: dict, field_name: str) -> dict:
    _validate_message_send_allowed(lead, field_name)

    lead[field_name]["status"] = "sent"
    lead[field_name]["sent_at"] = store.utc_now()

    if field_name == "first_message":
        lead["status"] = "awaiting_reply"
        lead["outreach_status"] = "awaiting_reply"
        note = "Ilk mesaj gonderildi."
    else:
        lead["status"] = "follow_up_sent"
        lead["outreach_status"] = "follow_up_sent"
        note = "Takip mesaji gonderildi."

    lead["activity_log"].append(
        {
            "type": f"{field_name}_sent",
            "note": note,
            "at": store.utc_now(),
        }
    )
    return store.save_lead(lead)


def generate_follow_up(lead: dict) -> dict:
    _validate_follow_up_draft_allowed(lead)

    company_name = lead["company_name"]
    contact_name = lead.get("decision_maker", {}).get("name") or "merhaba"

    body = (
        f"Merhaba {contact_name},\n\n"
        f"{company_name} ile ilgili onceki notumu tekrar paylasmak istedim. "
        "Uygun oldugunuzda kisa bir gorusme plani yapabiliriz.\n\n"
        "Tesekkurler"
    )

    lead["follow_up_message"] = {
        "channel": (lead.get("first_message") or {}).get("channel", "email"),
        "subject": f"{company_name} icin kisa takip notu",
        "body": body,
        "status": "draft",
        "generated_at": store.utc_now(),
    }
    lead["status"] = "follow_up_draft_ready"
    lead["outreach_status"] = "follow_up_draft_ready"
    lead["activity_log"].append(
        {
            "type": "follow_up_drafted",
            "note": "Takip mesaji taslagi olusturuldu.",
            "at": store.utc_now(),
        }
    )
    return store.save_lead(lead)


def record_reply(lead: dict, reply_type: str, detail: str | None) -> dict:
    _validate_reply_record_allowed(lead)

    status_map = {
        "positive": "reply_received",
        "meeting_request": "meeting_requested",
        "negative": "closed_negative",
        "needs_follow_up": "follow_up_due",
    }

    lead["status"] = status_map[reply_type]
    lead["outreach_status"] = status_map[reply_type]
    lead["crm_status"] = status_map[reply_type]
    lead["last_reply"] = {
        "type": reply_type,
        "detail": detail,
        "recorded_at": store.utc_now(),
    }
    lead["activity_log"].append(
        {
            "type": "reply_recorded",
            "note": detail or f"Musteri yaniti kaydedildi: {reply_type}",
            "at": store.utc_now(),
        }
    )
    return store.save_lead(lead)


def pipeline_summary() -> dict:
    return store.get_pipeline_summary()


def _extract_timestamped_note(note: str) -> tuple[str | None, str]:
    if note.startswith("[") and "] " in note:
        timestamp, body = note[1:].split("] ", 1)
        return timestamp, body

    return None, note
