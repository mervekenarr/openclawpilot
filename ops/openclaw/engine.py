import os
import json
import re
import sys
import asyncio
import base64
import subprocess
import requests
import trafilatura
from playwright.sync_api import sync_playwright
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from bs4 import BeautifulSoup

# Windows üzerinde Playwright ve Asyncio çakışmasını önlemek için Proactor policy ayarı
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Playwright varsayilan olarak acik kalir.
# Gerekirse .env veya ortam degiskeni ile OPENCLAW_DISABLE_PLAYWRIGHT=1 yapilarak kapatilabilir.
PLAYWRIGHT_DISABLED = os.getenv("OPENCLAW_DISABLE_PLAYWRIGHT", "").strip() == "1"
PLAYWRIGHT_WAIT_UNTIL = (os.getenv("OPENCLAW_PLAYWRIGHT_WAIT_UNTIL", "networkidle").strip() or "networkidle")

# ==========================================
# GÜVENLİK VE FİLTRELEME (AYIRICILAR)
# ==========================================
BLOCKED_HOST_TOKENS = [
    "facebook.com", "instagram.com", "x.com", "twitter.com",
    "youtube.com", "tiktok.com", "wikipedia.org", "amazon.", "hepsiburada.",
    "trendyol.", "n11.", "alibaba.", "aliexpress.", "sahibinden.com",
    "emlakjet.com", "zingat.com", "milliyet.com.tr", "hurriyet.com.tr",
    "sozcu.com.tr", "sabah.com.tr", "cumhuriyet.com.tr", "ensonhaber.com",
    "haber7.com", "letgo.com", "dolap.com", "zhihu.com", "quora.com",
    "reddit.com", "tripadvisor.", "britannica.com", "crazygames.com",
    "support.microsoft.com", "learn.microsoft.com"
] # LİNKEDİN ÇIKARILDI: LinkedIn sonuçlarının gelmesi için engeli kaldırdık.

BAD_SUBDOMAIN_PREFIXES = [
    "support", "docs", "doc", "help", "blog", "news", "forum", "answers",
    "learn", "developer", "developers", "community", "kb", "wiki"
]

BAD_PATH_TOKENS = [
    "/question/", "/questions/", "/topic/", "/wiki/", "/article/", "/articles/",
    "/support/", "/help/", "/docs/", "/doc/", "/blog/", "/news/", "/forum/",
    "/kb/", "/tardis/", "/art/"
]

QUESTIONISH_TOKENS = [
    "what is", "nedir", "how to", "nasil", "soru", "question", "wikipedia",
    "guide", "tripadvisor", "crazygames", "zhihu", "quora"
]

COMPANY_HINT_TOKENS = [
    "company", "firma", "official", "resmi", "corporate", "kurumsal",
    "manufacturer", "supplier", "industrial", "sanayi", "uretim", "uretici",
    "factory", "solutions", "services", "products", "urun", "hakkimizda",
    "about us", "enterprise", "group", "holding", "inc", "ltd", "llc"
]

INDUSTRY_TOKENS = [
    "industry", "industrial", "manufacturing", "supplier", "manufacturer", 
    "corporation", "limited", "ltd", "inc", "group", "holding", "services", 
    "solutions", "global", "enterprise", "distributor", "factory", "production"
]

ISO_COUNTRY_MAP = {
    # Popüler Bölgeler
    "turkiye": "TR", "turkey": "TR", "tr": "TR", "germany": "DE", "almanya": "DE", "germania": "DE",
    "united states": "US", "usa": "US", "abd": "US", "uk": "GB", "united kingdom": "GB", "england": "GB", "ingiltere": "GB",
    "italy": "IT", "italia": "IT", "italya": "IT", "france": "FR", "fransa": "FR", "spain": "ES", "espana": "ES", "ispanya": "ES",
    "netherlands": "NL", "holland": "NL", "hollanda": "NL", "belgium": "BE", "belcika": "BE", "switzerland": "CH", "isvicre": "CH",
    "austria": "AT", "avusturya": "AT", "sweden": "SE", "isvec": "SE", "norway": "NO", "norvec": "NO", "denmark": "DK", "danimarka": "DK",
    "finland": "FI", "finlandiya": "FI", "poland": "PL", "polonya": "PL", "russia": "RU", "rusya": "RU", "ukraine": "UA", "ukrayna": "UA",
    "china": "CN", "cin": "CN", "japan": "JP", "japonya": "JP", "korea": "KR", "kore": "KR", "india": "IN", "hindistan": "IN",
    "brazil": "BR", "brezilya": "BR", "mexico": "MX", "meksika": "MX", "canada": "CA", "kanada": "CA", "australia": "AU", "avustralya": "AU",
    "singapore": "SG", "singapur": "SG", "uae": "AE", "dubai": "AE", "qatar": "QA", "katar": "QA", "saudi arabia": "SA", "suudi arabistan": "SA",
    "egypt": "EG", "misir": "EG", "south africa": "ZA", "guney afrika": "ZA", "nigeria": "NG", "nijerya": "NG", "israel": "IL", "israil": "IL",
    "greece": "GR", "yunanistan": "GR", "bulgaria": "BG", "bulgaristan": "BG", "romania": "RO", "romanya": "RO", "azerbaijan": "AZ", "azerbaycan": "AZ"
}

