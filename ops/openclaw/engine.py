import os
import re
import sys
import asyncio
import requests
import trafilatura

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

BLOCKED_HOST_TOKENS = [
    "facebook.com", "instagram.com", "x.com", "twitter.com", "youtube.com", "tiktok.com",
    "wikipedia.org", "milliyet.com.tr", "hurriyet.com.tr", "sozcu.com.tr", "sabah.com.tr",
    "cumhuriyet.com.tr", "ensonhaber.com", "haber7.com", "aa.com.tr", "iha.com.tr",
    "dha.com.tr", "haberler.com", "eksisozluk.com", "onedio.com", "medium.com",
    # Dizin / listing siteleri — firma sitesi değil
    "sahibinden.com", "armut.com", "ito.org.tr", "tobb.org.tr", "istanbul.zone",
    "yellowpages", "rehber", "firmarehberi", "sirketrehberi", "beyazsayfa",
    "kobiler.com", "ihracat.com", "pagesdirectory", "hotfrog", "cylex",
    "yandex.com", "google.com", "bing.com"
]

def check_allowed(url):
    if not url: return False
    domain = url.lower()
    return not any(token in domain for token in BLOCKED_HOST_TOKENS)

PARKED_SIGNALS = [
    "domain for sale", "bu domain satılık", "this domain is for sale",
    "parked domain", "buy this domain", "domain satın al",
    "under construction", "coming soon", "yapım aşamasında",
    "godaddy.com", "sedoparking", "parkingcrew", "hugedomains",
    "dan.com", "afternic", "sedo.com"
]

def is_url_alive(url, timeout=8):
    """URL'nin gerçekten aktif bir site olup olmadığını kontrol eder."""
    if "linkedin.com" in url.lower():
        return True
    h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"}
    try:
        r = requests.get(url, timeout=timeout, allow_redirects=True, headers=h)
        if r.status_code >= 400:
            return False
        content_lower = r.text.lower()
        # Parked domain / satılık domain kontrolü
        if any(signal in content_lower for signal in PARKED_SIGNALS):
            return False
        # Çok kısa içerik = boş/hatalı site
        if len(r.text.strip()) < 200:
            return False
        return True
    except:
        return False

def read_website_content(url, linkedin_token=""):
    try:
        if "linkedin.com" in url.lower() and linkedin_token:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
            }
            cookies = {"li_at": linkedin_token}
            resp = requests.get(url, headers=headers, cookies=cookies, timeout=15)
            if resp.status_code == 200:
                content = trafilatura.extract(resp.text)
                return content[:3000] if content else "LinkedIn sayfası okundu ama içerik çıkarılamadı."
            return f"LinkedIn erişim hatası: {resp.status_code}"
        else:
            downloaded = trafilatura.fetch_url(url)
            if not downloaded: return "Hata"
            content = trafilatura.extract(downloaded)
            return content[:3000] if content else "Hata"
    except Exception as e:
        return "Hata"

def openclaw_discover_companies(keyword, sector, location="", country="", limit=8):
    """DuckDuckGo ile gerçek firma ve LinkedIn profili arar."""
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
    q_loc = f"{location} {country}".strip()
    linkedin_results = []
    web_results = []
    seen_urls = set()

    # 1. LinkedIn profil araması
    try:
        li_query = f'site:linkedin.com/company {keyword} {sector} {q_loc}'
        with DDGS() as ddgs:
            for r in ddgs.text(li_query, max_results=10):
                url = r.get("href", "")
                if not url or url in seen_urls: continue
                if "linkedin.com/company" not in url.lower(): continue
                name = r.get("title", "").split(" | ")[0].split(" - ")[0].strip()
                if not name: continue
                seen_urls.add(url)
                linkedin_results.append({
                    "company_name": name,
                    "website": url,
                    "is_linkedin": True,
                    "snippet": r.get("body", "")[:200],
                    "sales_script": "",
                    "score": 100
                })
    except Exception:
        pass

    # 2. Web sitesi araması — canlı siteleri filtrele
    try:
        web_query = f'{keyword} {sector} {q_loc} firma sirket resmi site'
        with DDGS() as ddgs:
            for r in ddgs.text(web_query, max_results=30):
                if len(web_results) >= limit: break
                url = r.get("href", "")
                if not url or url in seen_urls or not check_allowed(url): continue
                if "linkedin.com" in url.lower(): continue
                if not is_url_alive(url): continue  # ölü siteleri ele
                seen_urls.add(url)
                name = r.get("title", "").split(" | ")[0].split(" - ")[0].strip()
                if not name: name = url.split("//")[-1].split("/")[0].replace("www.", "").title()
                web_results.append({
                    "company_name": name,
                    "website": url,
                    "is_linkedin": False,
                    "snippet": r.get("body", "")[:200],
                    "sales_script": "",
                    "score": 100
                })
    except Exception:
        pass

    # LinkedIn ve web sonuçlarını karıştır: önce web, sonra LinkedIn
    half = limit // 2
    results = web_results[:half] + linkedin_results[:half]
    # Kalan slotları doldur
    all_extra = web_results[half:] + linkedin_results[half:]
    results += all_extra[:max(0, limit - len(results))]
    return results[:limit]
