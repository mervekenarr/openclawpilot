import os


ALLOWED_REAL_SEARCH_SOURCES = [
    {
        "id": "company_website",
        "label": "Sirket web sitesi",
        "risk": "low",
        "notes": "En guvenli ilk kaynak. Public ve dogrudan firma beyanina dayanir.",
    },
    {
        "id": "news_scan",
        "label": "Haber taramasi",
        "risk": "low",
        "notes": "Yatirim, kapasite artisi ve duyuru gibi sinyaller icin kullanilir.",
    },
    {
        "id": "public_registry",
        "label": "Acik sicil ve kayitlar",
        "risk": "low",
        "notes": "Sadece acik ve kamuya acik kayitlar kullanilir.",
    },
    {
        "id": "sector_directory",
        "label": "Sektor rehberleri",
        "risk": "medium",
        "notes": "Kalite degisken olabilir; veri guvenilirligi alanina yansitilmalidir.",
    },
]


BLOCKED_REAL_SEARCH_SOURCES = [
    {
        "id": "linkedin",
        "label": "LinkedIn otomasyonu",
        "status": "blocked",
        "reason": "Kisisel hesap riski ve platform kurallari nedeniyle ilk asamada kapali tutulur.",
    },
    {
        "id": "browser_automation",
        "label": "Tarayici otomasyonu",
        "status": "blocked",
        "reason": "Browser automation bu pilotta henuz acilmaz.",
    },
    {
        "id": "live_messaging",
        "label": "Canli mesaj gonderimi",
        "status": "blocked",
        "reason": "Insan onayi olmadan gonderim yapilmaz.",
    },
]


def get_research_policy() -> dict:
    safe_web_enabled = _get_env_flag("SAFE_WEB_RESEARCH_ENABLED", False)
    safe_news_enabled = _get_env_flag("SAFE_NEWS_SEARCH_ENABLED", False)

    return {
        "mode": "safe_web_first",
        "real_search_enabled": safe_web_enabled,
        "safe_news_enabled": safe_news_enabled,
        "allowed_sources": ALLOWED_REAL_SEARCH_SOURCES,
        "blocked_sources": BLOCKED_REAL_SEARCH_SOURCES,
        "allowed_source_ids": [item["id"] for item in ALLOWED_REAL_SEARCH_SOURCES],
        "blocked_source_ids": [item["id"] for item in BLOCKED_REAL_SEARCH_SOURCES],
        "next_safe_step": (
            "Sirket web sitesi, haber taramasi ve acik sicil kaynaklari ile basla. LinkedIn kapali kalsin."
            if safe_web_enabled and safe_news_enabled
            else "SAFE_WEB_RESEARCH_ENABLED=true yap; sonra SAFE_NEWS_SEARCH_ENABLED ile haber taramasini kontrollu ac."
        ),
    }


def _get_env_flag(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    return raw_value.strip().lower() in {"1", "true", "yes", "on"}