TLD_MAP = {
    "germany": ".de", "almanya": ".de", "france": ".fr", "fransa": ".fr",
    "italy": ".it", "italya": ".it", "uk": ".co.uk", "usa": ".com"
}

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}

HTTP_SESSION = requests.Session()
HTTP_SESSION.trust_env = False

OPENCLAW_HOME = Path(__file__).resolve().parents[2] / ".openclaw-home"
OPENCLAW_CONFIG_PATH = OPENCLAW_HOME / "openclaw.json"
OPENCLAW_COMMAND_TIMEOUT_MS = 90000

LEGAL_SUFFIX_TOKENS = {
    "as", "a", "s", "a.s", "ltd", "sti", "sti.", "limited", "inc", "llc",
    "corp", "co", "company", "gmbh", "ag", "sa", "plc", "bv", "oy", "ab",
    "group", "holding", "san", "tic", "ve", "anonim", "sirketi", "sirket",
    "corporation"
}

def fold_text(text):
    """Karakter temizleme ve normalize etme (Türkçe dahil)."""
    text = (text or "").lower()
    replacements = {'ı': 'i', 'ş': 's', 'ğ': 'g', 'ü': 'u', 'ö': 'o', 'ç': 'c'}
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text


def normalize_company_identity(name):
    """Firma isimlerini ortak bir karsilastirma formatina indirger."""
    raw = re.sub(r"[^a-z0-9]+", " ", fold_text(name))
    tokens = [token for token in raw.split() if token and token not in LEGAL_SUFFIX_TOKENS]
    return " ".join(tokens)


def company_token_set(name):
    """Anlamli firma tokenlarini cikarir."""
    return {token for token in normalize_company_identity(name).split() if len(token) >= 3}

def is_allowed_domain(url):
    """Çöp siteleri ve sosyal medyayı eler."""
    domain = url.lower()
    return not any(token in domain for token in BLOCKED_HOST_TOKENS)


def build_query(*parts):
    """Boş parçaları eleyip okunabilir arama cümlesi oluşturur."""
    return " ".join(str(part).strip() for part in parts if str(part).strip())


def goto_with_fallback(page, url, timeout=40000):
    """Once tam yukleme dener, takilirsa daha gevsek moda duser."""
    try:
        page.goto(url, wait_until=PLAYWRIGHT_WAIT_UNTIL, timeout=timeout)
    except Exception:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout)


def openclaw_env():
    """OpenClaw CLI komutlarini proje icindeki local state ile calistirir."""
    env = os.environ.copy()
    if OPENCLAW_CONFIG_PATH.exists():
        env["OPENCLAW_CONFIG_PATH"] = str(OPENCLAW_CONFIG_PATH)
        env["OPENCLAW_STATE_DIR"] = str(OPENCLAW_HOME)
    env.setdefault("NO_COLOR", "1")
    return env


def parse_cli_json_output(text):
    """CLI bazen gürültü üretebildigi icin ilk JSON blogunu ayiklar."""
    raw = (text or "").strip()
    if not raw:
        return {}

    for marker in ("{", "["):
        idx = raw.find(marker)
        if idx != -1:
            try:
                return json.loads(raw[idx:])
            except Exception:
                continue

    raise ValueError(f"JSON parse edilemedi: {raw[:200]}")


