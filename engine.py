import os
import json
import re
import sys
import asyncio
import requests
import trafilatura
from playwright.sync_api import sync_playwright

# Windows üzerinde Playwright ve Asyncio çakışmasını önlemek için Proactor policy ayarı
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# ==========================================
# GÜVENLİK VE FİLTRELEME (AYIRICILAR)
# ==========================================
BLOCKED_HOST_TOKENS = [
    "facebook.com", "instagram.com", "x.com", "twitter.com",
    "youtube.com", "tiktok.com", "wikipedia.org", "amazon.", "hepsiburada.",
    "trendyol.", "n11.", "alibaba.", "aliexpress.", "sahibinden.com",
    "emlakjet.com", "zingat.com", "milliyet.com.tr", "hurriyet.com.tr",
    "sozcu.com.tr", "sabah.com.tr", "cumhuriyet.com.tr", "ensonhaber.com",
    "haber7.com", "letgo.com", "dolap.com"
] # LİNKEDİN ÇIKARILDI: LinkedIn sonuçlarının gelmesi için engeli kaldırdık.

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

def fold_text(text):
    """Karakter temizleme ve normalize etme (Türkçe dahil)."""
    text = (text or "").lower()
    replacements = {'ı': 'i', 'ş': 's', 'ğ': 'g', 'ü': 'u', 'ö': 'o', 'ç': 'c'}
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text

def is_allowed_domain(url):
    """Çöp siteleri ve sosyal medyayı eler."""
    domain = url.lower()
    return not any(token in domain for token in BLOCKED_HOST_TOKENS)

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
    loc_str = f'"{location}" {country}'.strip() if location else country
    target_tld = TLD_MAP.get(country.lower(), "")
    
    # Lokasyonu tırnak içine alarak Bing'i bu kelimeye zorluyoruz (Dinamik)
    q_loc = f'"{location}"' if location else ""
    
    web_queries = [
        f"{keyword} {q_loc} {country} official website",
        f"{keyword} {q_loc} {country}",
        f"{keyword} manufacturer in {q_loc} {country}"
    ]
    li_queries = [
        f"site:linkedin.com/company/ {keyword} {q_loc} {country}",
        f"{keyword} {q_loc} {country} official linkedin company"
    ]
    if target_tld:
        web_queries.append(f"site:{target_tld} {keyword} {q_loc}")
    
    final_results = {}
    
    try:
        with sync_playwright() as p:
            # Bing bot koruması konusunda daha esnek olduğu için Chromium kullanıyoruz
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")
            page = context.new_page()
            
            # 1. BÖLÜM: BING ARAMASI (HİBRİT)
            for q in (li_queries + web_queries):
                if len(final_results) >= (limit + 4): break
                try:
                    c_code = ISO_COUNTRY_MAP.get(country.lower(), "US")
                    lang_cc = f"&setlang=en&cc={c_code}" if c_code != "TR" else "&setlang=tr&cc=TR"
                    search_url = f"https://www.bing.com/search?q={q.strip()}{lang_cc}"
                    page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
                    
                    # Sonuçları ayıkla
                    results = page.query_selector_all('li.b_algo')
                    for res in results[:15]: 
                        title_el = res.query_selector('h2 a')
                        snippet_el = res.query_selector('div.b_caption p, .b_lineclamp3')
                        
                        if title_el:
                            name = title_el.inner_text().strip()
                            url = title_el.get_attribute("href")
                            
                            if not url or not is_allowed_domain(url): continue
                            if not url.startswith('http'): continue
                            
                            domain = url.split("//")[-1].split("/")[0].replace("www.", "").lower()
                            score = score_candidate({"title": name, "body": snippet_el.inner_text() if snippet_el else "", "href": url}, keyword, sector, location, country)
                            
                            # LİNKEDİN ŞİRKET FİLTRESİ (KİŞİLERİ ELER)
                            # /in/, /people/, /pub/, /jobs/ gibi linkler şirket sayfası değildir.
                            is_li = ("linkedin.com/company/" in url.lower() or "linkedin.com/school/" in url.lower())
                            is_person = any(x in url.lower() for x in ["/in/", "/people/", "/pub/", "/jobs/", "/pulse/", "/search/"])
                            
                            if is_person: continue # Kişisel profil veya arama sonuçlarını ele.
                            
                            if is_li: score += 200 # Şirket sayfasını en başa al
                            
                            if url not in final_results or score > final_results[url]['score']:
                                final_results[url] = {
                                    "company_name": name.split("-")[0].split("|")[0].strip(),
                                    "website": url,
                                    "score": score,
                                    "is_linkedin": is_li,
                                    "snippet": snippet_el.inner_text() if snippet_el else f"Firma: {name}"
                                }
                except Exception as e:
                    print(f"Arama Hatası [{q}]: {str(e)}")
            
            # 2. BÖLÜM: DEDICATED LİNKEDİN FALLBACK (DuckDuckGo Lite)
            # Eğer Bing LinkedIn bulamazsa, DDG Lite üzerinden LinkedIn kazıması yap
            for q in li_queries:
                try:
                    resp = requests.get(f"https://html.duckduckgo.com/html/?q={q}", headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, timeout=5)
                    if resp.status_code == 200:
                        # REGEX: Tüm alt alan adlarını ve şirket sayfalarını yakalar.
                        links = re.findall(r'https?://[a-zA-Z0-9.]*linkedin\.com/(?:company|school)/[a-zA-Z0-9\-_%]+', resp.text)
                        for l in list(set(links))[:8]:
                            if l not in final_results:
                                comp_name = l.split("/")[-1].replace("-", " ").capitalize()
                                final_results[l] = {
                                    "company_name": comp_name,
                                    "website": l, "score": 200, "is_linkedin": True,
                                    "snippet": f"LinkedIn Sayfası: {comp_name}"
                                }
                except: pass
            
            browser.close()
    except Exception as e:
        print(f"Hata: {str(e)}")

    sorted_list = sorted(final_results.values(), key=lambda x: x['score'], reverse=True)
    return sorted_list[:limit]

