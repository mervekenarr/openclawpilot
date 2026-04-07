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

BLOCKED_HOST_TOKENS = [
    "facebook.com", "instagram.com", "x.com", "twitter.com", "youtube.com", "tiktok.com",
    "wikipedia.org", "milliyet.com.tr", "hurriyet.com.tr", "sozcu.com.tr", "sabah.com.tr",
    "cumhuriyet.com.tr", "ensonhaber.com", "haber7.com", "aa.com.tr", "iha.com.tr",
    "dha.com.tr", "haberler.com", "eksisozluk.com", "onedio.com", "medium.com"
]

def check_allowed(url):
    if not url: return False
    domain = url.lower()
    return not any(token in domain for token in BLOCKED_HOST_TOKENS)

def get_fallback_results(query):
    """Yahoo Search üzerinden sonuç çeker."""
    import re, requests
    results = []
    try:
        url = f"https://search.yahoo.com/search?p={query}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        links = re.findall(r'href="(https?://[^"]+)"', resp.text)
        seen = set()
        for link in links:
            if 'yahoo.com' not in link and 'microsoft.com' not in link and link not in seen:
                if check_allowed(link):
                    seen.add(link)
                    results.append({"title": link.split("/")[-1] or "Potansiyel Firma", "website": link, "score": 75, "is_linkedin": "linkedin.com" in link.lower(), "snippet": "Arama motoru üzerinden bulundu."})
                    if len(results) >= 8: break
    except: pass
    return results

def search_web_companies(keyword, sector, location="", country="", limit=6):
    """Doğrudan Google/Yahoo taraması."""
    results = []
    print(f"🔍 Web Taraması Başlıyor: {keyword} in {location}")
    
    # 1. Google Search Fallback
    try:
        from googlesearch import search
        q = f"{keyword} {sector} {location} {country} industrial"
        for url in search(q, num_results=limit):
            if check_allowed(url):
                results.append({
                    "company_name": url.split("//")[-1].split(".")[0].title(),
                    "website": url,
                    "score": 85,
                    "is_linkedin": "linkedin.com" in url.lower(),
                    "snippet": f"{location} bölgesinde faaliyet gösteren firma."
                })
    except: pass
    
    if not results:
        results = get_fallback_results(f"{keyword} {sector} {location}")
        
    return results[:limit]

def read_website_content(url):
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded: return "Hata"
        content = trafilatura.extract(downloaded)
        return content[:3000] if content else "Hata"
    except: return "Hata"

def openclaw_discover_companies(keyword, sector, location="", country="", limit=6):
    """DIRECT OLLAMA CONNECTION - BYPASS GATEWAY"""
    import json, re, requests
    
    # DOĞRUDAN OLLAMA IP
    ollama_url = "http://172.16.41.43:11434/api/chat"
    model_name = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
    
    q_loc = f"{location} {country}".strip()
    prompt = f"""Kriterlere uygun en kaliteli 6-8 sirketi/fabrikai bul ve JSON olarak don.
Kriterler:
- Urun/Keyword: {keyword}
- Sektor: {sector}
- Lokasyon: {q_loc}

Gorevin: 
1. Sektordeki gercek B2B kurumsal firmalari listele.
2. LinkedIn sirket profilini (linkedin.com/company/...) onceliklendir.
3. Donus Formati sadece bu JSON array olsun:
[
  {{
    "company_name": "Firma Adi", 
    "website": "Web URL", 
    "is_linkedin": true/false, 
    "snippet": "Uzmanlik alani ozeti",
    "sales_script": "Kısa bir giris mesaji..."
  }}
]"""

    print(f"📡 Direkt Ollama Ajanı Görevlendiriliyor (IP: 172.16.41.43)")
    
    try:
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.2}
        }
        
        resp = requests.post(ollama_url, json=payload, timeout=300)
        
        if resp.status_code == 200:
            content = resp.json().get("message", {}).get("content", "")
            print(f"📄 RAW CONTENT FROM OLLAMA: {content[:200]}...")
            
            # JSON Ayıklama
            results = []
            try:
                match = re.search(r'\[.*\]', content, re.DOTALL)
                if match:
                    results = json.loads(match.group(0))
            except: pass
            
            if results:
                for res in results:
                    res['score'] = 100
                return results[:limit]

        print("⚠️ Ollama boş döndü veya hata verdi. Web Taraması (Fallback) denenecek...")
    except Exception as e:
        print(f"❌ Ollama Bağlantı Hatası: {e}")
        
    # KESİN SONUÇ GARANTİSİ: WEB TARAMA
    return search_web_companies(keyword, sector, location, country, limit)
