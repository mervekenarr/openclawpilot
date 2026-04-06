import os
import json
import re
import urllib.parse
import sys
import asyncio
import requests
import trafilatura
from playwright.sync_api import sync_playwright

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Gereksiz/Haber siteleri listesi
BLOCKED_HOST_TOKENS = [
    "facebook.com", "instagram.com", "x.com", "twitter.com", "youtube.com", "tiktok.com",
    "wikipedia.org", "milliyet.com.tr", "hurriyet.com.tr", "sozcu.com.tr", "sabah.com.tr",
    "cumhuriyet.com.tr", "ensonhaber.com", "haber7.com", "aa.com.tr", "iha.com.tr",
    "dha.com.tr", "haberler.com", "eksisozluk.com", "onedio.com", "medium.com"
]

def is_allowed_domain(url):
    if not url: return False
    domain = url.lower()
    return not any(token in domain for token in BLOCKED_HOST_TOKENS)

def score_candidate(entry, keyword, sector, location, country):
    text = (f"{entry.get('title', '')} {entry.get('body', '')} {entry.get('href', '')}").lower()
    score = 0
    
    # Firma emaresi (Çok önemli)
    corp_indicators = ["ltd", "sti", "a.ş.", "a.s.", "aş.", "holding", "sanayi", "ticaret", "factory", "uretim", "manufacturer", "group", "pazarlama", "lojistik"]
    for token in corp_indicators:
        if token in text: score += 50
        
    # Lokasyon
    if location.lower() in text: score += 40
    if country.lower() in text: score += 20
    # Sektör/Ürün
    if keyword.lower() in text: score += 30
    
    # Haber/Blog cezası (Daha esnek, -300 yerine -50 ve bazılarında tolerans)
    news_tokens = ["haber", "nedir", "nasil", "rehber", "forum", "gazete", "haberleri", "magazine"]
    if any(n in text for n in news_tokens): score -= 50
    if "linkedin.com/company/" in entry.get('href', '').lower(): score += 200
        
    return score

def get_fallback_results(query):
    """Tarayıcı bloklandığında Yahoo Search üzerinden sonuç çeker."""
    results = []
    try:
        url = f"https://search.yahoo.com/search?p={query}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        
        # Yahoo Search HTML Parsing
        links = re.findall(r'href="(https?://[^"]+)"', resp.text)
        links = [l for l in links if 'yahoo.com' not in l and 'microsoft.com' not in l]
        
        # Sadece benzersiz URL'leri al, Yahoo bazen çöp parametreler koyabiliyor
        seen = set()
        for link in links:
            if link not in seen:
                seen.add(link)
                results.append({"title": link.split("/")[-1] or link, "href": link, "body": ""})
                if len(results) >= 10: break
    except: pass
    return results

def search_web_companies(keyword, sector, location="", country="", limit=6):
    final_results = {}
    q_loc = f"{location} {country}".strip()
    
    # Bloklanma ihtimali düşük, kurumsal odaklı sorgular
    queries = [
        f"{keyword} {sector} {q_loc} iletişim",
        f"{keyword} {q_loc} industrial manufacturer"
    ]
    
    for q in queries:
        if len(final_results) >= (limit + 5): break
        
        batch = []
        # Önce Tarayıcı Denemesi (Yahoo)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", ignore_https_errors=True)
                page = ctx.new_page()
                print(f"🔍 Deneniyor (Yahoo): {q}")
                page.goto(f"https://search.yahoo.com/search?p={q}", wait_until="load", timeout=30000)
                items = page.query_selector_all('div.compTitle a')
                for item in items[:10]:
                    try:
                        href = item.get_attribute("href")
                        if href: batch.append({"title": item.inner_text(), "href": href, "body": ""})
                    except: continue
                browser.close()
                if batch: print(f"✅ Tarayıcı üzerinden {len(batch)} sonuç bulundu.")
        except Exception as e:
            print(f"⚠️ Tarayıcı hatası: {e}")
            pass
            
        if not batch:
            print(f"⚡ Fallback motoru çalışıyor: {q}")
            batch = get_fallback_results(q)
            if batch: print(f"✅ Yedek motor üzerinden {len(batch)} sonuç bulundu.")
            
        for item in batch:
            url = item['href']
            if not url or not is_allowed_domain(url) or not url.startswith('http'): continue
            
            if "linkedin.com" in url.lower():
                if "/company/" not in url.lower() and "/school/" not in url.lower(): continue
            
            score = score_candidate(item, keyword, sector, location, country)
            if url not in final_results or score > final_results[url]['score']:
                final_results[url] = {
                    "company_name": item['title'].split("-")[0].split("|")[0].strip(),
                    "website": url, "score": score, "is_linkedin": "/company/" in url.lower(),
                    "snippet": item['title']
                }

    sorted_res = sorted(final_results.values(), key=lambda x: x['score'], reverse=True)
    return sorted_res[:limit]

def read_website_content(url):
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded: return "Hata"
        content = trafilatura.extract(downloaded)
        return content[:3000] if content else "Hata"
    except: return "Hata"

def search_linkedin_companies(keyword, sector, location="", li_at=None, limit=5):
    """Yahoo üzerinden LinkedIn şirketlerini güvenli şekilde çeken bot-dirençli yapı."""
    results = []
    q = f"site:linkedin.com/company/ {keyword} {sector} {location}".strip()
    print(f"🔗 LinkedIn Taraması Başladı: {q}")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)", ignore_https_errors=True)
            page = ctx.new_page()
            page.goto(f"https://search.yahoo.com/search?p={q}", wait_until="load", timeout=30000)
            items = page.query_selector_all('div.compTitle a')
            for item in items[:(limit + 5)]:
                try:
                    href = item.get_attribute("href")
                    title = item.inner_text()
                    if href:
                        unquoted_href = urllib.parse.unquote(href)
                        if "linkedin.com/company/" in unquoted_href:
                            clean_href = re.sub(r'^.*?RU=(https?://[^/]+/company/[^/]+).*$', r'\1', unquoted_href)
                            if "yahoo.com" not in clean_href:
                                results.append({
                                    "company_name": title.split(" - ")[0].split(" | ")[0].strip(),
                                    "linkedin_url": clean_href,
                                    "snippet": title
                                })
                                if len(results) >= limit: break
                except: continue
            browser.close()
    except Exception as e:
        print(f"LinkedIn Çekim Hatası: {str(e)}")
    print(f"🔗 LinkedIn Taraması Tamamlandı, {len(results)} şirket bulundu.")
    return results
