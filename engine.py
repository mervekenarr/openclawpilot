import asyncio
import os
import socket
import sys

import requests
import trafilatura
from playwright.sync_api import sync_playwright


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


BLOCKED_HOST_TOKENS = [
    "facebook.com",
    "instagram.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "tiktok.com",
    "wikipedia.org",
    "milliyet.com.tr",
    "hurriyet.com.tr",
    "sozcu.com.tr",
    "sabah.com.tr",
    "cumhuriyet.com.tr",
    "ensonhaber.com",
    "haber7.com",
    "aa.com.tr",
    "iha.com.tr",
    "dha.com.tr",
    "haberler.com",
    "eksisozluk.com",
    "onedio.com",
    "medium.com",
    "sahibinden.com",
    "armut.com",
    "ito.org.tr",
    "tobb.org.tr",
    "istanbul.zone",
    "yellowpages",
    "rehber",
    "firmarehberi",
    "sirketrehberi",
    "beyazsayfa",
    "kobiler.com",
    "hotfrog",
    "cylex",
    "yandex.com",
    "google.com",
    "bing.com",
]


def check_allowed(url):
    if not url:
        return False
    domain = url.lower()
    return not any(token in domain for token in BLOCKED_HOST_TOKENS)


def is_domain_reachable(url):
    if "linkedin.com" in url.lower():
        return True
    try:
        host = url.split("//")[-1].split("/")[0].split(":")[0]
        socket.setdefaulttimeout(3)
        socket.getaddrinfo(host, None)
        return True
    except Exception:
        return False


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


def search_linkedin_companies(keyword, sector, location, country, token, limit=5):
    """Search LinkedIn company pages directly with Playwright."""
    results = []
    search_query = f"{keyword} {sector}"

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                )
            )
            context.add_cookies(
                [
                    {
                        "name": "li_at",
                        "value": token,
                        "domain": ".linkedin.com",
                        "path": "/",
                    }
                ]
            )

            page = context.new_page()
            encoded_query = requests.utils.quote(search_query)
            search_url = (
                "https://www.linkedin.com/search/results/companies/"
                f"?keywords={encoded_query}&origin=SWITCH_SEARCH_VERTICAL"
            )
            page.goto(search_url, timeout=30000)
            page.wait_for_timeout(4000)

            seen_urls = set()
            cards = page.query_selector_all("a[href*='/company/']")

            for card in cards:
                href = card.get_attribute("href") or ""
                if "/company/" not in href:
                    continue

                clean_url = normalize_linkedin_company_url(href)
                if not clean_url or clean_url in seen_urls:
                    continue
                seen_urls.add(clean_url)

                text = card.inner_text().strip()
                name = text.split("\n")[0].strip()[:80]
                if not name or len(name) < 2:
                    name = clean_url.split("/company/")[-1].strip("/").replace("-", " ").title()

                results.append(
                    {
                        "company_name": name,
                        "website": clean_url,
                        "linkedin_url": clean_url,
                        "is_linkedin": True,
                        "snippet": f"{location} {country} bolgesinde {sector} sektoru",
                        "sales_script": "",
                        "score": 100,
                    }
                )
                if len(results) >= limit:
                    break

            browser.close()
    except Exception:
        pass

    return results


def search_web_companies(keyword, sector, location, country, limit=5):
    """Search official websites and enrich them with a LinkedIn company URL."""
    results = []
    q_loc = f"{location} {country}".strip()

    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        web_query = f"{keyword} {sector} {q_loc} firma sirket resmi site"
        seen = set()
        with DDGS() as ddgs:
            for result in ddgs.text(web_query, max_results=30):
                if len(results) >= limit:
                    break

                url = result.get("href", "")
                if not url or url in seen or not check_allowed(url):
                    continue
                if "linkedin.com" in url.lower():
                    continue
                if not is_domain_reachable(url):
                    continue

                seen.add(url)
                name = result.get("title", "").split(" | ")[0].split(" - ")[0].strip()
                if not name:
                    name = url.split("//")[-1].split("/")[0].replace("www.", "").title()

                linkedin_url = search_linkedin_company_url(name, keyword, sector, location, country)
                results.append(
                    {
                        "company_name": name,
                        "website": url,
                        "linkedin_url": linkedin_url,
                        "is_linkedin": False,
                        "snippet": result.get("body", "")[:200],
                        "sales_script": "",
                        "score": 100,
                    }
                )
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


def openclaw_discover_companies(keyword, sector, location="", country="", limit=8):
    """
    Discovery flow:
    1. Search LinkedIn company pages directly when token exists.
    2. Search official websites and enrich them with LinkedIn company URLs.
    """
    linkedin_token = os.getenv("LINKEDIN_SESSION_TOKEN", "")

    li_limit = limit // 2
    linkedin_results = []
    if linkedin_token:
        linkedin_results = search_linkedin_companies(
            keyword,
            sector,
            location,
            country,
            linkedin_token,
            limit=li_limit,
        )

    web_limit = limit - len(linkedin_results)
    web_results = search_web_companies(keyword, sector, location, country, limit=web_limit)

    return linkedin_results + web_results
