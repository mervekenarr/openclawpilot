import os
from copy import deepcopy

from app import store
from app.adapters.news_signal_client import SafeNewsSearchError, search_company_news_signals
from app.adapters.safe_research_client import fetch_company_website_summary
from app.research_policy import get_research_policy


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
    "operasyonel verimlilik odakli bir donemden geciyor",
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

SAFE_WEB_NOTE_PREFIX = "[public-web]"
SAFE_NEWS_NOTE_PREFIX = "[public-news]"


def build_seed_enrichment_result(raw_lead: dict) -> dict:
    return deepcopy(build_seed_research_bundle(raw_lead)["enrichment"])


def build_research_result(raw_lead: dict) -> dict:
    bundle = build_research_bundle(raw_lead)
    enrichment = deepcopy(bundle["enrichment"])
    enrichment["research_bundle"] = bundle
    return enrichment


def build_research_bundle(raw_lead: dict) -> dict:
    if _get_env_flag("SAFE_WEB_RESEARCH_ENABLED", False):
        return build_safe_research_bundle(raw_lead)

    return build_seed_research_bundle(raw_lead)


def build_seed_research_bundle(raw_lead: dict) -> dict:
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
        missing_fields.append("decision_maker_email")
    if raw_lead["id"] % 4 == 0:
        decision_maker["linkedin_hint"] = None
        missing_fields.append("linkedin_profile")
    if raw_lead["id"] % 5 == 0:
        decision_maker["name"] = None
        missing_fields.append("decision_maker_name")

    quality = _quality_from_missing(missing_fields)
    confidence = "high" if quality == "high" else "medium" if quality == "medium" else "low"
    priority = "high" if quality == "high" else "medium" if quality == "medium" else "low"

    enrichment = {
        "decision_maker": decision_maker,
        "company_summary": f"{raw_lead['company_name']} {raw_lead['sector']} alaninda aktif gorunen bir firma.",
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

    sources = [
        {
            "source_id": "seed_catalog",
            "label": "Baslangic sinyal paketi",
            "status": "reviewed",
            "risk": "low",
            "url": raw_lead.get("website"),
            "title": raw_lead["company_name"],
            "snippet": enrichment["summary"],
            "confidence": confidence,
            "relevance": "medium",
            "published_at": None,
        }
    ]

    return _build_bundle(raw_lead, mode="seeded", sources=sources, enrichment=enrichment)


def build_safe_research_bundle(raw_lead: dict) -> dict:
    snapshot = fetch_company_website_summary(
        website_url=raw_lead["website"],
        company_name=raw_lead["company_name"],
    )
    website_source = _build_website_source(raw_lead, snapshot)
    news_sources = _build_news_sources(raw_lead)
    sources = [website_source, *news_sources]
    enrichment = _build_safe_enrichment(raw_lead, snapshot, sources)
    return _build_bundle(raw_lead, mode="safe_web_first", sources=sources, enrichment=enrichment)


def _build_news_sources(raw_lead: dict) -> list[dict]:
    if not _get_env_flag("SAFE_NEWS_SEARCH_ENABLED", False):
        return [
            {
                "source_id": "news_scan",
                "label": "Haber taramasi",
                "status": "disabled",
                "risk": "low",
                "url": None,
                "title": "Haber taramasi kapali",
                "snippet": "SAFE_NEWS_SEARCH_ENABLED=false oldugu icin haber aramasi yapilmadi.",
                "confidence": "low",
                "relevance": "low",
                "published_at": None,
            }
        ]

    try:
        news_items = search_company_news_signals(
            company_name=raw_lead["company_name"],
            keyword=raw_lead["keyword"],
            max_results=3,
        )
    except SafeNewsSearchError as exc:
        return [
            {
                "source_id": "news_scan",
                "label": "Haber taramasi",
                "status": "error",
                "risk": "low",
                "url": None,
                "title": "Haber taramasi hatasi",
                "snippet": str(exc),
                "confidence": "low",
                "relevance": "low",
                "published_at": None,
            }
        ]

    if not news_items:
        return [
            {
                "source_id": "news_scan",
                "label": "Haber taramasi",
                "status": "no_hits",
                "risk": "low",
                "url": None,
                "title": "Yeni haber sinyali bulunamadi",
                "snippet": "Firma adi ve anahtar kelime ile anlamli public haber bulunamadi.",
                "confidence": "low",
                "relevance": "low",
                "published_at": None,
            }
        ]

    sources = []
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

    return sources


def _build_website_source(raw_lead: dict, snapshot: dict) -> dict:
    confidence = "high" if snapshot.get("meta_description") and snapshot.get("text_excerpt") else "medium"
    return {
        "source_id": "company_website",
        "label": "Sirket web sitesi",
        "status": "reviewed",
        "risk": "low",
        "url": snapshot.get("final_url") or raw_lead["website"],
        "title": snapshot.get("title") or raw_lead["company_name"],
        "snippet": snapshot.get("best_summary") or snapshot.get("text_excerpt"),
        "confidence": confidence,
        "relevance": snapshot.get("relevance") or "medium",
        "published_at": None,
    }


def _build_safe_enrichment(raw_lead: dict, snapshot: dict, sources: list[dict]) -> dict:
    reviewed_sources = [item for item in sources if item.get("status") == "reviewed"]
    reviewed_news = [
        item for item in reviewed_sources
        if item.get("source_id") == "news_scan"
    ]
    website_summary = snapshot.get("best_summary") or snapshot.get("text_excerpt") or "Sirket web sitesindeki acik bilgi su an sinirli."
    title = snapshot.get("title") or raw_lead["company_name"]
    website_text = " ".join(
        part for part in [
            website_summary,
            snapshot.get("text_excerpt"),
            " ".join(snapshot.get("headings") or []),
        ]
        if part
    ).lower()
    keyword = (raw_lead.get("keyword") or "").lower()
    keyword_found = bool(keyword and keyword in website_text)

    reviewed_count = len(reviewed_sources)
    high_confidence_count = sum(1 for item in reviewed_sources if item.get("confidence") == "high")

    if reviewed_news:
        recent_signal = f"Halka acik haber sinyali incelendi: {reviewed_news[0].get('title', 'baslik yok')[:180]}"
    else:
        recent_signal = f"Sirket web sitesi incelendi: {title[:180]}"

    website_has_strong_signal = bool(
        snapshot.get("meta_description")
        and snapshot.get("text_excerpt")
        and snapshot.get("relevance") == "high"
    )

    if reviewed_news and keyword_found:
        priority = "high"
        confidence = "high"
        data_reliability = "high"
        fit_reason = (
            f"Resmi site icerigi ve guncel halka acik haberler, {keyword or raw_lead['sector']} odakli uygunluk sinyali veriyor."
        )
    elif keyword_found or high_confidence_count >= 1 or website_has_strong_signal:
        priority = "medium"
        confidence = "medium"
        data_reliability = "high" if website_has_strong_signal else "medium"
        fit_reason = (
            f"{raw_lead['company_name']} icin resmi site icerigi hedef anahtar kelimeyle uyumlu; manuel incelemeye deger gorunuyor."
        )
    else:
        priority = "medium"
        confidence = "low"
        data_reliability = "medium" if reviewed_count else "low"
        fit_reason = (
            f"{raw_lead['company_name']} icin halka acik site verisi dogrulandi; ancak satis uygunlugu hala manuel teyit gerektiriyor."
        )

    summary = (
        "Resmi site arastirmasi tamamlandi."
        if not reviewed_news
        else "Resmi site ve halka acik haber arastirmasi tamamlandi."
    )

    source_notes = _build_source_notes(reviewed_sources)
    if not reviewed_news:
        source_notes.append(
            f"{SAFE_NEWS_NOTE_PREFIX} Yeni haber sinyali bulunmadi veya haber taramasi kapali."
        )

    return {
        "decision_maker": {
            "name": None,
            "title": None,
            "email": None,
            "linkedin_hint": None,
        },
        "company_summary": website_summary[:300],
        "recent_signal": recent_signal[:300],
        "fit_reason": fit_reason[:300],
        "summary": (
            f"{summary} Human review is still required before outreach."
        )[:300],
        "priority": priority,
        "confidence": confidence,
        "data_reliability": data_reliability,
        "missing_fields": [
            "decision_maker_name",
            "decision_maker_title",
            "decision_maker_email",
            "linkedin_profile",
        ],
        "source_notes": source_notes[:10],
    }


def _build_source_notes(sources: list[dict]) -> list[str]:
    notes: list[str] = []

    for source in sources:
        prefix = SAFE_WEB_NOTE_PREFIX if source.get("source_id") == "company_website" else SAFE_NEWS_NOTE_PREFIX
        if source.get("url"):
            notes.append(f"{prefix} Source URL: {source['url']}")
        if source.get("title"):
            notes.append(f"{prefix} Title: {source['title']}")
        if source.get("snippet"):
            notes.append(f"{prefix} Snippet: {source['snippet'][:220]}")

    notes.append(f"{SAFE_WEB_NOTE_PREFIX} LinkedIn ve tarayici otomasyonu kullanilmadi.")
    return notes


def _build_bundle(raw_lead: dict, mode: str, sources: list[dict], enrichment: dict) -> dict:
    policy = get_research_policy()
    reviewed_count = sum(1 for item in sources if item.get("status") == "reviewed")
    high_confidence_count = sum(1 for item in sources if item.get("confidence") == "high")
    news_count = sum(
        1
        for item in sources
        if item.get("source_id") == "news_scan" and item.get("status") == "reviewed"
    )

    return {
        "version": 1,
        "mode": mode,
        "built_at": store.utc_now(),
        "inputs": {
            "raw_lead_id": raw_lead["id"],
            "company_name": raw_lead["company_name"],
            "keyword": raw_lead["keyword"],
            "sector": raw_lead["sector"],
            "website": raw_lead.get("website"),
        },
        "sources": sources,
        "evidence_summary": {
            "source_count": len(sources),
            "reviewed_count": reviewed_count,
            "high_confidence_count": high_confidence_count,
            "news_count": news_count,
            "blocked_channels": list(policy.get("blocked_source_ids", [])),
        },
        "enrichment": enrichment,
    }


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


def _get_env_flag(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    return raw_value.strip().lower() in {"1", "true", "yes", "on"}
