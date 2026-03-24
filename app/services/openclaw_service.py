from collections import Counter
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


def get_raw_lead(lead_id: int) -> dict | None:
    return next((item for item in store.raw_leads if item["id"] == lead_id), None)


def get_lead(lead_id: int) -> dict | None:
    return next((item for item in store.leads if item["id"] == lead_id), None)


def generate_raw_leads(keyword: str, sector: str | None, limit: int) -> list[dict]:
    normalized_sector = sector or keyword.title()
    generated_leads = []

    for offset in range(limit):
        raw_lead_id = store.next_id("raw_lead")
        seed = raw_lead_id + len(keyword) + offset
        company_name = f"{_pick(COMPANY_ROOTS, seed)} {_pick(COMPANY_SUFFIXES, seed + 1)}"

        lead = {
            "id": raw_lead_id,
            "keyword": keyword,
            "sector": normalized_sector,
            "company_name": company_name,
            "website": f"https://www.{_slugify(company_name)}.com",
            "source": _pick(SOURCES, seed + 2),
            "status": "new",
            "research_status": "pending",
            "created_at": store.utc_now(),
        }

        store.raw_leads.append(lead)
        generated_leads.append(lead)

    return generated_leads


def enrich_lead(raw_lead: dict) -> dict:
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

    raw_lead.update(
        {
            "research_status": "completed",
            "status": "needs_review",
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
            "personal_notes": [
                f"{raw_lead['sector']} keyword seti ile uyumlu bulundu.",
                "Ilk temas oncesi insan onayi beklenmeli.",
            ],
            "updated_at": store.utc_now(),
        }
    )

    return raw_lead


def approve_raw_lead(raw_lead: dict, reviewer_note: str | None) -> dict:
    lead_id = store.next_id("lead")
    raw_lead["status"] = "approved"
    raw_lead["review_note"] = reviewer_note
    raw_lead["reviewed_at"] = store.utc_now()

    lead = {
        "id": lead_id,
        "raw_lead_id": raw_lead["id"],
        "company_name": raw_lead["company_name"],
        "keyword": raw_lead["keyword"],
        "sector": raw_lead["sector"],
        "website": raw_lead["website"],
        "decision_maker": deepcopy(raw_lead.get("decision_maker", {})),
        "company_summary": raw_lead.get("company_summary"),
        "recent_signal": raw_lead.get("recent_signal"),
        "fit_reason": raw_lead.get("fit_reason"),
        "summary": raw_lead.get("summary"),
        "priority": raw_lead.get("priority"),
        "confidence": raw_lead.get("confidence"),
        "data_reliability": raw_lead.get("data_reliability"),
        "missing_fields": deepcopy(raw_lead.get("missing_fields", [])),
        "status": "approved",
        "crm_status": "pending",
        "outreach_status": "not_started",
        "first_message": None,
        "follow_up_message": None,
        "created_at": store.utc_now(),
        "activity_log": [
            {
                "type": "approved",
                "note": reviewer_note or "Lead kullanici tarafindan onaylandi.",
                "at": store.utc_now(),
            }
        ],
    }

    store.leads.append(lead)
    return lead


def review_raw_lead(raw_lead: dict, action: str, reviewer_note: str | None) -> dict:
    raw_lead["review_note"] = reviewer_note
    raw_lead["reviewed_at"] = store.utc_now()

    if action == "approve":
        lead = approve_raw_lead(raw_lead, reviewer_note)
        return {"raw_lead": raw_lead, "lead": lead}

    status_map = {
        "reject": "rejected",
        "hold": "on_hold",
        "revise": "needs_revision",
    }
    raw_lead["status"] = status_map[action]
    return {"raw_lead": raw_lead}


def sync_crm(lead: dict, owner: str | None) -> dict:
    lead["crm_status"] = "synced"
    lead["status"] = "sales_ready"
    lead["sales_owner"] = owner or "unassigned"
    lead["crm_record"] = {
        "pipeline_stage": "sales_ready",
        "synced_at": store.utc_now(),
    }
    lead["activity_log"].append(
        {
            "type": "crm_sync",
            "note": f"Lead CRM'e kaydedildi. Owner: {lead['sales_owner']}",
            "at": store.utc_now(),
        }
    )
    return lead


def generate_first_message(lead: dict, channel: str) -> dict:
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
    return lead


def approve_message(lead: dict, field_name: str) -> dict:
    if not lead.get(field_name):
        return lead

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
    return lead


def mark_message_sent(lead: dict, field_name: str) -> dict:
    if not lead.get(field_name):
        return lead

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
    return lead


def generate_follow_up(lead: dict) -> dict:
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
    return lead


def record_reply(lead: dict, reply_type: str, detail: str | None) -> dict:
    status_map = {
        "positive": "reply_received",
        "meeting_request": "meeting_requested",
        "negative": "closed_negative",
        "needs_follow_up": "follow_up_due",
    }
    crm_stage_map = {
        "positive": "reply_received",
        "meeting_request": "meeting_requested",
        "negative": "closed_negative",
        "needs_follow_up": "follow_up_due",
    }

    lead["status"] = status_map[reply_type]
    lead["outreach_status"] = status_map[reply_type]
    lead["crm_status"] = crm_stage_map[reply_type]
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
    return lead


def pipeline_summary() -> dict:
    raw_status = Counter(item["status"] for item in store.raw_leads)
    lead_status = Counter(item["status"] for item in store.leads)
    outreach_status = Counter(item["outreach_status"] for item in store.leads)
    crm_status = Counter(item["crm_status"] for item in store.leads)

    return {
        "keywords_total": len(store.keywords),
        "raw_leads_total": len(store.raw_leads),
        "approved_leads_total": len(store.leads),
        "raw_lead_status": dict(raw_status),
        "lead_status": dict(lead_status),
        "outreach_status": dict(outreach_status),
        "crm_status": dict(crm_status),
    }
