import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import unicodedata
from urllib.parse import urlsplit

import requests
import trafilatura
from playwright.sync_api import sync_playwright


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


BLOCKED_HOST_TOKENS = [
    # Sosyal medya
    "facebook.com", "instagram.com", "x.com", "twitter.com",
    "youtube.com", "tiktok.com", "linkedin.com/in/", "pinterest.com",
    "reddit.com", "threads.net",
    # Ansiklopedi / Wiki
    "wikipedia.org", "wikimedia.org", "wikihow.com",
    # Türk haber siteleri
    "milliyet.com.tr", "hurriyet.com.tr", "sozcu.com.tr", "sabah.com.tr",
    "cumhuriyet.com.tr", "ensonhaber.com", "haber7.com", "aa.com.tr",
    "iha.com.tr", "dha.com.tr", "haberler.com", "ntv.com.tr",
    "cnnturk.com", "bloomberght.com", "ekonomim.com", "dunya.com",
    "takvim.com.tr", "posta.com.tr", "aksam.com.tr", "star.com.tr",
    "turkiyegazetesi.com.tr", "yenisafak.com", "karar.com",
    "gazetevatan.com", "birgun.net", "bianet.org", "t24.com.tr",
    "habertürk.com", "haberturk.com", "tele1.com.tr",
    "para.com.tr", "dunya.com", "ticaret.gov.tr",
    # Genel haber / blog
    "haber", "gazete", "news", "blog", "medium.com", "onedio.com",
    "eksisozluk.com", "uludagsozluk.com",
    # İlan / rehber siteleri
    "sahibinden.com", "armut.com", "letgo.com", "hepsiemlak.com",
    "emlakjet.com", "zingat.com", "remax.com.tr",
    "yellowpages", "rehber", "firmarehberi", "sirketrehberi",
    "beyazsayfa", "kobiler.com", "hotfrog", "cylex",
    "ito.org.tr", "tobb.org.tr", "tesk.org.tr", "istanbul.zone",
    "turkonfed.org.tr", "pageshunt", "firmaara", "yerelbul",
    "neredekal.com", "tripadvisor", "yelp.com",
    # Arama motorları
    "yandex.com", "google.com", "bing.com", "yahoo.com", "duckduckgo.com",
    # E-ticaret / pazar yerleri
    "trendyol.com", "hepsiburada.com", "n11.com", "amazon.com",
    "gittigidiyor.com", "ciceksepeti.com",
    # Diğer
    "gov.tr", "edu.tr", "wikipedia", "wikidata",
]

# Başlıkta bu kelimeler varsa haber/ilan sitesidir — geç
BLOCKED_TITLE_TOKENS = [
    "haberleri", "haberi", "haber ", " haber", "gazetesi",
    "manşet", "gündem", "son dakika", "breaking", " news",
    "ilanı", "ilanları", "emlak ilan", "satılık", "kiralık",
]

# Arama sonuçlarını filtreleyen ürün-ilişkili kelimeler
PRODUCT_RELATION_KEYWORDS = [
    "satış", "satai", "satıyor", "üretim", "üretici", "üretiyor",
    "ithal", "ihracat", "dağıtıcı", "distribütör", "tedarik",
    "tedarikçi", "kaynak", "imalat", "fabrika", "ticaret",
    "pazarlama", "reklam", "hizmet", "çözüm", "çözüm sağla",
    "uygulamalar", "teknoloji", "sistem", "yazılım", "donanım",
]

_TR_CHAR_MAP = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")

PRODUCT_STOPWORDS = {
    "a", "an", "and", "the", "of", "or", "to", "for", "with",
    "ve", "veya", "ile", "icin", "bir", "bu", "su",
    "urun", "urunu", "urunleri", "hizmet", "hizmeti", "cozum", "cozumu",
}