def run_openclaw_cli(args, timeout_ms=OPENCLAW_COMMAND_TIMEOUT_MS, expect_json=True):
    """OpenClaw CLI komutunu JSON veya metin cikti ile calistirir."""
    completed = subprocess.run(
        ["openclaw", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(timeout_ms / 1000.0, 1.0),
        env=openclaw_env(),
        check=False,
    )
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if completed.returncode != 0:
        raise RuntimeError(stderr or stdout or f"OpenClaw komutu hata verdi: {' '.join(args)}")
    return parse_cli_json_output(stdout) if expect_json else stdout


def openclaw_browser_available():
    """OpenClaw browser durumunu dondurur; yoksa None."""
    if not OPENCLAW_CONFIG_PATH.exists():
        return None
    try:
        return run_openclaw_cli(["browser", "--json", "status"], timeout_ms=20000)
    except Exception as exc:
        print(f"OpenClaw browser status okunamadi: {exc}")
        return None


def ensure_openclaw_browser_started():
    """OpenClaw browser calisir durumda degilse baslatir."""
    status = openclaw_browser_available()
    if not status:
        return None
    if status.get("running"):
        return status
    try:
        return run_openclaw_cli(["browser", "--json", "start"], timeout_ms=OPENCLAW_COMMAND_TIMEOUT_MS)
    except Exception as exc:
        print(f"OpenClaw browser baslatilamadi: {exc}")
        return None


def openclaw_browser_open(url, timeout_ms=OPENCLAW_COMMAND_TIMEOUT_MS):
    """Yeni sekmede URL acar ve tab bilgisini dondurur."""
    return run_openclaw_cli(["browser", "--json", "open", url], timeout_ms=timeout_ms)


def openclaw_browser_close(target_id):
    """Sekmeyi kapatir."""
    if not target_id:
        return
    try:
        run_openclaw_cli(["browser", "--json", "close", str(target_id)], timeout_ms=20000)
    except Exception:
        pass


def openclaw_browser_wait(target_id=None, selector=None, text=None, load=None, timeout_ms=20000, time_ms=None):
    """OpenClaw browser wait komutuna ince sarmalayi."""
    args = ["browser", "--json", "wait"]
    if selector:
        args.append(selector)
    if text:
        args.extend(["--text", text])
    if load:
        args.extend(["--load", load])
    if time_ms is not None:
        args.extend(["--time", str(time_ms)])
    if target_id:
        args.extend(["--target-id", str(target_id)])
    args.extend(["--timeout-ms", str(timeout_ms)])
    return run_openclaw_cli(args, timeout_ms=timeout_ms + 5000)


def openclaw_browser_navigate(target_id, url, timeout_ms=OPENCLAW_COMMAND_TIMEOUT_MS):
    """Mevcut sekmeyi verilen URL'ye goturur."""
    args = ["browser", "--json", "navigate", url]
    if target_id:
        args.extend(["--target-id", str(target_id)])
    return run_openclaw_cli(args, timeout_ms=timeout_ms)


def openclaw_browser_evaluate(target_id, fn, timeout_ms=30000):
    """Sayfada JS evaluate eder ve sonuc sonucunu dondurur."""
    args = ["browser", "--json", "evaluate", "--fn", fn]
    if target_id:
        args.extend(["--target-id", str(target_id)])
    result = run_openclaw_cli(args, timeout_ms=timeout_ms)
    return result.get("result", result)


def set_openclaw_linkedin_cookie(li_at):
    """LinkedIn oturum cerezini OpenClaw browser profiline yazar."""
    if not li_at:
        return False
    try:
        run_openclaw_cli(
            ["browser", "--json", "cookies", "set", "li_at", li_at, "--url", "https://www.linkedin.com/"],
            timeout_ms=30000,
        )
        return True
    except Exception as exc:
        print(f"OpenClaw LinkedIn cookie yazilamadi: {exc}")
        return False


def unwrap_search_result_url(url):
    """Arama motoru yönlendirme URL'lerini gerçek hedefe çevirir."""
    clean_url = (url or "").strip()
    if not clean_url:
        return ""

    if clean_url.startswith("//"):
        clean_url = f"https:{clean_url}"

    parsed = urlparse(clean_url)
    host = parsed.netloc.lower()
    query = parse_qs(parsed.query)

    if "bing.com" in host and parsed.path.startswith("/ck/a"):
        target = query.get("u", [""])[0]
        if target.startswith("a1"):
            try:
                encoded = target[2:]
                encoded += "=" * (-len(encoded) % 4)
                return base64.b64decode(encoded).decode("utf-8")
            except Exception:
                pass

    if "duckduckgo.com" in host and parsed.path.startswith("/l/"):
        target = query.get("uddg", [""])[0]
        return unquote(target) if target else clean_url

    return clean_url


def extract_company_name_from_url(url):
    """URL slug'ından okunabilir firma adı çıkarır."""
    parsed = urlparse(url or "")
    segment = parsed.path.strip("/").split("/")[-1] if parsed.path else ""
    segment = re.sub(r"[%_]+", " ", segment)
    segment = segment.replace("-", " ").strip()
    return segment.title() if segment else parsed.netloc.replace("www.", "")


def normalize_company_site_url(url):
    """Derin linkten şirket ana domainine döner."""
    parsed = urlparse(url or "")
    host = parsed.netloc.lower().replace("www.", "")
    if not host:
        return ""

    if host.endswith(".gov") or ".gov." in host or host.endswith(".edu") or ".edu." in host:
        return ""

    if any(host.startswith(f"{prefix}.") for prefix in BAD_SUBDOMAIN_PREFIXES):
        return ""

    scheme = parsed.scheme or "https"
    return f"{scheme}://{parsed.netloc}/"


def looks_like_company_result(title, snippet, url, is_li=False):
    """Şirket sitesi olmayan sonuçları mümkün olduğunca erken eler."""
    haystack = fold_text(f"{title} {snippet} {url}")
    parsed = urlparse(url or "")
    host = parsed.netloc.lower().replace("www.", "")
    path = parsed.path.lower()

    if not is_li and any(token in path for token in BAD_PATH_TOKENS):
        return False

    if any(host.startswith(f"{prefix}.") for prefix in BAD_SUBDOMAIN_PREFIXES):
        return False

    if any(token in haystack for token in QUESTIONISH_TOKENS) and not any(token in haystack for token in COMPANY_HINT_TOKENS):
        return False

    return True


def store_candidate(final_results, title, url, snippet, keyword, sector, location, country):
    """Sonucu puanlayıp sözlüğe ekler."""
    clean_url = unwrap_search_result_url(url)
    if not clean_url or not clean_url.startswith("http") or not is_allowed_domain(clean_url):
        return

    lower_url = clean_url.lower()
    is_li = ("linkedin.com/company/" in lower_url or "linkedin.com/school/" in lower_url)
    is_person = any(x in lower_url for x in ["/in/", "/people/", "/pub/", "/jobs/", "/pulse/", "/search/", "/posts/"])
    if is_person:
        return

    if not is_li:
        clean_url = normalize_company_site_url(clean_url)
        if not clean_url:
            return
        lower_url = clean_url.lower()

    title = (title or "").strip() or extract_company_name_from_url(clean_url)
    snippet = (snippet or "").strip()
    if not looks_like_company_result(title, snippet, clean_url, is_li=is_li):
        return

    score = score_candidate(
        {"title": title, "body": snippet, "href": clean_url},
        keyword,
        sector,
        location,
        country,
    )

    if is_li:
        score += 200
    else:
        score += 15
        if any(token in fold_text(f"{title} {snippet}") for token in COMPANY_HINT_TOKENS):
            score += 10

    if score < 10:
        return

    company_name = title.split("-")[0].split("|")[0].strip() or extract_company_name_from_url(clean_url)
    if len(company_name) < 2:
        return

    existing = final_results.get(clean_url)
    if not existing or score > existing["score"]:
        final_results[clean_url] = {
            "company_name": company_name,
            "website": clean_url,
            "score": score,
            "is_linkedin": is_li,
            "snippet": snippet or f"Firma: {company_name}"
        }


def fetch_bing_results_http(query, country=""):
    """Playwright açılamazsa Bing HTML üzerinden sonuç çeker."""
    c_code = ISO_COUNTRY_MAP.get((country or "").lower(), "US")
    lang = "tr" if c_code == "TR" else "en"

    try:
        resp = HTTP_SESSION.get(
            "https://www.bing.com/search",
            params={"q": query, "setlang": lang, "cc": c_code},
            timeout=12,
        )
        resp.raise_for_status()
    except Exception as exc:
        print(f"HTTP Bing Hata [{query}]: {exc}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    parsed_results = []
    for res in soup.select("li.b_algo")[:15]:
        title_el = res.select_one("h2 a")
        if not title_el:
            continue
        snippet_el = res.select_one("div.b_caption p, .b_lineclamp3")
        parsed_results.append({
            "title": title_el.get_text(" ", strip=True),
            "href": title_el.get("href", ""),
            "body": snippet_el.get_text(" ", strip=True) if snippet_el else "",
        })
    return parsed_results


def fetch_ddg_results_http(query):
    """DuckDuckGo HTML üzerinden sade sonuç çeker."""
    try:
        resp = HTTP_SESSION.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            timeout=12,
        )
        resp.raise_for_status()
    except Exception as exc:
        print(f"HTTP DDG Hata [{query}]: {exc}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    parsed_results = []
    for link in soup.select("a.result__a, a.result-link")[:15]:
        href = link.get("href", "")
        container = link.find_parent(class_="result") or link.parent
        snippet_el = container.select_one(".result__snippet") if container else None
        parsed_results.append({
            "title": link.get_text(" ", strip=True),
            "href": href,
            "body": snippet_el.get_text(" ", strip=True) if snippet_el else "",
        })
    return parsed_results


def score_company_website_match(company_name, title, snippet, url):
    """Belirli bir firma ismi ile sonuc arasindaki yakinligi puanlar."""
    target_tokens = company_token_set(company_name)
    if not target_tokens:
        return 0

    haystack = f"{title} {snippet} {extract_company_name_from_url(url)}"
    haystack_fold = fold_text(haystack)
    haystack_tokens = company_token_set(haystack)
    host_tokens = {
        token for token in re.split(r"[^a-z0-9]+", fold_text(urlparse(url or "").netloc))
        if len(token) >= 3
    }

    overlap = len(target_tokens & haystack_tokens)
    host_overlap = len(target_tokens & host_tokens)
    score = overlap * 24 + host_overlap * 16

    target_name = normalize_company_identity(company_name)
    if target_name and target_name in normalize_company_identity(haystack):
        score += 35

    if any(token in haystack_fold for token in COMPANY_HINT_TOKENS):
        score += 8

    if any(token in haystack_fold for token in QUESTIONISH_TOKENS):
        score -= 18

    return score


def find_company_website(company_name, keyword="", sector="", location="", country=""):
    """Firma adindan resmi web sitesini bulmaya calisir."""
    clean_name = (company_name or "").strip()
    if len(clean_name) < 2:
        return None

    target_tld = TLD_MAP.get((country or "").lower(), "")
    queries = [
        build_query(f"\"{clean_name}\"", country, "official website"),
        build_query(f"\"{clean_name}\"", location, country, "official site"),
        build_query(f"\"{clean_name}\"", keyword, sector, location, country),
        build_query(f"\"{clean_name}\"", "company"),
        build_query(f"\"{clean_name}\"", "firma"),
    ]
    if target_tld:
        queries.append(build_query(f"site:{target_tld}", f"\"{clean_name}\"", "official"))

    best = None
    seen_urls = set()
    for query in queries:
        combined_results = fetch_bing_results_http(query, country) + fetch_ddg_results_http(query)
        for entry in combined_results:
            url = unwrap_search_result_url(entry.get("href", ""))
            lower_url = url.lower()
            if not url or "linkedin.com" in lower_url or not is_allowed_domain(url):
                continue

            normalized_url = normalize_company_site_url(url)
            if not normalized_url or normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)

            title = entry.get("title", "").strip() or extract_company_name_from_url(normalized_url)
            snippet = entry.get("body", "").strip()
            if not looks_like_company_result(title, snippet, normalized_url, is_li=False):
                continue

            score = score_company_website_match(clean_name, title, snippet, normalized_url)
            haystack = fold_text(f"{title} {snippet} {normalized_url}")
            if keyword and fold_text(keyword) in haystack:
                score += 6
            if sector and fold_text(sector) in haystack:
                score += 4
            if location and fold_text(location) in haystack:
                score += 5
            if country and fold_text(country) in haystack:
                score += 5

            if score < 32:
                continue

            candidate = {
                "company_name": clean_name,
                "website": normalized_url,
                "score": score,
                "is_linkedin": False,
                "snippet": snippet or f"Firma: {clean_name}"
            }
            if not best or score > best["score"]:
                best = candidate

        if best and best["score"] >= 80:
            break

    return best


def extract_linkedin_company_website_openclaw(company_url):
    """LinkedIn sirket sayfasindan resmi siteyi cikarmaya calisir."""
    if not company_url:
        return None

    company_tab = None
    try:
        company_tab = openclaw_browser_open(company_url, timeout_ms=OPENCLAW_COMMAND_TIMEOUT_MS)
        target_id = company_tab.get("targetId") or company_tab.get("id")
        if not target_id:
            return None

        openclaw_browser_wait(target_id=target_id, load="domcontentloaded", timeout_ms=15000)
        openclaw_browser_wait(target_id=target_id, time_ms=2500, timeout_ms=5000)

        website_js = r"""() => {
            const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
            const decodeHref = (href) => {
                if (!href) return '';
                try {
                    const parsed = new URL(href, location.href);
                    const redirectTarget = parsed.searchParams.get('url') || parsed.searchParams.get('dest') || parsed.searchParams.get('redir');
                    if (redirectTarget) return decodeURIComponent(redirectTarget);
                    return parsed.href;
                } catch (err) {
                    return '';
                }
            };
            const entries = Array.from(document.querySelectorAll('a[href]')).map((anchor) => {
                const href = decodeHref(anchor.getAttribute('href') || anchor.href || '');
                if (!/^https?:/i.test(href)) return null;
                let parsed;
                try {
                    parsed = new URL(href);
                } catch (err) {
                    return null;
                }
                const host = parsed.hostname.replace(/^www\./i, '').toLowerCase();
                if (!host || host.endsWith('linkedin.com')) return null;
                const text = clean(anchor.textContent) || clean(anchor.getAttribute('aria-label')) || clean(anchor.title);
                const isBad = /^(mailto:|tel:|javascript:)/i.test(href) || /(facebook|instagram|twitter|x\.com|youtube|tiktok)\./i.test(host);
                if (isBad) return null;
                let score = 0;
                if (/(website|visit website|web site|site web|firma sitesi|kurumsal|official)/i.test(text)) score += 60;
                if (parsed.pathname === '/' || parsed.pathname === '') score += 10;
                if (/linkedin\.com\/redir/i.test(anchor.href || '')) score += 12;
                if (text.length > 0 && text.length < 80) score += 6;
                return {
                    url: `${parsed.protocol}//${parsed.host}/`,
                    raw: parsed.href,
                    text,
                    score
                };
            }).filter(Boolean).sort((a, b) => b.score - a.score);

            const summary = clean(document.body?.innerText || '').slice(0, 400);
            return {
                website: entries[0] || null,
                summary
            };
        }"""

        extracted = openclaw_browser_evaluate(target_id, website_js, timeout_ms=20000) or {}
        website = extracted.get("website") if isinstance(extracted, dict) else None
        summary = extracted.get("summary", "") if isinstance(extracted, dict) else ""

        if not website:
            about_url = company_url.rstrip("/") + "/about/"
            openclaw_browser_navigate(target_id, about_url, timeout_ms=OPENCLAW_COMMAND_TIMEOUT_MS)
            openclaw_browser_wait(target_id=target_id, load="domcontentloaded", timeout_ms=15000)
            openclaw_browser_wait(target_id=target_id, time_ms=2500, timeout_ms=5000)
            extracted = openclaw_browser_evaluate(target_id, website_js, timeout_ms=20000) or {}
            website = extracted.get("website") if isinstance(extracted, dict) else None
            summary = summary or (extracted.get("summary", "") if isinstance(extracted, dict) else "")

        if not website:
            return None

        normalized_url = normalize_company_site_url(website.get("url") or website.get("raw") or "")
        if not normalized_url:
            return None

        return {
            "website_url": normalized_url,
            "summary": summary,
            "label": website.get("text", ""),
        }
    except Exception as exc:
        print(f"OpenClaw LinkedIn website cikarimi basarisiz [{company_url}]: {exc}")
        return None
    finally:
        if company_tab:
            openclaw_browser_close(company_tab.get("targetId") or company_tab.get("id"))


def search_linkedin_companies_openclaw(keyword, sector, location="", li_at=None, limit=5):
    """LinkedIn company search sonucunu OpenClaw browser ile toplar."""
    if not li_at:
        os.environ["OPENCLAW_LAST_LINKEDIN_STATUS"] = "skip:no_token"
        return []

    status = ensure_openclaw_browser_started()
    if not status or not status.get("enabled"):
        os.environ["OPENCLAW_LAST_LINKEDIN_STATUS"] = "error:browser_unavailable"
        return []
    if not set_openclaw_linkedin_cookie(li_at):
        os.environ["OPENCLAW_LAST_LINKEDIN_STATUS"] = "error:cookie_set_failed"
        return []

    query = build_query(keyword, sector, location)
    search_url = f"https://www.linkedin.com/search/results/companies/?keywords={quote_plus(query)}"
    search_tab = None
    try:
        search_tab = openclaw_browser_open(search_url, timeout_ms=OPENCLAW_COMMAND_TIMEOUT_MS)
        target_id = search_tab.get("targetId") or search_tab.get("id")
        if not target_id:
            return []

        openclaw_browser_wait(target_id=target_id, load="domcontentloaded", timeout_ms=20000)
        openclaw_browser_wait(target_id=target_id, selector="li.reusable-search__result-container", timeout_ms=20000)

        results_js = f"""() => {{
            const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
            return Array.from(document.querySelectorAll('li.reusable-search__result-container')).map((item, index) => {{
                const link = item.querySelector('a[href*="/company/"], a[href*="/school/"]');
                if (!link) return null;
                const href = (link.href || '').split('?')[0];
                if (!/linkedin\\.com\\/(company|school)\\//i.test(href)) return null;
                if (/(\\/in\\/|\\/people\\/|\\/pub\\/|\\/jobs\\/|\\/pulse\\/|\\/search\\/|\\/posts\\/)/i.test(href)) return null;
                const name = clean(link.textContent).split(' · ')[0];
                if (!name || name.length < 2) return null;
                const subtitleEl = item.querySelector('.entity-result__primary-subtitle, .entity-result__summary');
                return {{
                    company_name: name,
                    linkedin_url: href,
                    title: clean(subtitleEl ? subtitleEl.textContent : ''),
                    score: {max(limit, 5) * 20} - index
                }};
            }}).filter(Boolean).slice(0, {max(limit, 5)});
        }}"""
        extracted_results = openclaw_browser_evaluate(target_id, results_js, timeout_ms=20000)
        if not isinstance(extracted_results, list):
            os.environ["OPENCLAW_LAST_LINKEDIN_STATUS"] = "error:invalid_result"
            return []

        final_results = []
        for row in extracted_results[:limit]:
            company_name = row.get("company_name", "").strip()
            linkedin_url = row.get("linkedin_url", "").split("?")[0]
            if not company_name or not linkedin_url:
                continue

            website_info = extract_linkedin_company_website_openclaw(linkedin_url)
            final_results.append({
                "company_name": company_name,
                "linkedin_url": linkedin_url,
                "website_url": website_info.get("website_url", "") if website_info else "",
                "title": website_info.get("summary", "") if website_info and website_info.get("summary") else row.get("title", ""),
                "score": row.get("score", 0),
            })

        os.environ["OPENCLAW_LAST_LINKEDIN_STATUS"] = f"ok:{len(final_results)}"
        return final_results
    except Exception as exc:
        os.environ["OPENCLAW_LAST_LINKEDIN_STATUS"] = f"error:{str(exc)[:120]}"
        print(f"OpenClaw LinkedIn search hatasi: {exc}")
        return []
    finally:
        if search_tab:
            openclaw_browser_close(search_tab.get("targetId") or search_tab.get("id"))


def search_linkedin_company_pages_http(keyword, sector, location="", country="", limit=5):
    """LinkedIn şirket sayfalarını tarayıcı olmadan arar."""
    queries = [
        build_query("site:linkedin.com/company/", keyword, sector, location, country),
        build_query("site:linkedin.com/company/", sector, keyword, location, country),
        build_query(keyword, sector, location, country, "official linkedin company"),
    ]

    found = {}
    for query in queries:
        for entry in fetch_bing_results_http(query, country) + fetch_ddg_results_http(query):
            url = unwrap_search_result_url(entry.get("href", ""))
            lower_url = url.lower()
            if "linkedin.com/company/" not in lower_url and "linkedin.com/school/" not in lower_url:
                continue
            if any(x in lower_url for x in ["/in/", "/people/", "/pub/", "/jobs/", "/pulse/", "/search/", "/posts/"]):
                continue

            name = entry.get("title", "").split("-")[0].split("|")[0].strip() or extract_company_name_from_url(url)
            if url not in found:
                found[url] = {
                    "company_name": name,
                    "linkedin_url": url.split("?")[0],
                    "title": entry.get("body", ""),
                    "score": 10,
                }

            if len(found) >= limit:
                break
        if len(found) >= limit:
            break

    return list(found.values())[:limit]

def score_candidate(entry, keyword, sector, location, country):
    """Şirketin uygunluğunu puanlar (0-30 arası)."""
    haystack = fold_text(f"{entry.get('title', '')} {entry.get('body', '')} {entry.get('href', '')}").strip()
    if not haystack: return 0
    
    k_fold = fold_text(keyword)
    s_fold = fold_text(sector)
    loc_tokens = [fold_text(t) for t in [location, country] if t]
    
    score = 0
    # Anahtar kelime ve Sektör eşleşmesi (En önemli sinyaller)
    if k_fold and k_fold in haystack: score += 10
    if s_fold and s_fold in haystack: score += 6
    
    # Sanayici/Üretici kelime grupları
    if any(token in haystack for token in INDUSTRY_TOKENS): score += 3
    if any(token in haystack for token in ["manufacturer", "uretim", "uretici", "sanayi", "industrial", "fabrik"]): score += 7
    
    # Lokasyon Puanlaması (Eğer eşleşme varsa BÜYÜK PUAN, yoksa ağır ceza)
    loc_hit = False
    for t in loc_tokens:
        if t in haystack:
            score += 35 # ARTIŞ: Dinamik lokasyon eşleşmesi artık kritik öneme sahip
            loc_hit = True
            
    # Domain bazlı coğrafi kontrol (GLOBAL-GENEL)
    domain = entry.get('href', '').lower()
    c_fold = country.lower().strip()
    is_foreign = c_fold not in ["turkiye", "turkey", "tr"] 
    
    if (".tr" in domain or ".com.tr" in domain) and "linkedin.com" not in domain:
        if is_foreign:
            score -= 60 # Yurt dışı aramalarında Türk sitelerini daha sert yasakla
        else:
            score += 20
            loc_hit = True
            
    # Hedef ülke TLD'sine tam uyum
    target_tld = TLD_MAP.get(c_fold, "")
    if not target_tld and is_foreign:
        c_code = ISO_COUNTRY_MAP.get(c_fold, "").lower()
        if c_code: target_tld = f".{c_code}" 
    if target_tld and domain.endswith(target_tld):
        score += 30 
        loc_hit = True

    # Eğer lokasyon belirtilmiş ama içerikte hiçbir iz yoksa ağır ceza
    if loc_tokens and not loc_hit:
        score -= 30 # ARTIŞ: Sapmaları (Ankara yerine İstanbul gelmesi) engellemek için ceza artırıldı
    
    # KİŞİSEL PROFİL CEZASI (URL bazlı son kontrol)
    if any(x in domain for x in ["/in/", "/pub/", "/people/"]):
        score -= 100 # Şirket arıyoruz, kişileri değil.
        
    return score

# ==========================================
# ARAŞTIRMA FONKSİYONLARI (MOTOR)
# ==========================================

def search_web_companies(keyword, sector, location="", country="", limit=6):
    """Bing üzerinden en sağlam ve engellenemez (CAPTCHA bypass) şekilde şirket arar."""
    target_tld = TLD_MAP.get(country.lower(), "")
    q_loc = f'"{location}"' if location else ""

    web_queries = [
        build_query(keyword, sector, q_loc, country, "official website"),
        build_query(keyword, sector, q_loc, country),
        build_query(keyword, sector, q_loc, country, "company"),
        build_query(keyword, sector, q_loc, country, "firma"),
        build_query(keyword, sector, q_loc, country, "official company website"),
        build_query(keyword, sector, q_loc, country, "kurumsal"),
        build_query(keyword, sector, "manufacturer in", q_loc, country),
        build_query(sector, keyword, "supplier", q_loc, country),
    ]
    if target_tld:
        web_queries.append(build_query(f"site:{target_tld}", keyword, sector, q_loc))
    
    final_results = {}
    
    if not PLAYWRIGHT_DISABLED:
        try:
            with sync_playwright() as p:
                # Bing bot koruması konusunda daha esnek olduğu için Chromium kullanıyoruz
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
                page = context.new_page()
                
                # 1. BÖLÜM: BING ARAMASI (HİBRİT)
                for q in web_queries:
                    if len(final_results) >= (limit + 4): break
                    try:
                        c_code = ISO_COUNTRY_MAP.get(country.lower(), "US")
                        lang_cc = f"&setlang=en&cc={c_code}" if c_code != "TR" else "&setlang=tr&cc=TR"
                        search_url = f"https://www.bing.com/search?q={q.strip()}{lang_cc}"
                        goto_with_fallback(page, search_url, timeout=40000)
                        
                        # Sonuçları ayıkla
                        results = page.query_selector_all('li.b_algo')
                        for res in results[:15]: 
                            title_el = res.query_selector('h2 a')
                            snippet_el = res.query_selector('div.b_caption p, .b_lineclamp3')
                            
                            if title_el:
                                store_candidate(
                                    final_results,
                                    title_el.inner_text().strip(),
                                    title_el.get_attribute("href"),
                                    snippet_el.inner_text() if snippet_el else "",
                                    keyword,
                                    sector,
                                    location,
                                    country,
                                )
                    except Exception as e:
                        print(f"Arama Hatası [{q}]: {str(e)}")
                
                browser.close()
        except Exception as e:
            print(f"Playwright Arama Hatası, HTTP fallback devreye giriyor: {str(e)}")
    else:
        print("Playwright kapali: OPENCLAW_DISABLE_PLAYWRIGHT=1, HTTP fallback kullaniliyor.")

    if len(final_results) < limit:
        for q in web_queries:
            if len(final_results) >= (limit + 4):
                break
            for entry in fetch_bing_results_http(q, country) + fetch_ddg_results_http(q):
                store_candidate(
                    final_results,
                    entry.get("title", ""),
                    entry.get("href", ""),
                    entry.get("body", ""),
                    keyword,
                    sector,
                    location,
                    country,
                )
                if len(final_results) >= (limit + 4):
                    break

    sorted_list = sorted(final_results.values(), key=lambda x: x['score'], reverse=True)
    return sorted_list[:limit]

def read_website_content(url):
    """Bir web sitesinin içeriğini okur ve temizler."""
    if not url: return "Gecersiz link."
    try:
        resp = HTTP_SESSION.get(url, timeout=12)
        resp.raise_for_status()
        content = trafilatura.extract(resp.text, include_comments=False, include_tables=True)
        return content[:3000] if content else "Icerik okunamadi."
    except:
        return "Baglanti hatasi."

def search_linkedin_companies(keyword, sector, location="", li_at=None, limit=5):
    """LinkedIn üzerinden şirket arar (Playwright - Defansif Mod)."""
    query = f"{keyword} {sector} {location}".strip()
    search_url = f"https://www.linkedin.com/search/results/companies/?keywords={query}"

    openclaw_results = search_linkedin_companies_openclaw(keyword, sector, location, li_at=li_at, limit=limit)
    if openclaw_results:
        return openclaw_results

    fallback_results = search_linkedin_company_pages_http(keyword, sector, location, "", limit=limit)
    if fallback_results:
        os.environ["OPENCLAW_LAST_LINKEDIN_STATUS"] = f"http_fallback:{len(fallback_results)}"
    if not li_at:
        return fallback_results

    results = []
    if not PLAYWRIGHT_DISABLED:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36")
                page = context.new_page()
                
                # Oturum Çerezi Ekle
                context.add_cookies([{"name": "li_at", "value": li_at, "domain": ".linkedin.com", "path": "/"}])

                # Once oturumu yerlestir, sonra companies aramasina git.
                goto_with_fallback(page, "https://www.linkedin.com/feed/", timeout=30000)
                if "login" in page.url or "authwall" in page.url:
                    browser.close()
                    return fallback_results

                goto_with_fallback(page, search_url, timeout=40000)
                
                if "login" in page.url or "authwall" in page.url:
                    browser.close()
                    return fallback_results
                    
                # Sonuçların yüklenmesini bekle (Kısa bekleme süresi)
                try:
                    page.wait_for_selector("li.reusable-search__result-container, div.search-results-container", timeout=12000)
                    page.wait_for_timeout(1500)
                    items = page.query_selector_all('li.reusable-search__result-container')
                    
                    for i, item in enumerate(items[:limit]):
                        title_el = item.query_selector('span.entity-result__title-text a')
                        if title_el:
                            name = title_el.inner_text().split("\n")[0].strip()
                            url = title_el.get_attribute("href").split("?")[0]
                            lower_url = url.lower()
                            if "linkedin.com/company/" not in lower_url and "linkedin.com/school/" not in lower_url:
                                continue
                            if any(x in lower_url for x in ["/in/", "/people/", "/pub/", "/jobs/", "/pulse/", "/search/", "/posts/"]):
                                continue
                            desc_el = item.query_selector('div.entity-result__primary-subtitle')
                            results.append({
                                "company_name": name,
                                "linkedin_url": url,
                                "title": desc_el.inner_text().strip() if desc_el else "",
                                "score": 10 - i
                            })
                except:
                    pass # Sonuç bulunamadıysa boş dön
                    
                browser.close()
        except Exception as e:
            print(f"LinkedIn Hata, HTTP fallback devreye giriyor: {str(e)}")
    else:
        print("LinkedIn Playwright kapali: OPENCLAW_DISABLE_PLAYWRIGHT=1, HTTP fallback kullaniliyor.")

    final_results = results if results else fallback_results
    if results:
        os.environ["OPENCLAW_LAST_LINKEDIN_STATUS"] = f"playwright:{len(results)}"
    elif not os.environ.get("OPENCLAW_LAST_LINKEDIN_STATUS"):
        os.environ["OPENCLAW_LAST_LINKEDIN_STATUS"] = "error:no_results"
    return final_results