def read_website_content(url):
    """Bir web sitesinin içeriğini okur ve temizler."""
    if not url: return "Gecersiz link."
    try:
        downloaded = trafilatura.fetch_url(url)
        content = trafilatura.extract(downloaded, include_comments=False, include_tables=True)
        return content[:3000] if content else "Icerik okunamadi."
    except:
        return "Baglanti hatasi."

def search_linkedin_companies(keyword, sector, location="", li_at=None, limit=5):
    """LinkedIn üzerinden şirket arar (Playwright - Defansif Mod)."""
    if not li_at:
        return {"error": "li_at token gerekli."}
        
    query = f"{keyword} {sector} {location}".strip()
    search_url = f"https://www.linkedin.com/search/results/companies/?keywords={query}"
    
    results = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36")
            page = context.new_page()
            
            # Oturum Çerezi Ekle
            context.add_cookies([{"name": "li_at", "value": li_at, "domain": ".linkedin.com", "path": "/"}])
            
            # Sayfaya git (Max 20 saniye bekle - takılı kalmamak için)
            page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
            
            if "login" in page.url or "authwall" in page.url:
                browser.close()
                return {"error": "LinkedIn Token gecersiz."}
                
            # Sonuçların yüklenmesini bekle (Kısa bekleme süresi)
            try:
                page.wait_for_selector("div.search-results-container", timeout=10000)
                items = page.query_selector_all('li.reusable-search__result-container')
                
                for i, item in enumerate(items[:limit]):
                    title_el = item.query_selector('span.entity-result__title-text a')
                    if title_el:
                        name = title_el.inner_text().split("\n")[0].strip()
                        url = title_el.get_attribute("href").split("?")[0]
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
        print(f"LinkedIn Hata: {str(e)}")
            
    return results

if __name__ == "__main__":
    # Test
    print("--- Arama Testi (Valves Singapore) ---")
    res = search_web_companies("Valve", "Industrial", "Singapore", "Singapore", limit=2)
    print(json.dumps(res, indent=2))