SELLER_INTENT_TERMS = [
    "satis", "satiyor", "uretim", "uretici", "uretiyor", "imalat",
    "imalatci", "tedarik", "tedarikci", "distributor", "dagitici",
    "ithalat", "ihracat", "bayi", "bayii", "toptan", "fabrika",
    "manufacturer", "supplier", "distributor", "dealer", "wholesale",
    "products", "product", "catalog", "catalogue",
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")


def _read_dotenv_value(key: str, default: str = "") -> str:
    if not os.path.exists(ENV_PATH):
        return default
    try:
        with open(ENV_PATH, "r", encoding="utf-8") as env_file:
            for line in env_file:
                raw = line.strip()
                if not raw or raw.startswith("#") or "=" not in raw:
                    continue
                env_key, env_value = raw.split("=", 1)
                if env_key.strip() == key:
                    return env_value.strip().strip('"').strip("'")
    except Exception:
        return default
    return default


def get_config_value(key: str, default: str = "") -> str:
    return (os.getenv(key) or _read_dotenv_value(key, default) or default).strip()


def _config_bool(key: str, default: bool = False) -> bool:
    raw = get_config_value(key, "true" if default else "false").lower()
    return raw in {"1", "true", "yes", "on"}


def _normalize_for_match(value: str) -> str:
    text = (value or "").translate(_TR_CHAR_MAP)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def _product_terms(keyword: str) -> list[str]:
    normalized = _normalize_for_match(keyword)
    tokens = re.findall(r"[a-z0-9]+", normalized)
    terms = [
        token
        for token in tokens
        if token not in PRODUCT_STOPWORDS and (len(token) >= 3 or any(ch.isdigit() for ch in token))
    ]
    return terms or [token for token in tokens if len(token) >= 2]


def _contains_term(haystack: str, term: str) -> bool:
    pattern = rf"(?<![a-z0-9]){re.escape(term)}[a-z0-9]*"
    return bool(re.search(pattern, haystack))


def _product_match_details(text: str, keyword: str) -> tuple[bool, bool, list[str]]:
    haystack = _normalize_for_match(text)
    terms = _product_terms(keyword)
    if not terms:
        return False, False, []

    phrase = re.sub(r"[^a-z0-9]+", " ", _normalize_for_match(keyword)).strip()
    phrase_match = bool(phrase and len(phrase) >= 3 and phrase in haystack)
    matched_terms = [term for term in terms if _contains_term(haystack, term)]

    if len(terms) == 1:
        return bool(matched_terms), phrase_match, matched_terms

    anchor = terms[-1]
    enough_terms = len(matched_terms) >= min(2, len(terms))
    return phrase_match or (anchor in matched_terms and enough_terms), phrase_match, matched_terms


def has_product_evidence(text: str, keyword: str) -> bool:
    matched, _, _ = _product_match_details(text, keyword)
    return matched


def _has_seller_intent(text: str) -> bool:
    haystack = _normalize_for_match(text)
    return any(_contains_term(haystack, term) for term in SELLER_INTENT_TERMS)


def _sector_match(text: str, sector: str) -> bool:
    sector_terms = _product_terms(sector)
    if not sector_terms:
        return True
    haystack = _normalize_for_match(text)
    return any(_contains_term(haystack, term) for term in sector_terms)


def check_allowed(url):
    if not url:
        return False
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.lower()
    except Exception:
        domain = url.lower()
    return not any(token in domain for token in BLOCKED_HOST_TOKENS)


def is_title_allowed(title: str) -> bool:
    """Başlık haber veya ilan gibi görünüyorsa False döner."""
    t = (title or "").lower()
    return not any(token in t for token in BLOCKED_TITLE_TOKENS)


def is_domain_reachable(url):
    if "linkedin.com" in url.lower():
        return True
    try:
        host = url.split("//")[-1].split("/")[0].split(":")[0]
        socket.setdefaulttimeout(2)
        socket.getaddrinfo(host, None)
        resp = requests.head(url, timeout=3, allow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0"})
        return resp.status_code < 500
    except Exception:
        return False


def is_website_relevant_to_product(url, keyword, sector, snippet="", title=""):
    """
    Return True only when the result contains evidence for the requested product.
    Sector-only matches are intentionally rejected because they create noisy leads.
    """
    fast_haystack = " ".join([title or "", snippet or "", url or ""])

    if has_product_evidence(fast_haystack, keyword) and (
        _has_seller_intent(fast_haystack) or _sector_match(fast_haystack, sector)
    ):
        return True

    try:
        downloaded = trafilatura.fetch_url(url, timeout=4)
        if not downloaded:
            return has_product_evidence(fast_haystack, keyword) and _has_seller_intent(fast_haystack)

        content = trafilatura.extract(downloaded)
        if not content:
            return has_product_evidence(fast_haystack, keyword) and _has_seller_intent(fast_haystack)

        combined = " ".join([fast_haystack, content[:2000]])
        combined_normalized = _normalize_for_match(combined)
        blocked_keywords = ["porn", "casino", "bahis", "kumar", "xxx", "adult"]
        if any(bk in combined_normalized for bk in blocked_keywords):
            return False
        if not has_product_evidence(combined, keyword):
            return False
        return _has_seller_intent(combined) or _sector_match(combined, sector)
    except Exception:
        return has_product_evidence(fast_haystack, keyword) and _has_seller_intent(fast_haystack)


def normalize_linkedin_company_url(url):
    if not url or "linkedin.com/company/" not in url.lower():
        return ""
    clean = url.split("?")[0].split("#")[0].rstrip("/")
    if clean.startswith("/"):
        clean = "https://www.linkedin.com" + clean
    return clean


def search_linkedin_company_url(company_name, keyword="", sector="", location="", country=""):
    """Find a LinkedIn company URL for a company discovered on the web."""
    if not company_name:
        return ""

    query_parts = [
        f'"{company_name}"',
        keyword,
        sector,
        location,
        country,
        "site:linkedin.com/company",
    ]
    query = " ".join(part for part in query_parts if part).strip()

    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            for result in ddgs.text(query, max_results=8):
                candidate_url = normalize_linkedin_company_url(result.get("href", ""))
                if candidate_url:
                    return candidate_url
    except Exception:
        pass

    return ""


def _openclaw_cli_path() -> str:
    configured = get_config_value("OPENCLAW_CLI")
    if configured and os.path.exists(configured):
        return configured
    return shutil.which("openclaw") or ""


def _openclaw_gateway_healthy(timeout_ms=4000) -> bool:
    cli = _openclaw_cli_path()
    if not cli:
        return False
    try:
        completed = subprocess.run(
            [cli, "health", "--json", "--timeout", str(timeout_ms)],
            capture_output=True,
            text=True,
            timeout=max(2, int(timeout_ms / 1000) + 2),
        )
        return completed.returncode == 0
    except Exception:
        return False


def _openclaw_http_base_url() -> str:
    raw = (
        get_config_value("OPENCLAW_GATEWAY_HTTP_URL")
        or get_config_value("OPENCLAW_GATEWAY_URL")
        or "http://127.0.0.1:18789"
    )
    if raw.startswith("ws://"):
        raw = "http://" + raw[len("ws://"):]
    elif raw.startswith("wss://"):
        raw = "https://" + raw[len("wss://"):]
    return raw.rstrip("/")


def _openclaw_http_healthy(timeout_seconds=1.5) -> bool:
    try:
        parsed = urlsplit(_openclaw_http_base_url())
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if not host:
            return False
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except Exception:
        return False


def _openclaw_discovery_prompt(keyword, sector, location, country, limit) -> str:
    return (
        "Find real B2B companies for sales prospecting. "
        "Return only valid JSON, no markdown. "
        f"Target product/service: {keyword}. "
        f"Target sector: {sector}. "
        f"Target location: {location or country}. "
        f"Country: {country}. "
        "Only include companies that explicitly sell, manufacture, distribute, install, or supply the target product/service. "
        "Every company must include at least one source URL: official website or LinkedIn company page. "
        "Prefer official company websites and LinkedIn company pages; do not include directories, marketplaces, news, blogs, or people profiles. "
        f"Return up to {limit} items with this exact shape: "
        '{"companies":[{"company_name":"","website":"","linkedin_url":"","snippet":"","evidence":""}]}'
    )


def _run_openclaw_cli_agent(prompt: str, timeout_seconds: int) -> str:
    if not _config_bool("OPENCLAW_CLI_AGENT_ENABLED", True):
        return ""
    cli = _openclaw_cli_path()
    if not cli or not _openclaw_http_healthy():
        return ""
    try:
        completed = subprocess.run(
            [
                cli,
                "agent",
                "--session-id",
                "openclawpilot-discovery",
                "--message",
                prompt,
                "--json",
                "--timeout",
                str(timeout_seconds),
                "--thinking",
                "medium",
            ],
            capture_output=True,
            text=True,
            timeout=timeout_seconds + 10,
        )
    except Exception:
        return ""
    if completed.returncode != 0:
        return ""
    return "\n".join([completed.stdout or "", completed.stderr or ""])


def _run_openclaw_gateway_chat(prompt: str, timeout_seconds: int) -> str:
    base_url = _openclaw_http_base_url()
    token = get_config_value("OPENCLAW_GATEWAY_TOKEN", "demo-openclaw-token")
    model = get_config_value("OPENCLAW_DISCOVERY_MODEL", get_config_value("OLLAMA_MODEL", "qwen2.5:14b"))
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {
        "model": model if "/" in model else f"ollama/{model}",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a careful B2B sourcing analyst. "
                    "Use only companies you can support with URLs. "
                    "Return JSON only."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "temperature": 0.1,
    }
    try:
        response = requests.post(
            f"{base_url}/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=timeout_seconds,
        )
        if response.status_code != 200:
            return ""
        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return content or json.dumps(data)
    except Exception:
        return ""


def _extract_json_payloads(raw_text: str) -> list:
    text = (raw_text or "").strip()
    if not text:
        return []

    payloads = []
    try:
        payloads.append(json.loads(text))
    except Exception:
        pass

    fenced = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    for block in fenced:
        try:
            payloads.append(json.loads(block.strip()))
        except Exception:
            pass

    for match in re.finditer(r"(\[[\s\S]*\]|\{[\s\S]*\})", text):
        snippet = match.group(1)
        try:
            payloads.append(json.loads(snippet))
        except Exception:
            continue

    return payloads


def _walk_json_values(value):
    if isinstance(value, (list, tuple)):
        yield value
        for item in value:
            yield from _walk_json_values(item)
    elif isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk_json_values(nested)
    elif isinstance(value, str):
        for payload in _extract_json_payloads(value):
            yield from _walk_json_values(payload)


def _candidate_dicts_from_openclaw(raw_text: str) -> list[dict]:
    candidates = []
    for payload in _extract_json_payloads(raw_text):
        for value in _walk_json_values(payload):
            if isinstance(value, dict):
                possible_list = (
                    value.get("companies")
                    or value.get("results")
                    or value.get("leads")
                    or value.get("items")
                )
                if isinstance(possible_list, list):
                    for item in possible_list:
                        if isinstance(item, dict):
                            candidates.append(item)
                elif any(key in value for key in ["company_name", "name", "website", "linkedin_url", "url"]):
                    candidates.append(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        candidates.append(item)
    deduped = []
    seen = set()
    for candidate in candidates:
        key = json.dumps(candidate, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _clean_company_url(value: str) -> str:
    url = (value or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    elif not url.startswith(("http://", "https://")):
        if "." not in url.split("/")[0]:
            return ""
        url = "https://" + url
    return url.split()[0].strip(".,;)")


def _openclaw_candidate_to_result(candidate: dict, keyword: str, sector: str) -> dict | None:
    name = (
        candidate.get("company_name")
        or candidate.get("company")
        or candidate.get("name")
        or candidate.get("title")
        or ""
    ).strip()
    website = _clean_company_url(candidate.get("website") or candidate.get("site") or "")
    linkedin_url = normalize_linkedin_company_url(
        candidate.get("linkedin_url") or candidate.get("linkedin") or ""
    )
    generic_url = _clean_company_url(candidate.get("url") or candidate.get("source_url") or "")
    if generic_url:
        if "linkedin.com/company/" in generic_url.lower() and not linkedin_url:
            linkedin_url = normalize_linkedin_company_url(generic_url)
        elif not website:
            website = generic_url

    snippet = (
        candidate.get("snippet")
        or candidate.get("description")
        or candidate.get("reason")
        or candidate.get("evidence")
        or ""
    ).strip()
    evidence_text = " ".join([name, website, linkedin_url, snippet])

    if website:
        if not check_allowed(website) or "linkedin.com" in website.lower():
            website = ""
        elif not is_website_relevant_to_product(website, keyword, sector, snippet, name):
            website = ""

    if not website and linkedin_url and not has_product_evidence(evidence_text, keyword):
        return None
    if not website and not linkedin_url:
        return None
    if not name:
        source_url = linkedin_url or website
        name = source_url.split("//")[-1].split("/")[0].replace("www.", "").title()

    return {
        "company_name": name[:100],
        "website": website or linkedin_url,
        "linkedin_url": linkedin_url,
        "is_linkedin": bool(linkedin_url and not website),
        "is_openclaw": True,
        "snippet": snippet[:250] or f"{keyword} {sector}",
        "sales_script": "",
        "score": 100,
    }


def search_openclaw_companies(keyword, sector, location, country, limit=5):
    """Ask OpenClaw for sourced company leads, then verify every result locally."""
    if not _config_bool("OPENCLAW_DISCOVERY_ENABLED", True):
        return []
    if not _openclaw_http_healthy():
        return []

    timeout_seconds = int(get_config_value("OPENCLAW_AGENT_TIMEOUT_SECONDS", "90") or "90")
    prompt = _openclaw_discovery_prompt(keyword, sector, location, country, limit)
    raw = _run_openclaw_cli_agent(prompt, timeout_seconds)
    if not raw:
        raw = _run_openclaw_gateway_chat(prompt, min(timeout_seconds, 60))
    if not raw:
        return []

    results = []
    seen = set()
    for candidate in _candidate_dicts_from_openclaw(raw):
        item = _openclaw_candidate_to_result(candidate, keyword, sector)
        if not item:
            continue
        key = (item.get("linkedin_url") or item.get("website") or item.get("company_name", "")).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        results.append(item)
        if len(results) >= limit:
            break
    return results


def _linkedin_storage_state_path() -> str:
    configured = get_config_value("LINKEDIN_STORAGE_STATE_PATH")
    candidates = []
    if configured:
        candidates.append(configured)
    candidates.extend(
        [
            os.path.join(BASE_DIR, "runtime-home", "linkedin-storage-state.json"),
            os.path.join(BASE_DIR, "runtime-home", "linkedin-bootstrap-profile", "state.json"),
            "/app/runtime-home/linkedin-storage-state.json",
        ]
    )
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return ""


def search_linkedin_companies(keyword, sector, location, country, token="", limit=5, storage_state_path=""):
    """Search LinkedIn company pages via DuckDuckGo — no auth required."""
    results = []
    loc_tokens = _location_tokens(location)
    loc_part = location if location else country

    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        queries = [
            f'{keyword} {sector} {loc_part} site:linkedin.com/company',
            f'{keyword} {loc_part} site:linkedin.com/company',
            f'{keyword} {country} site:linkedin.com/company',
        ]
        seen = set()

        for query in queries:
            if len(results) >= limit:
                break
            with DDGS() as ddgs:
                    for result in ddgs.text(query, max_results=20):
                        if len(results) >= limit:
                            break

                        url = result.get("href", "")
                        if not url or "linkedin.com/company/" not in url.lower():
                            continue

                        clean_url = normalize_linkedin_company_url(url)
                        if not clean_url or clean_url in seen:
                            continue

                        snippet = result.get("body", "") + " " + result.get("title", "")
                        snippet_low = snippet.lower()
                        if loc_tokens:
                            other_cities = ["ankara", "izmir", "bursa", "antalya", "adana", "konya", "gaziantep", "kocaeli"]
                            loc_main = loc_tokens[0]
                            skip = False
                            for city in other_cities:
                                if city != loc_main and city in snippet_low and loc_main not in snippet_low:
                                    skip = True
                                    break
                            if skip:
                                continue

                        seen.add(clean_url)
                        title = result.get("title", "")
                        name = title.split("|")[0].split("-")[0].split("•")[0].strip()[:80]
                        if not name or len(name) < 2:
                            name = clean_url.split("/company/")[-1].strip("/").replace("-", " ").title()

                        results.append(
                            {
                                "company_name": name,
                                "website": clean_url,
                                "linkedin_url": clean_url,
                                "is_linkedin": True,
                                "snippet": snippet[:200],
                                "sales_script": "",
                                "score": 100,
                            }
                        )
    except Exception:
        pass

    return results


def _location_tokens(location: str) -> list[str]:
    """Returns lowercase variants of a city/location name for snippet matching."""
    if not location.strip():
        return []
    tr_map = str.maketrans("ışğüöçİŞĞÜÖÇ", "isgoucISGUOC")
    # Apply tr_map BEFORE lower() so Turkish İ → I → i (not i̇)
    normalized = location.strip().translate(tr_map).lower()
    raw = location.strip().lower()
    variants = {normalized, raw}
    alias = {"istanbul": "istanbul", "izmir": "izmir", "ankara": "ankara"}
    for k, v in alias.items():
        if k in normalized or v in normalized:
            variants.add(k)
            variants.add(v)
    return [v for v in variants if v]


def _result_matches_location(result: dict, location_tokens: list[str]) -> bool:
    """Returns True if the search result snippet/title/url contains the target location."""
    if not location_tokens:
        return True
    haystack = " ".join([
        result.get("title", ""),
        result.get("body", ""),
        result.get("href", ""),
    ]).lower()
    return any(tok in haystack for tok in location_tokens)


def search_web_companies(keyword, sector, location, country, limit=5):
    """Search official websites — tries multiple queries to guarantee enough results."""
    results = []
    loc_tokens = _location_tokens(location)
    loc_part = location if location else country

    queries = [
        f'{keyword} {sector} şirketi {loc_part}',
        f'{keyword} {loc_part} firması',
        f'{keyword} şirketi {country}',
        f'{keyword} {sector} {country}',
    ]

    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        seen = set()

        for query_idx, web_query in enumerate(queries):
            if len(results) >= limit:
                break
            # Son 2 sorguda lokasyon filtresi gevşet — minimum 5 garantisi için
            strict_location = query_idx < 2

            try:
                with DDGS() as ddgs:
                    for result in ddgs.text(web_query, max_results=30):
                        if len(results) >= limit:
                            break

                        url = result.get("href", "")
                        title = result.get("title", "")
                        if not url or url in seen or not check_allowed(url):
                            continue
                        if "linkedin.com" in url.lower():
                            continue
                        if not is_title_allowed(title):
                            continue

                        if strict_location and loc_tokens and not _result_matches_location(result, loc_tokens):
                            continue

                        snippet = result.get("body", "")
                        # Sadece snippet ile hızlı kontrol — site indirme yok
                        if not has_product_evidence(snippet + " " + title, keyword) and not _sector_match(snippet + " " + title, sector):
                            continue

                        seen.add(url)
                        name = title.split(" | ")[0].split(" - ")[0].strip()
                        if not name:
                            name = url.split("//")[-1].split("/")[0].replace("www.", "").title()

                        results.append(
                            {
                                "company_name": name,
                                "website": url,
                                "linkedin_url": "",
                                "is_linkedin": False,
                                "snippet": snippet[:200],
                                "sales_script": "",
                                "score": 100,
                            }
                        )
            except Exception:
                continue

    except Exception:
        pass

    return results


def read_website_content(url, linkedin_token=""):
    try:
        if "linkedin.com" in url.lower() and linkedin_token:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
            }
            cookies = {"li_at": linkedin_token}
            response = requests.get(url, headers=headers, cookies=cookies, timeout=15)
            if response.status_code == 200:
                content = trafilatura.extract(response.text)
                if content:
                    return content[:3000]
                return "LinkedIn sayfasi okundu ama icerik cikarilamadi."
            return f"LinkedIn erisim hatasi: {response.status_code}"

        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return "Hata"
        content = trafilatura.extract(downloaded)
        return content[:3000] if content else "Hata"
    except Exception:
        return "Hata"


_CONTACT_SLUGS = [
    "iletisim", "iletişim", "contact", "contact-us", "bize-ulasin",
    "bize-ulaşın", "hakkimizda", "hakkında", "about", "about-us",
    "adresimiz", "kurumsal", "corporate",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}


def _base_url(url: str) -> str:
    parts = url.split("//", 1)
    if len(parts) < 2:
        return url
    scheme = parts[0] + "//"
    host = parts[1].split("/")[0]
    return scheme + host


def find_contact_url(website_url: str) -> str:
    """
    Firmanın iletişim sayfasını bulmaya çalışır.
    Önce ana sayfadaki linklere bakar, bulamazsa bilinen slug'ları dener.
    """
    if not website_url or "linkedin.com" in website_url.lower():
        return ""

    base = _base_url(website_url)

    # 1. Ana sayfayı oku, içindeki linkleri tara
    try:
        resp = requests.get(website_url, headers=_HEADERS, timeout=8, allow_redirects=True)
        if resp.status_code == 200:
            html = resp.text.lower()
            for slug in _CONTACT_SLUGS:
                patterns = [f'href="/{slug}', f"href='/{slug}", f'href="/{slug}/',
                            f'/{slug}"', f"/{slug}'"]
                if any(p in html for p in patterns):
                    candidate = f"{base}/{slug}"
                    try:
                        r2 = requests.head(candidate, headers=_HEADERS, timeout=5, allow_redirects=True)
                        if r2.status_code < 400:
                            return candidate
                    except Exception:
                        pass
    except Exception:
        pass

    # 2. Bilinen slug'ları doğrudan dene
    for slug in _CONTACT_SLUGS:
        candidate = f"{base}/{slug}"
        try:
            r = requests.head(candidate, headers=_HEADERS, timeout=5, allow_redirects=True)
            if r.status_code < 400:
                return candidate
        except Exception:
            continue

    return ""


def read_contact_page(website_url: str) -> str:
    """
    Firmanın iletişim sayfasını okur ve ham metni döner.
    Adres, şehir, telefon bilgisi içerir.
    """
    contact_url = find_contact_url(website_url)
    if not contact_url:
        return ""
    try:
        resp = requests.get(contact_url, headers=_HEADERS, timeout=10, allow_redirects=True)
        if resp.status_code != 200:
            return ""
        content = trafilatura.extract(resp.text)
        if content:
            return f"[İletişim sayfası: {contact_url}]\n{content[:1500]}"
        # trafilatura tutmadıysa ham metni kırp
        import re as _re
        text = _re.sub(r"<[^>]+>", " ", resp.text)
        text = _re.sub(r"\s+", " ", text).strip()
        return f"[İletişim sayfası: {contact_url}]\n{text[:1500]}"
    except Exception:
        return ""


def _result_dedupe_key(item: dict) -> str:
    for key in ["linkedin_url", "website"]:
        value = (item.get(key) or "").lower().strip()
        if value:
            return value.rstrip("/")
    return _normalize_for_match(item.get("company_name", ""))


def _merge_company_results(*groups: list[dict], limit=8) -> list[dict]:
    merged = []
    seen = set()
    for group in groups:
        for item in group or []:
            key = _result_dedupe_key(item)
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= limit:
                return merged
    return merged


def openclaw_discover_companies(keyword, sector, location="", country="", limit=8):
    """
    Discovery flow: Her kaynaktan bağımsız 5 sonuç, toplam max 10.
    """
    per_source = max(5, limit // 2)

    web_results = search_web_companies(keyword, sector, location, country, limit=per_source)

    linkedin_token = get_config_value("LINKEDIN_SESSION_TOKEN")
    linkedin_storage_state = _linkedin_storage_state_path()

    linkedin_results = search_linkedin_companies(
        keyword,
        sector,
        location,
        country,
        linkedin_token,
        limit=per_source,
        storage_state_path=linkedin_storage_state,
    )

    return _merge_company_results(web_results, linkedin_results, limit=per_source * 2)
