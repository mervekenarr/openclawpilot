import os
import json
import html
import re
import sys
import asyncio
import base64
import time
import shutil
import subprocess
import unicodedata
import xml.etree.ElementTree as ET
import requests
import trafilatura
from playwright.sync_api import sync_playwright
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
from bs4 import BeautifulSoup
try:
    from babel import Locale
    from babel.languages import get_official_languages
except Exception:
    Locale = None

    def get_official_languages(*args, **kwargs):
        return ()

# Windows üzerinde Playwright ve Asyncio çakışmasını önlemek için Proactor policy ayarı
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Playwright varsayilan olarak acik kalir.
# Gerekirse .env veya ortam degiskeni ile OPENCLAW_DISABLE_PLAYWRIGHT=1 yapilarak kapatilabilir.
PLAYWRIGHT_DISABLED = os.getenv("OPENCLAW_DISABLE_PLAYWRIGHT", "").strip() == "1"
PLAYWRIGHT_WAIT_UNTIL = (os.getenv("OPENCLAW_PLAYWRIGHT_WAIT_UNTIL", "networkidle").strip() or "networkidle")
PLAYWRIGHT_RUNTIME_FAILED = False
OPENCLAW_LINKEDIN_BROWSER_ENABLED = os.getenv("OPENCLAW_LINKEDIN_BROWSER", "").strip() == "1"
SEARCH_RESULT_CACHE = {}
QUERY_TRANSLATION_CACHE = {}
DISCOVERED_OLLAMA_MODEL = ""
DISCOVERED_OLLAMA_BASE_URL = ""
DISCOVERED_OLLAMA_FETCHED = False
BRAVE_BACKOFF_UNTIL = 0.0
BRAVE_FAILURE_COUNT = 0
DDG_BACKOFF_UNTIL = 0.0
DDG_FAILURE_COUNT = 0
SEARCH_HTTP_TIMEOUT = 4
VERIFY_HTTP_TIMEOUT = 4
LINKEDIN_HTTP_TIMEOUT = 5
QUERY_TRANSLATION_LLM_ENABLED = os.getenv("OPENCLAW_ENABLE_QUERY_TRANSLATION", "1").strip() != "0"
try:
    QUERY_TRANSLATION_TIMEOUT = max(3, int(os.getenv("OPENCLAW_QUERY_TRANSLATION_TIMEOUT", "8") or "8"))
except Exception:
    QUERY_TRANSLATION_TIMEOUT = 8

# ==========================================
# GÜVENLİK VE FİLTRELEME (AYIRICILAR)
# ==========================================
BLOCKED_HOST_TOKENS = [
    "facebook.com", "instagram.com", "x.com", "twitter.com",
    "youtube.com", "tiktok.com", "wikipedia.org", "amazon.", "hepsiburada.",
    "trendyol.", "n11.", "alibaba.", "aliexpress.", "sahibinden.com",
    "emlakjet.com", "zingat.com", "milliyet.com.tr", "hurriyet.com.tr",
    "sozcu.com.tr", "sabah.com.tr", "cumhuriyet.com.tr", "ensonhaber.com",
    "haber7.com", "haberler.com", "haberturk.com", "ntv.com.tr",
    "cnnturk.com", "ekonomim.com", "dunya.com", "posta.com.tr",
    "webtekno.com", "shiftdelete.net", "chip.com.tr", "letgo.com",
    "dolap.com", "zhihu.com", "quora.com", "reddit.com", "tripadvisor.",
    "britannica.com", "crazygames.com",
    "support.microsoft.com", "learn.microsoft.com"
] # LİNKEDİN ÇIKARILDI: LinkedIn sonuçlarının gelmesi için engeli kaldırdık.

BAD_SUBDOMAIN_PREFIXES = [
    "support", "docs", "doc", "help", "blog", "news", "forum", "answers",
    "learn", "developer", "developers", "community", "kb", "wiki"
]

BAD_PATH_TOKENS = [
    "/question/", "/questions/", "/topic/", "/wiki/", "/article/", "/articles/",
    "/support/", "/help/", "/docs/", "/doc/", "/blog/", "/news/", "/forum/",
    "/kb/", "/tardis/", "/art/", "/press/", "/press-release/", "/newsroom/",
    "/announcement/", "/announcements/", "/haber/", "/haberler/", "/basin/",
    "/duyuru/", "/media/", "/medya/"
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

SELLER_HINT_TOKENS = [
    "manufacturer", "supplier", "distributor", "dealer", "reseller", "wholesaler",
    "vendor", "stockist", "exporter", "integrator", "producer", "oem", "maker",
    "authorized", "dealer", "partner", "bayi", "tedarik", "tedarikci", "satici",
    "satis", "distributoru", "distributoru", "uretim", "uretici", "imalat"
]

ARTICLEISH_TOKENS = [
    "news", "article", "blog", "guide", "what is", "nedir", "how to", "manual",
    "datasheet", "whitepaper", "policy", "forum", "career", "careers", "jobs",
    "job", "press release", "press", "support", "documentation", "docs", "kb",
    "haber", "haberler", "basin", "duyuru", "announcement", "announcements",
    "review", "reviews", "inceleme", "yorum", "rehber", "karsilastirma"
]

NON_COMPANY_HOST_TOKENS = [
    "gov.uk", ".gov", ".edu", "medium.com", "substack.com", "wikipedia.org",
    "support.", "docs.", "help.", "learn.", "forum.", "blog.", "europages.",
    "environmental-expert.", "thomasnet.", "made-in-china.", "exporthub."
]

DIRECTORYISH_TOKENS = [
    "business directory", "supplier directory", "manufacturers directory",
    "manufacturer directory", "company profile", "company listing", "company listings",
    "b2b directory", "b2b marketplace", "marketplace", "buyers guide", "buyer guide",
    "find suppliers", "find supplier", "find manufacturers", "find manufacturer",
    "verified suppliers", "companies and suppliers", "supplier of", "suppliers of"
]

COMPANY_PAGE_HINT_TOKENS = [
    "about us", "about company", "our company", "hakkimizda", "kurumsal",
    "contact us", "iletisim", "products", "urunler", "services", "solutions"
]

NOISY_NAME_TOKENS = [
    "linkedin", "linkedin com", "official site", "official website", "company profile",
    "company page", "search results", "manufacturer", "supplier", "distributor",
    "reseller", "dealer", "homepage", "home page", "products", "services",
    "solutions", "overview", "category", "categories", "industrial", "industry"
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
    "turkiye": ".tr", "turkey": ".tr", "tr": ".tr",
    "germany": ".de", "almanya": ".de", "france": ".fr", "fransa": ".fr",
    "italy": ".it", "italya": ".it", "uk": ".co.uk", "usa": ".com"
}

COUNTRY_ALIAS_MAP = {
    "TR": ["turkiye", "turkey", "tuerkei", "turkei"],
    "DE": ["germany", "almanya", "deutschland", "deutsch"],
    "GB": ["uk", "united kingdom", "england", "britain", "great britain"],
    "US": ["usa", "united states", "america", "us"],
    "FR": ["france", "fransa", "francais"],
    "IT": ["italy", "italya", "italia"],
    "ES": ["spain", "ispanya", "espana"],
    "NL": ["netherlands", "hollanda", "nederland"],
    "PL": ["poland", "polonya", "polska"],
    "CN": ["china", "cin", "zhongguo", "prc"],
}

COUNTRY_QUERY_TERM_MAP = {
    "DE": ["hersteller", "lieferant", "unternehmen", "kontakt", "uber uns", "standorte", "vertriebspartner", "handler"],
    "FR": ["fabricant", "fournisseur", "entreprise", "contact", "a propos", "implantations", "distributeur"],
    "IT": ["produttore", "fornitore", "azienda", "contatti", "chi siamo", "sedi", "distributore"],
    "ES": ["fabricante", "proveedor", "empresa", "contacto", "sobre nosotros", "ubicaciones", "distribuidor"],
    "NL": ["fabrikant", "leverancier", "bedrijf", "contact", "over ons", "locaties", "distributeur"],
    "PL": ["producent", "dostawca", "firma", "kontakt", "o nas", "lokalizacje", "dystrybutor"],
    "TR": ["firma", "sirket", "uretici", "imalatci", "bayi", "tedarikci", "kurumsal", "iletisim"],
}

LANGUAGE_QUERY_TERM_MAP = {
    "en": ["company", "manufacturer", "supplier", "distributor", "dealer", "contact", "about", "products"],
    "tr": ["firma", "sirket", "uretici", "imalatci", "bayi", "tedarikci", "kurumsal", "iletisim"],
    "de": ["hersteller", "lieferant", "unternehmen", "kontakt", "standorte", "handler", "vertrieb"],
    "fr": ["fabricant", "fournisseur", "entreprise", "contact", "distributeur", "implantations"],
    "it": ["produttore", "fornitore", "azienda", "contatti", "distributore", "sedi"],
    "es": ["fabricante", "proveedor", "empresa", "contacto", "distribuidor", "ubicaciones"],
    "nl": ["fabrikant", "leverancier", "bedrijf", "contact", "distributeur", "locaties"],
    "pl": ["producent", "dostawca", "firma", "kontakt", "dystrybutor", "lokalizacje"],
    "pt": ["fabricante", "fornecedor", "empresa", "contato", "distribuidor", "produtos"],
    "ru": ["производитель", "поставщик", "компания", "контакты", "дистрибьютор", "продукция"],
    "zh": ["制造商", "供应商", "公司", "工厂", "联系", "产品"],
    "ja": ["メーカー", "サプライヤー", "会社", "工場", "お問い合わせ", "製品"],
    "ko": ["제조업체", "공급업체", "회사", "공장", "문의", "제품"],
    "ar": ["شركة", "مصنع", "مورد", "اتصال", "منتجات"],
}

PRODUCT_TRANSLATION_MAP = {
    "vana": {"en": ["valve", "industrial valve"], "de": ["ventil"], "fr": ["vanne"], "it": ["valvola"], "es": ["valvula"], "pt": ["valvula"], "pl": ["zawor"], "ru": ["klapan"], "zh": ["阀门"], "ja": ["バルブ"], "ko": ["밸브"]},
    "pompa": {"en": ["pump", "industrial pump"], "de": ["pumpe"], "fr": ["pompe"], "it": ["pompa"], "es": ["bomba"], "pt": ["bomba"], "pl": ["pompa"], "ru": ["nasos"], "zh": ["泵"]},
    "redüktör": {"en": ["gearbox", "speed reducer"], "de": ["getriebe"], "fr": ["reducteur"], "it": ["riduttore"], "es": ["reductor"], "pt": ["redutor"], "pl": ["przekladnia"], "ru": ["reduktor"], "zh": ["减速机"]},
    "reductor": {"en": ["gearbox", "speed reducer"], "de": ["getriebe"], "fr": ["reducteur"], "it": ["riduttore"], "es": ["reductor"], "pt": ["redutor"], "pl": ["przekladnia"], "ru": ["reduktor"], "zh": ["减速机"]},
    "sonsuz dişli": {"en": ["worm gear"], "de": ["schneckengetriebe"], "fr": ["engrenage a vis sans fin"], "it": ["vite senza fine"], "es": ["sinfín"], "pt": ["rosca sem fim"], "pl": ["przekladnia slimakowa"], "ru": ["chervyachnaya peredacha"], "zh": ["蜗轮蜗杆"]},
    "rulman": {"en": ["bearing"], "de": ["lager"], "fr": ["roulement"], "it": ["cuscinetto"], "es": ["rodamiento"], "pt": ["rolamento"], "pl": ["lozysko"], "ru": ["podshipnik"], "zh": ["轴承"]},
    "sensör": {"en": ["sensor"], "de": ["sensor"], "fr": ["capteur"], "it": ["sensore"], "es": ["sensor"], "pt": ["sensor"], "pl": ["czujnik"], "ru": ["sensor"], "zh": ["传感器"]},
    "motor": {"en": ["motor", "electric motor"], "de": ["motor"], "fr": ["moteur"], "it": ["motore"], "es": ["motor"], "pt": ["motor"], "pl": ["silnik"], "ru": ["dvigatel"], "zh": ["电机"]},
    "konveyör": {"en": ["conveyor", "conveyor system"], "de": ["forderband"], "fr": ["convoyeur"], "it": ["trasportatore"], "es": ["transportador"], "pt": ["transportador"], "pl": ["przenosnik"], "ru": ["konveyer"], "zh": ["输送机"]},
    "kompresör": {"en": ["compressor"], "de": ["kompressor"], "fr": ["compresseur"], "it": ["compressore"], "es": ["compresor"], "pt": ["compressor"], "pl": ["kompresor"], "ru": ["kompressor"], "zh": ["压缩机"]},
    "klavye": {"en": ["keyboard", "computer keyboard"], "de": ["tastatur"], "fr": ["clavier"], "it": ["tastiera"], "es": ["teclado"], "pt": ["teclado"], "pl": ["klawiatura"], "ru": ["klaviatura"], "zh": ["键盘"]},
}

SECTOR_TRANSLATION_MAP = {
    "dokum": {"en": ["casting", "foundry"], "de": ["guss", "giesserei"], "fr": ["fonderie"], "it": ["fonderia"], "es": ["fundicion"], "pt": ["fundicao"], "pl": ["odlewnia"], "zh": ["铸造"]},
    "makine": {"en": ["machinery", "machine"], "de": ["maschinenbau", "maschine"], "fr": ["machines"], "it": ["macchinari"], "es": ["maquinaria"], "pt": ["maquinas"], "pl": ["maszyny"], "zh": ["机械"]},
    "sondaj": {"en": ["drilling"], "de": ["bohrung"], "fr": ["forage"], "it": ["perforazione"], "es": ["perforacion"], "pt": ["perfuracao"], "pl": ["wiercenie"], "zh": ["钻井"]},
    "teknoloji": {"en": ["technology"], "de": ["technologie"], "fr": ["technologie"], "it": ["tecnologia"], "es": ["tecnologia"], "pt": ["tecnologia"], "pl": ["technologia"], "zh": ["科技"]},
    "metal": {"en": ["metal"], "de": ["metall"], "fr": ["metal"], "it": ["metallo"], "es": ["metal"], "pt": ["metal"], "pl": ["metal"], "zh": ["金属"]},
    "otomasyon": {"en": ["automation"], "de": ["automation"], "fr": ["automatisation"], "it": ["automazione"], "es": ["automatizacion"], "pt": ["automacao"], "pl": ["automatyka"], "zh": ["自动化"]},
    "beyaz esya": {"en": ["home appliance", "white goods"], "de": ["haushaltsgerate"], "fr": ["electromenager"], "it": ["elettrodomestici"], "es": ["electrodomesticos"], "pt": ["eletrodomesticos"], "pl": ["agd"], "zh": ["家电"]},
    "enerji": {"en": ["energy"], "de": ["energie"], "fr": ["energie"], "it": ["energia"], "es": ["energia"], "pt": ["energia"], "pl": ["energia"], "zh": ["能源"]},
    "kimya": {"en": ["chemical", "chemicals"], "de": ["chemie"], "fr": ["chimie"], "it": ["chimica"], "es": ["quimica"], "pt": ["quimica"], "pl": ["chemia"], "zh": ["化工"]},
    "lojistik": {"en": ["logistics"], "de": ["logistik"], "fr": ["logistique"], "it": ["logistica"], "es": ["logistica"], "pt": ["logistica"], "pl": ["logistyka"], "zh": ["物流"]},
}

TOKEN_TRANSLATION_MAP = {
    "vana": {"en": ["valve"], "de": ["ventil"], "fr": ["vanne"], "it": ["valvola"], "es": ["valvula"], "pt": ["valvula"], "pl": ["zawor"], "ru": ["klapan"], "zh": ["阀门"], "ja": ["バルブ"], "ko": ["밸브"]},
    "pompa": {"en": ["pump"], "de": ["pumpe"], "fr": ["pompe"], "it": ["pompa"], "es": ["bomba"], "pt": ["bomba"], "pl": ["pompa"], "ru": ["nasos"], "zh": ["泵"]},
    "rulman": {"en": ["bearing"], "de": ["lager"], "fr": ["roulement"], "it": ["cuscinetto"], "es": ["rodamiento"], "pt": ["rolamento"], "pl": ["lozysko"], "ru": ["podshipnik"], "zh": ["轴承"]},
    "sonsuz": {"en": ["worm"], "de": ["schnecken"], "fr": ["vis sans fin"], "it": ["vite"], "es": ["sinfin"], "pt": ["sem fim"], "pl": ["slimak"], "zh": ["蜗杆"]},
    "disli": {"en": ["gear"], "de": ["getriebe"], "fr": ["engrenage"], "it": ["ingranaggio"], "es": ["engranaje"], "pt": ["engrenagem"], "pl": ["przekladnia"], "zh": ["齿轮"]},
    "redüktör": {"en": ["gearbox"], "de": ["getriebe"], "fr": ["reducteur"], "it": ["riduttore"], "es": ["reductor"], "pt": ["redutor"], "pl": ["przekladnia"], "zh": ["减速机"]},
    "reductor": {"en": ["gearbox"], "de": ["getriebe"], "fr": ["reducteur"], "it": ["riduttore"], "es": ["reductor"], "pt": ["redutor"], "pl": ["przekladnia"], "zh": ["减速机"]},
    "motor": {"en": ["motor"], "de": ["motor"], "fr": ["moteur"], "it": ["motore"], "es": ["motor"], "pt": ["motor"], "pl": ["silnik"], "zh": ["电机"]},
    "elektrik": {"en": ["electric"], "de": ["elektrisch"], "fr": ["electrique"], "it": ["elettrico"], "es": ["electrico"], "pt": ["eletrico"], "pl": ["elektryczny"], "zh": ["电动"]},
    "elektrikli": {"en": ["electric"], "de": ["elektrisch"], "fr": ["electrique"], "it": ["elettrico"], "es": ["electrico"], "pt": ["eletrico"], "pl": ["elektryczny"], "zh": ["电动"]},
    "hidrolik": {"en": ["hydraulic"], "de": ["hydraulik"], "fr": ["hydraulique"], "it": ["idraulico"], "es": ["hidraulico"], "pt": ["hidraulico"], "pl": ["hydrauliczny"], "zh": ["液压"]},
    "pnomatik": {"en": ["pneumatic"], "de": ["pneumatik"], "fr": ["pneumatique"], "it": ["pneumatico"], "es": ["neumatico"], "pt": ["pneumatico"], "pl": ["pneumatyczny"], "zh": ["气动"]},
    "klavye": {"en": ["keyboard"], "de": ["tastatur"], "fr": ["clavier"], "it": ["tastiera"], "es": ["teclado"], "pt": ["teclado"], "pl": ["klawiatura"], "zh": ["键盘"]},
    "dokum": {"en": ["casting", "foundry"], "de": ["guss"], "fr": ["fonderie"], "it": ["fonderia"], "es": ["fundicion"], "pt": ["fundicao"], "pl": ["odlewnia"], "zh": ["铸造"]},
    "makine": {"en": ["machine", "machinery"], "de": ["maschine"], "fr": ["machine"], "it": ["macchina"], "es": ["maquina"], "pt": ["maquina"], "pl": ["maszyna"], "zh": ["机械"]},
    "sondaj": {"en": ["drilling"], "de": ["bohrung"], "fr": ["forage"], "it": ["perforazione"], "es": ["perforacion"], "pt": ["perfuracao"], "pl": ["wiercenie"], "zh": ["钻井"]},
    "teknoloji": {"en": ["technology"], "de": ["technologie"], "fr": ["technologie"], "it": ["tecnologia"], "es": ["tecnologia"], "pt": ["tecnologia"], "pl": ["technologia"], "zh": ["科技"]},
    "otomasyon": {"en": ["automation"], "de": ["automation"], "fr": ["automatisation"], "it": ["automazione"], "es": ["automatizacion"], "pt": ["automacao"], "pl": ["automatyka"], "zh": ["自动化"]},
    "metal": {"en": ["metal"], "de": ["metall"], "fr": ["metal"], "it": ["metallo"], "es": ["metal"], "pt": ["metal"], "pl": ["metal"], "zh": ["金属"]},
}

COUNTRY_CALLING_CODE_MAP = {
    "TR": ["+90", "0090"],
    "DE": ["+49", "0049"],
    "GB": ["+44", "0044"],
    "US": ["+1", "001"],
    "FR": ["+33", "0033"],
    "IT": ["+39", "0039"],
    "ES": ["+34", "0034"],
    "NL": ["+31", "0031"],
    "PL": ["+48", "0048"],
    "CN": ["+86", "0086"],
}

LOCATION_PAGE_HINT_TOKENS = [
    "contact", "contact us", "contacto", "contatti", "kontakt", "iletisim",
    "location", "locations", "locaties", "standorte", "implantations", "sedi",
    "where to buy", "where-to-buy", "dealer", "dealers", "distributor", "distributors",
    "branch", "branches", "office", "offices", "store", "stores", "showroom",
    "warehouse", "warehouses", "service", "services", "network", "global network",
    "bayi", "bayiler", "sube", "subeler", "ofis", "ofisler", "temsilci", "temsilcilik",
]

LOCATION_ROLE_HINT_TOKENS = [
    "branch", "office", "offices", "dealer", "dealers", "distributor", "distributors",
    "partner", "partners", "warehouse", "service", "showroom", "head office", "headquarter",
    "facility", "plant", "factory", "subsidiary", "country office", "regional office",
    "bayi", "bayiler", "sube", "subeler", "ofis", "depo", "servis", "temsilci", "temsilcilik",
    "niederlassung", "vertretung", "handler", "agence", "filiale", "sede", "rivenditore",
]

OPENCLAW_SITE_BROWSE_READY = None

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}

HTTP_SESSION = requests.Session()
HTTP_SESSION.trust_env = False
HTTP_SESSION.headers.update(DEFAULT_HEADERS)

OPENCLAW_HOME = Path(__file__).resolve().parents[2] / ".openclaw-home"
OPENCLAW_CONFIG_PATH = OPENCLAW_HOME / "openclaw.json"
OPENCLAW_COMMAND_TIMEOUT_MS = 90000
OPENCLAW_ATTACH_PROFILE_DIR = OPENCLAW_HOME / "chrome-profile"

LEGAL_SUFFIX_TOKENS = {
    "as", "a", "s", "a.s", "ltd", "sti", "sti.", "limited", "inc", "llc",
    "corp", "co", "company", "gmbh", "ag", "sa", "plc", "bv", "oy", "ab",
    "group", "holding", "san", "tic", "ve", "anonim", "sirketi", "sirket",
    "corporation"
}

DIRECTORY_HOST_TOKENS = [
    "yellowpages.", "kompass.", "zoominfo.", "rocketreach.", "signalhire.",
    "apollo.io", "dnb.com", "bloomberg.com", "crunchbase.com", "glassdoor.",
    "clutch.co", "craft.co", "cylex.", "hotfrog.", "2findlocal.", "yelp.",
    "mapquest.com", "zaubacorp.com", "pitchbook.com", "tracxn.com", "aihitdata.com",
    "europages.", "environmental-expert.", "thomasnet.", "made-in-china.",
    "globalsources.", "exporthub.", "businesslist.", "yelu.", "industrystock."
]

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


MOJIBAKE_REPLACEMENTS = {
    "Ã§": "ç",
    "Ã‡": "Ç",
    "ÄŸ": "ğ",
    "Äž": "Ğ",
    "Ä±": "ı",
    "Ä°": "İ",
    "Ã¶": "ö",
    "Ã–": "Ö",
    "Ã¼": "ü",
    "Ãœ": "Ü",
    "ÅŸ": "ş",
    "Åž": "Ş",
    "â€™": "'",
    "â€œ": '"',
    "â€": '"',
    "â€“": "-",
    "â€”": "-",
    "Â": "",
}


def repair_text(text):
    """Fix common mojibake patterns from search results and page titles."""
    clean = html.unescape((text or "").replace("\xa0", " "))
    for bad, good in MOJIBAKE_REPLACEMENTS.items():
        clean = clean.replace(bad, good)
    clean = clean.replace("\u200b", "")
    return re.sub(r"\s+", " ", clean).strip()


def fold_text(text):
    """Normalize text for matching while preserving Turkish characters in display."""
    clean = repair_text(text)
    normalized = unicodedata.normalize("NFKD", clean)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return normalized.lower()


def seed_country_maps_from_babel():
    """Expand country lookup tables with Babel so most world countries resolve automatically."""
    if not Locale:
        return
    try:
        locale_en = Locale.parse("en")
        locale_tr = Locale.parse("tr")
    except Exception:
        return

    special_tlds = {"GB": ".co.uk", "US": ".com"}
    for code, english_name in locale_en.territories.items():
        if len(code) != 2 or not code.isalpha():
            continue

        aliases = [english_name, locale_tr.territories.get(code, ""), code.lower()]
        for alias in aliases:
            folded_alias = fold_text(alias)
            if folded_alias:
                ISO_COUNTRY_MAP.setdefault(folded_alias, code)

        alias_bucket = COUNTRY_ALIAS_MAP.setdefault(code, [])
        for alias in aliases:
            alias = (alias or "").strip()
            if alias and alias not in alias_bucket:
                alias_bucket.append(alias)

        cc_tld = special_tlds.get(code, f".{code.lower()}")
        for alias in aliases[:2]:
            folded_alias = fold_text(alias)
            if folded_alias:
                TLD_MAP.setdefault(folded_alias, cc_tld)
        TLD_MAP.setdefault(code.lower(), cc_tld)

        if code not in COUNTRY_QUERY_TERM_MAP:
            terms = []
            try:
                for language in list(get_official_languages(code))[:2]:
                    terms.extend(LANGUAGE_QUERY_TERM_MAP.get(language.lower(), []))
            except Exception:
                pass
            COUNTRY_QUERY_TERM_MAP[code] = list(dict.fromkeys(terms or LANGUAGE_QUERY_TERM_MAP["en"]))


seed_country_maps_from_babel()


def build_query(*parts):
    """Boş parçaları eleyip okunabilir arama cümlesi oluşturur."""
    return " ".join(str(part).strip() for part in parts if str(part).strip())


def country_code_for(country):
    """Normalize user country input to a compact ISO-like code when possible."""
    return ISO_COUNTRY_MAP.get(fold_text(country), "")


def country_alias_tokens(country):
    """Return normalized aliases that may appear on websites for the target country."""
    country_fold = fold_text(country)
    code = country_code_for(country)
    aliases = {country_fold} if country_fold else set()
    if code:
        aliases.update(fold_text(alias) for alias in COUNTRY_ALIAS_MAP.get(code, []))
    return {alias for alias in aliases if alias}


def country_tld_for(country):
    """Resolve a likely country-level domain suffix for search/query boosts."""
    folded = fold_text(country)
    target_tld = TLD_MAP.get(folded, "")
    if target_tld:
        return target_tld
    code = country_code_for(country)
    return f".{code.lower()}" if code else ""


def country_query_terms(country):
    """Country-specific company/seller terms for better foreign-language discovery."""
    code = country_code_for(country)
    terms = list(COUNTRY_QUERY_TERM_MAP.get(code, []))
    if not terms and code:
        try:
            for language in list(get_official_languages(code))[:2]:
                terms.extend(LANGUAGE_QUERY_TERM_MAP.get(language.lower(), []))
        except Exception:
            pass
    if "company" not in terms:
        terms.extend(LANGUAGE_QUERY_TERM_MAP["en"][:4])
    return list(dict.fromkeys(term for term in terms if term))


def country_languages_for(country):
    """Return likely official languages for the requested country."""
    code = country_code_for(country)
    languages = []
    if code:
        try:
            languages.extend(language.lower() for language in get_official_languages(code))
        except Exception:
            pass
    if code == "TR" and "tr" not in languages:
        languages.insert(0, "tr")
    if "en" not in languages:
        languages.append("en")
    return list(dict.fromkeys(lang for lang in languages if lang))


def split_search_phrases(text, max_parts=6):
    """Split comma/slash separated sector phrases into reusable query chunks."""
    clean = repair_text(text)
    if not clean:
        return []
    parts = [clean]
    parts.extend(re.split(r"\s*[,;/|]+\s*", clean))
    result = []
    for part in parts:
        part = re.sub(r"\s+", " ", (part or "").strip(" -|,"))
        if len(part) < 2:
            continue
        if part not in result:
            result.append(part)
        if len(result) >= max_parts:
            break
    return result


def resolve_available_ollama_runtime(preferred_model=""):
    """Prefer a responsive local Ollama runtime and a model that really exists there."""
    global DISCOVERED_OLLAMA_MODEL, DISCOVERED_OLLAMA_BASE_URL, DISCOVERED_OLLAMA_FETCHED

    preferred = (preferred_model or os.getenv("OLLAMA_MODEL", "")).strip()
    if DISCOVERED_OLLAMA_BASE_URL and DISCOVERED_OLLAMA_MODEL:
        return DISCOVERED_OLLAMA_BASE_URL, DISCOVERED_OLLAMA_MODEL
    if DISCOVERED_OLLAMA_FETCHED:
        return DISCOVERED_OLLAMA_BASE_URL or "http://127.0.0.1:11434", DISCOVERED_OLLAMA_MODEL or preferred or "qwen2.5:3b"

    local_base_url = "http://127.0.0.1:11434"
    env_base_url = os.getenv("OLLAMA_BASE_URL", "").rstrip("/")
    candidate_urls = []
    for base_url in [local_base_url, env_base_url, "http://127.0.0.1:11434"]:
        clean_url = (base_url or "").rstrip("/")
        if clean_url and clean_url not in candidate_urls:
            candidate_urls.append(clean_url)

    discovered_models = []
    selected_base_url = ""
    for base_url in candidate_urls:
        try:
            response = HTTP_SESSION.get(f"{base_url}/api/tags", timeout=3)
            if response.status_code != 200:
                continue
            payload = response.json()
            models = [
                (row.get("name") or row.get("model") or "").strip()
                for row in payload.get("models", [])
                if isinstance(row, dict)
            ]
            models = [name for name in models if name]
            if not models:
                continue
            discovered_models = models
            selected_base_url = base_url
            break
        except Exception:
            continue

    DISCOVERED_OLLAMA_FETCHED = True
    DISCOVERED_OLLAMA_BASE_URL = selected_base_url or env_base_url or local_base_url
    if preferred and preferred in discovered_models:
        DISCOVERED_OLLAMA_MODEL = preferred
    elif discovered_models:
        DISCOVERED_OLLAMA_MODEL = discovered_models[0]
    else:
        DISCOVERED_OLLAMA_MODEL = preferred or "qwen2.5:3b"
    return DISCOVERED_OLLAMA_BASE_URL, DISCOVERED_OLLAMA_MODEL


def resolve_available_ollama_model(preferred_model=""):
    """Return only the chosen model name for callers that do not need the base URL."""
    return resolve_available_ollama_runtime(preferred_model)[1]


def _parse_query_translation_terms(raw_text):
    """Parse compact JSON/text translation responses into short search terms."""
    raw = repair_text(raw_text)
    if not raw:
        return []

    payload = None
    match = re.search(r"(\{.*\}|\[.*\])", raw_text or "", re.DOTALL)
    if match:
        try:
            payload = json.loads(match.group(1))
        except Exception:
            payload = None
    elif raw.startswith("{") or raw.startswith("["):
        try:
            payload = json.loads(raw)
        except Exception:
            payload = None

    terms = []
    if isinstance(payload, dict):
        for key in ["terms", "translations", "keywords", "variants", "items"]:
            value = payload.get(key)
            if isinstance(value, list):
                terms.extend(value)
                break
    elif isinstance(payload, list):
        terms.extend(payload)

    if not terms:
        terms.extend(re.split(r"[\n,;|]+", raw))

    cleaned = []
    seen = set()
    for term in terms:
        if not isinstance(term, str):
            continue
        term = repair_text(re.sub(r"^[\-\d\.\)\s]+", "", term)).strip(" -|,.;:")
        if len(term) < 2 or len(term) > 72:
            continue
        term_fold = fold_text(term)
        if not term_fold or term_fold in seen:
            continue
        seen.add(term_fold)
        cleaned.append(term)
        if len(cleaned) >= 6:
            break
    return cleaned


def llm_translate_query_terms(text, country="", context="product"):
    """Translate arbitrary Turkish queries into short country-aware search terms."""
    phrase = repair_text(text)
    if not QUERY_TRANSLATION_LLM_ENABLED or not phrase:
        return []

    country_code = country_code_for(country)
    if country_code in {"", "TR"}:
        return []

    cache_key = (context, country_code or fold_text(country), fold_text(phrase))
    cached = QUERY_TRANSLATION_CACHE.get(cache_key)
    if cached is not None:
        return list(cached)

    target_languages = []
    for lang in country_languages_for(country):
        lang = (lang or "").strip().lower()
        if lang and lang not in target_languages:
            target_languages.append(lang)
        if len(target_languages) >= 2:
            break
    if "en" not in target_languages:
        target_languages.append("en")

    kind_label = "product" if context == "product" else "industry sector"
    prompt = (
        f'Turkish input: "{phrase}"\n'
        f"Country: {repair_text(country) or country_code}\n"
        f"Target language codes: {', '.join(target_languages)}\n"
        f"Type: {kind_label}\n"
        "Task: return 1 to 6 short search terms used by company websites, distributors, dealers or LinkedIn company pages.\n"
        "Rules: translate the meaning, no sentences, no explanations, no numbering, keep terms short.\n"
        'JSON only: {"terms":["term 1","term 2"]}'
    )
    messages = [
        {
            "role": "system",
            "content": "You translate Turkish B2B search phrases into short company-discovery keywords. Return JSON only.",
        },
        {"role": "user", "content": prompt},
    ]

    base_url, model = resolve_available_ollama_runtime()
    attempts = [
        {
            "mode": "generate",
            "url": f"{base_url}/api/generate",
            "headers": {},
            "payload": {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.0, "num_predict": 96, "num_ctx": 1536},
            },
        },
        {
            "mode": "chat",
            "url": f"{base_url}/api/chat",
            "headers": {},
            "payload": {
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.0, "num_predict": 96, "num_ctx": 1536},
            },
        },
    ]

    for attempt in attempts:
        try:
            response = HTTP_SESSION.post(
                attempt["url"],
                json=attempt["payload"],
                headers=attempt["headers"],
                timeout=QUERY_TRANSLATION_TIMEOUT,
            )
            if response.status_code != 200:
                continue
            data = response.json()
            if attempt["mode"] == "generate":
                content = data.get("response", "")
            else:
                content = data.get("message", {}).get("content", "")
            terms = _parse_query_translation_terms(content)
            if terms:
                QUERY_TRANSLATION_CACHE[cache_key] = list(terms)
                return list(terms)
        except Exception:
            continue

    QUERY_TRANSLATION_CACHE[cache_key] = []
    return []


def translated_phrase_variants(text, country="", exact_map=None, max_parts=4, context="product"):
    """Expand Turkish phrases with exact and token-level multilingual variants."""
    phrases = split_search_phrases(text, max_parts=max_parts) or [repair_text(text)]
    languages = country_languages_for(country)
    variants = []

    for phrase in phrases:
        phrase_fold = fold_text(phrase)
        translation_row = (exact_map or {}).get(phrase_fold, {})
        phrase_variants = []
        for language in languages[:3]:
            phrase_variants.extend(translation_row.get(language, []))
        phrase_variants.extend(translation_row.get("en", []))

        tokens = search_term_tokens(phrase, min_len=2)
        if len(tokens) <= 1:
            pass
        else:
            for language in languages[:3]:
                translated_tokens = []
                translated_count = 0
                for token in tokens:
                    token_row = TOKEN_TRANSLATION_MAP.get(token, {})
                    token_options = token_row.get(language, []) or token_row.get("en", [])
                    if token_options:
                        translated_tokens.append(token_options[0])
                        translated_count += 1
                    elif language == "en":
                        translated_tokens.append(token)
                if translated_count >= max(1, len(tokens) - 1) and translated_tokens:
                    phrase_variants.append(" ".join(translated_tokens))

        if country_code_for(country) not in {"", "TR"} and len([item for item in phrase_variants if item]) < 2:
            phrase_variants.extend(llm_translate_query_terms(phrase, country=country, context=context))

        variants.extend(phrase_variants)

    return list(dict.fromkeys(term for term in variants if term))


def translated_keyword_variants(keyword, country=""):
    """Expand Turkish product input with multilingual product variants."""
    return translated_phrase_variants(
        keyword,
        country=country,
        exact_map=PRODUCT_TRANSLATION_MAP,
        max_parts=4,
        context="product",
    )


def translated_sector_variants(sector, country=""):
    """Expand Turkish sector input with multilingual sector variants."""
    return translated_phrase_variants(
        sector,
        country=country,
        exact_map=SECTOR_TRANSLATION_MAP,
        max_parts=5,
        context="sector",
    )


def best_product_signal_score(keyword, text, country=""):
    """Measure product match using both original and translated product terms."""
    score = product_signal_score(keyword, text)
    haystack = fold_text(text)
    for variant in translated_keyword_variants(keyword, country):
        variant_fold = fold_text(variant)
        if not variant_fold:
            continue
        if variant_fold in haystack:
            score = max(score, 24 if " " in variant_fold else 18)
    return score


def country_location_tokens(country):
    """Signals that often prove country presence on the website itself."""
    code = country_code_for(country)
    tokens = set(country_alias_tokens(country))
    if code:
        tokens.update(token.lower() for token in COUNTRY_CALLING_CODE_MAP.get(code, []))
        tokens.add(f"/{code.lower()}/")
        tokens.add(f"-{code.lower()}/")
        tokens.add(f"lang={code.lower()}")
        tokens.add(f"locale={code.lower()}")
    target_tld = country_tld_for(country)
    if target_tld:
        tokens.add(target_tld)
    return {token for token in tokens if token}


def clean_company_name(name):
    """Arama motoru başlıklarından temiz firma adı üretir."""
    text = (name or "").strip()
    if not text:
        return ""
    text = re.split(r"\s+[|•·]\s+|\s+-\s+", text, maxsplit=1)[0].strip()
    return re.sub(r"\s+", " ", text)


def is_plausible_company_name(name):
    """Şirket adı gibi görünmeyen şema / sınıf isimlerini eler."""
    text = (name or "").strip()
    low = text.lower()
    if not text:
        return False
    if low.startswith("com.linkedin") or low.startswith("urn:li:"):
        return False
    if text.count(".") >= 2:
        return False
    if any(token in low for token in ["$type", "validationmetadata", "graphql", "collectionresponse", "voyager.dash"]):
        return False
    return True


def is_linkedin_company_url(url):
    """LinkedIn şirket / okul URL'lerini ayıklar."""
    lower_url = (url or "").lower()
    return "linkedin.com/company/" in lower_url or "linkedin.com/school/" in lower_url


def normalize_linkedin_company_url(url):
    """LinkedIn entity URL'lerini tek biçime indirger."""
    clean_url = unwrap_search_result_url(url)
    if not clean_url:
        return ""

    try:
        parsed = urlparse(clean_url)
    except Exception:
        return ""

    if "linkedin.com" not in parsed.netloc.lower():
        return ""

    match = re.search(r"/(company|school)/([^/?#]+)/?", parsed.path, re.IGNORECASE)
    if not match:
        return ""

    entity_type = match.group(1).lower()
    slug = match.group(2).strip()
    if not slug:
        return ""

    return f"https://www.linkedin.com/{entity_type}/{slug}/"


def host_is_directory(url):
    """Firma sitesi yerine rehber/dizin/profil toplayıcısı olan host'ları ayıklar."""
    host = urlparse(url or "").netloc.lower().replace("www.", "")
    return any(token in host for token in DIRECTORY_HOST_TOKENS)


def url_looks_like_asset(url):
    """PDF / görsel / dosya uzantılarını firma sitesi olarak seçme."""
    path = urlparse(url or "").path.lower()
    return any(
        path.endswith(ext)
        for ext in [".pdf", ".jpg", ".jpeg", ".png", ".svg", ".zip", ".doc", ".docx", ".xls", ".xlsx"]
    )


def linkedin_status_label(prefix, detail=""):
    """Kısa ve okunabilir durum etiketi üretir."""
    return f"{prefix}:{detail}" if detail else prefix


def can_use_playwright():
    """Bu oturumda Playwright kullanılabilir mi?"""
    return not PLAYWRIGHT_DISABLED and not PLAYWRIGHT_RUNTIME_FAILED


def mark_playwright_failed(exc):
    """Playwright bir kez patlarsa oturum için kapat."""
    global PLAYWRIGHT_RUNTIME_FAILED
    PLAYWRIGHT_RUNTIME_FAILED = True
    print(f"Playwright runtime kapatildi: {exc}")


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


def resolve_openclaw_command():
    """Windows PATH farkliliklarinda OpenClaw CLI yolunu bul."""
    candidates = []

    env_candidate = os.getenv("OPENCLAW_BIN", "").strip()
    if env_candidate:
        candidates.append(env_candidate)

    for name in ["openclaw", "openclaw.cmd", "openclaw.ps1"]:
        resolved = shutil.which(name)
        if resolved:
            candidates.append(resolved)

    appdata = os.getenv("APPDATA", "")
    if appdata:
        candidates.extend([
            os.path.join(appdata, "npm", "openclaw.cmd"),
            os.path.join(appdata, "npm", "openclaw"),
            os.path.join(appdata, "npm", "openclaw.ps1"),
        ])

    seen = set()
    for candidate in candidates:
        if not candidate:
            continue
        normalized = os.path.normcase(os.path.abspath(candidate))
        if normalized in seen:
            continue
        seen.add(normalized)
        if os.path.exists(candidate):
            return candidate

    return "openclaw"


def load_openclaw_config():
    """OpenClaw config dosyasini güvenli biçimde oku."""
    if not OPENCLAW_CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(OPENCLAW_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def openclaw_browser_runtime(status=None):
    """Attach/browser bootstrap için gerekli runtime ayarlarini topla."""
    status = status or {}
    cfg = load_openclaw_config()
    browser_cfg = cfg.get("browser", {}) if isinstance(cfg.get("browser"), dict) else {}
    profiles_cfg = browser_cfg.get("profiles", {}) if isinstance(browser_cfg.get("profiles"), dict) else {}
    profile_name = str(status.get("profile") or "openclaw")
    profile_cfg = profiles_cfg.get(profile_name, {}) if isinstance(profiles_cfg.get(profile_name), dict) else {}

    cdp_port = status.get("cdpPort") or profile_cfg.get("cdpPort") or browser_cfg.get("cdpPort") or 18800
    try:
        cdp_port = int(cdp_port)
    except Exception:
        cdp_port = 18800

    executable_path = (
        status.get("executablePath")
        or browser_cfg.get("executablePath")
        or status.get("detectedExecutablePath")
        or ""
    )
    if executable_path and not os.path.exists(executable_path):
        executable_path = ""

    attach_only = bool(
        status.get("attachOnly")
        or profile_cfg.get("attachOnly")
        or browser_cfg.get("attachOnly")
    )

    return {
        "profile_name": profile_name,
        "cdp_port": cdp_port,
        "executable_path": executable_path,
        "attach_only": attach_only,
    }


def openclaw_cdp_http_ready(cdp_port):
    """Chrome debug port cevap veriyor mu?"""
    try:
        resp = HTTP_SESSION.get(f"http://127.0.0.1:{int(cdp_port)}/json/version", timeout=1.5)
        return resp.ok and "webSocketDebuggerUrl" in (resp.text or "")
    except Exception:
        return False


def start_openclaw_attach_browser(status=None):
    """AttachOnly modunda OpenClaw'ın baglanacagi Chrome'u dogrudan baslat."""
    runtime = openclaw_browser_runtime(status)
    if not runtime.get("attach_only"):
        return False

    cdp_port = runtime.get("cdp_port", 18800)
    if openclaw_cdp_http_ready(cdp_port):
        return True

    executable_path = runtime.get("executable_path", "")
    if not executable_path:
        print("OpenClaw attach browser yolu bulunamadi.")
        return False

    OPENCLAW_ATTACH_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        executable_path,
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={OPENCLAW_ATTACH_PROFILE_DIR}",
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-popup-blocking",
    ]

    try:
        popen_kwargs = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = (
                getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
        subprocess.Popen(cmd, **popen_kwargs)
    except Exception as exc:
        print(f"OpenClaw attach browser acilamadi: {exc}")
        return False

    for _ in range(20):
        time.sleep(0.5)
        if openclaw_cdp_http_ready(cdp_port):
            return True
    return False


def run_openclaw_cli(args, timeout_ms=OPENCLAW_COMMAND_TIMEOUT_MS, expect_json=True):
    """OpenClaw CLI komutunu JSON veya metin cikti ile calistirir."""
    command = resolve_openclaw_command()
    completed = subprocess.run(
        [command, *args],
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
    if status.get("running") or status.get("cdpReady"):
        return status
    runtime = openclaw_browser_runtime(status)
    if runtime.get("attach_only"):
        if start_openclaw_attach_browser(status):
            refreshed = openclaw_browser_available()
            if refreshed and (refreshed.get("running") or refreshed.get("cdpReady")):
                return refreshed
        print("OpenClaw attach browser hazir degil.")
        return None
    try:
        return run_openclaw_cli(["browser", "--json", "start"], timeout_ms=OPENCLAW_COMMAND_TIMEOUT_MS)
    except Exception as exc:
        if "spawn EPERM" in str(exc) and start_openclaw_attach_browser(status):
            refreshed = openclaw_browser_available()
            if refreshed and (refreshed.get("running") or refreshed.get("cdpReady")):
                return refreshed
        print(f"OpenClaw browser baslatilamadi: {exc}")
        return None


def run_openclaw_browser_cli(args, timeout_ms=OPENCLAW_COMMAND_TIMEOUT_MS, expect_json=True):
    """Browser komutlarini attach/start fallback ile güvenli sekilde calistir."""
    global OPENCLAW_SITE_BROWSE_READY
    status = ensure_openclaw_browser_started()
    if not status:
        raise RuntimeError("OpenClaw browser hazir degil")
    try:
        return run_openclaw_cli(args, timeout_ms=timeout_ms, expect_json=expect_json)
    except Exception as exc:
        message = str(exc).lower()
        if "not running" in message or "attachonly" in message or "cdp" in message:
            OPENCLAW_SITE_BROWSE_READY = None
            status = ensure_openclaw_browser_started()
            if status:
                return run_openclaw_cli(args, timeout_ms=timeout_ms, expect_json=expect_json)
        raise


def openclaw_browser_open(url, timeout_ms=OPENCLAW_COMMAND_TIMEOUT_MS):
    """Yeni sekmede URL acar ve tab bilgisini dondurur."""
    return run_openclaw_browser_cli(["browser", "--json", "open", url], timeout_ms=timeout_ms)


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
    return run_openclaw_browser_cli(args, timeout_ms=timeout_ms + 5000)


def openclaw_browser_navigate(target_id, url, timeout_ms=OPENCLAW_COMMAND_TIMEOUT_MS):
    """Mevcut sekmeyi verilen URL'ye goturur."""
    args = ["browser", "--json", "navigate", url]
    if target_id:
        args.extend(["--target-id", str(target_id)])
    return run_openclaw_browser_cli(args, timeout_ms=timeout_ms)


def openclaw_browser_evaluate(target_id, fn, timeout_ms=30000):
    """Sayfada JS evaluate eder ve sonuc sonucunu dondurur."""
    args = ["browser", "--json", "evaluate", "--fn", fn]
    if target_id:
        args.extend(["--target-id", str(target_id)])
    result = run_openclaw_browser_cli(args, timeout_ms=timeout_ms)
    return result.get("result", result)


def openclaw_browser_capture_page(target_id, timeout_ms=20000):
    """Basit bir HTML/text snapshot alir; parser'ı zorlayan JS kullanmaz."""
    snapshot_js = """function () {
        return {
            url: location.href,
            title: document.title || '',
            html: document.documentElement ? document.documentElement.outerHTML : '',
            text: document.body && document.body.innerText ? document.body.innerText : ''
        };
    }"""
    result = openclaw_browser_evaluate(target_id, snapshot_js, timeout_ms=timeout_ms)
    if isinstance(result, dict):
        return result
    return {
        "url": "",
        "title": "",
        "html": str(result or ""),
        "text": "",
    }


def openclaw_site_browse_ready():
    """Memoize whether OpenClaw site crawling is actually usable in this runtime."""
    global OPENCLAW_SITE_BROWSE_READY
    if OPENCLAW_SITE_BROWSE_READY is True:
        return OPENCLAW_SITE_BROWSE_READY

    status = ensure_openclaw_browser_started()
    OPENCLAW_SITE_BROWSE_READY = bool(
        status and (status.get("running") or status.get("pid") or status.get("cdpReady"))
    )
    return OPENCLAW_SITE_BROWSE_READY


def openclaw_fetch_page_snapshot(url, require_host=""):
    """Fetch page text and links via OpenClaw when the browser can be started."""
    if not openclaw_site_browse_ready():
        return None

    opened = None
    try:
        opened = openclaw_browser_open(url, timeout_ms=OPENCLAW_COMMAND_TIMEOUT_MS)
        target_id = opened.get("targetId") or opened.get("id")
        if not target_id:
            return None

        openclaw_browser_wait(target_id=target_id, load="domcontentloaded", timeout_ms=15000)
        openclaw_browser_wait(target_id=target_id, time_ms=1800, timeout_ms=4000)

        snapshot_js = r"""() => {
            const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
            const toAbs = (href) => {
                try {
                    return new URL(href, location.href).href;
                } catch (err) {
                    return '';
                }
            };
            const links = Array.from(document.querySelectorAll('a[href]')).map((anchor) => ({
                url: toAbs(anchor.getAttribute('href') || anchor.href || ''),
                text: clean(anchor.textContent || anchor.getAttribute('aria-label') || anchor.title || ''),
            })).filter((row) => row.url && /^https?:/i.test(row.url)).slice(0, 160);
            const locationBlocks = Array.from(document.querySelectorAll(
                'address, footer, [class*="contact"], [class*="location"], [class*="office"], [class*="branch"], [class*="dealer"], [class*="distributor"], [id*="contact"], [id*="location"], [id*="office"], [id*="branch"], [itemprop="address"], [itemprop="addressCountry"]'
            )).map((node) => clean(node.innerText)).filter(Boolean).slice(0, 12);
            const meta = Array.from(document.querySelectorAll('meta[name], meta[property]'))
                .map((node) => clean(`${node.getAttribute('name') || node.getAttribute('property') || ''} ${node.getAttribute('content') || ''}`))
                .filter(Boolean)
                .slice(0, 60);
            const jsonld = Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
                .map((node) => clean(node.textContent || ''))
                .filter(Boolean)
                .slice(0, 10);
            return {
                url: location.href,
                title: clean(document.title),
                text: clean(document.body?.innerText || '').slice(0, 4200),
                lang: clean(document.documentElement?.lang || ''),
                locationText: clean([...locationBlocks, ...meta, ...jsonld].join(' ')).slice(0, 2200),
                links,
            };
        }"""

        snapshot = openclaw_browser_evaluate(target_id, snapshot_js, timeout_ms=25000) or {}
        final_url = snapshot.get("url", "") or url
        final_host = urlparse(final_url).netloc.lower().replace("www.", "")
        if require_host and final_host != require_host:
            return None
        if not snapshot.get("title") and not snapshot.get("text"):
            return None
        return snapshot
    except Exception:
        return None
    finally:
        if opened:
            openclaw_browser_close(opened.get("targetId") or opened.get("id"))


def set_openclaw_linkedin_cookie(li_at):
    """LinkedIn oturum cerezini OpenClaw browser profiline yazar."""
    if not li_at:
        return False
    try:
        run_openclaw_browser_cli(
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

    if "linkedin.com" in host:
        return ""

    if host.endswith(".gov") or ".gov." in host or host.endswith(".edu") or ".edu." in host:
        return ""

    if any(host.startswith(f"{prefix}.") for prefix in BAD_SUBDOMAIN_PREFIXES):
        return ""

    if host_is_directory(url) or url_looks_like_asset(url):
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


def looks_like_article_or_info_page(title, snippet, url):
    """Haber, makale, dokuman veya resmi bilgi sayfalarını eler."""
    haystack = fold_text(f"{title} {snippet} {url}")
    host = urlparse(url or "").netloc.lower().replace("www.", "")
    path = urlparse(url or "").path.lower()
    if any(token in host for token in NON_COMPANY_HOST_TOKENS):
        return True
    if any(token in path for token in BAD_PATH_TOKENS):
        return True
    return any(token in haystack for token in ARTICLEISH_TOKENS)


def seller_intent_score(text):
    """Metnin satıcı/üretici niyetini puanlar."""
    haystack = fold_text(text)
    score = 0
    if any(token in haystack for token in SELLER_HINT_TOKENS):
        score += 20
    if any(token in haystack for token in COMPANY_HINT_TOKENS):
        score += 12
    if any(token in haystack for token in INDUSTRY_TOKENS):
        score += 8
    if looks_like_article_or_info_page("", haystack, haystack):
        score -= 40
    return score


def verify_company_homepage(candidate, keyword, sector, location="", country=""):
    """Aday domainin gerçekten şirket sitesi olup olmadığını kontrol eder."""
    website_url = normalize_company_site_url(candidate.get("website", ""))
    if not website_url:
        return None
    if looks_like_article_or_info_page(candidate.get("company_name", ""), candidate.get("snippet", ""), website_url):
        return None

    try:
        resp = HTTP_SESSION.get(website_url, timeout=10, allow_redirects=True)
        resp.raise_for_status()
    except Exception:
        return None

    final_url = normalize_company_site_url(resp.url or website_url)
    if not final_url or looks_like_article_or_info_page(candidate.get("company_name", ""), candidate.get("snippet", ""), final_url):
        return None

    html_doc = resp.text or ""
    soup = BeautifulSoup(html_doc, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    body_text = trafilatura.extract(html_doc, include_comments=False, include_tables=False) or soup.get_text(" ", strip=True)
    body_text = " ".join(body_text.split())[:1800]

    combined = f"{candidate.get('company_name', '')} {candidate.get('snippet', '')} {title} {body_text} {final_url}"
    score = seller_intent_score(combined)
    k_fold = fold_text(keyword)
    s_fold = fold_text(sector)
    loc_tokens = [fold_text(t) for t in [location, country] if t]

    if k_fold and k_fold in fold_text(combined):
        score += 18
    if s_fold and s_fold in fold_text(combined):
        score += 10
    if any(token in fold_text(combined) for token in loc_tokens):
        score += 8
    if final_url.endswith(".tr/") or ".com.tr/" in final_url:
        score += 6
    if looks_like_article_or_info_page(title, body_text[:300], final_url):
        score -= 60

    if score < 24:
        return None

    verified = dict(candidate)
    verified["website"] = final_url
    verified["score"] = candidate.get("score", 0) + score
    verified["snippet"] = title or candidate.get("snippet", "") or body_text[:220]
    return verified


def store_candidate(final_results, title, url, snippet, keyword, sector, location, country):
    """Sonucu puanlayıp sözlüğe ekler."""
    original_url = unwrap_search_result_url(url)
    if not original_url or not original_url.startswith("http") or not is_allowed_domain(original_url):
        return

    clean_url = original_url
    lower_url = clean_url.lower()
    is_li = is_linkedin_company_url(lower_url)
    is_person = any(x in lower_url for x in ["/in/", "/people/", "/pub/", "/jobs/", "/pulse/", "/search/", "/posts/"])
    if is_person:
        return

    if is_li:
        clean_url = normalize_linkedin_company_url(clean_url)
        if not clean_url:
            return
    else:
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

    if score < -5:
        return

    company_name = clean_company_name(title) or extract_company_name_from_url(clean_url)
    if len(company_name) < 2:
        return

    existing = final_results.get(clean_url)
    if not existing or score > existing["score"]:
        final_results[clean_url] = {
            "company_name": company_name,
            "website": clean_url,
            "source_url": original_url,
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
            timeout=SEARCH_HTTP_TIMEOUT,
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
    if parsed_results:
        return parsed_results

    try:
        rss_resp = HTTP_SESSION.get(
            "https://www.bing.com/search",
            params={"q": query, "setlang": lang, "cc": c_code, "format": "rss"},
            timeout=SEARCH_HTTP_TIMEOUT,
        )
        rss_resp.raise_for_status()
        root = ET.fromstring(rss_resp.text)
    except Exception as exc:
        print(f"HTTP Bing RSS Hata [{query}]: {exc}")
        return []

    rss_results = []
    for item in root.findall("./channel/item")[:15]:
        rss_results.append({
            "title": (item.findtext("title") or "").strip(),
            "href": (item.findtext("link") or "").strip(),
            "body": (item.findtext("description") or "").strip(),
        })
    return rss_results


def fetch_brave_results_http(query):
    """Brave Search üzerinden sonuç çeker."""
    try:
        resp = HTTP_SESSION.get(
            "https://search.brave.com/search",
            params={"q": query},
            timeout=SEARCH_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
    except Exception as exc:
        print(f"HTTP Brave Hata [{query}]: {exc}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    parsed_results = []
    for card in soup.select('div[data-type="web"]')[:15]:
        title_el = card.select_one("a.title, a.svelte-14r20fy.l1, a[href^='http']")
        if not title_el:
            continue
        href = title_el.get("href", "").strip()
        if not href.startswith("http"):
            continue
        title = title_el.get_text(" ", strip=True)
        if not title:
            title = card.get_text(" ", strip=True)[:120]
        desc_parts = [node.get_text(" ", strip=True) for node in card.select(".description")[:2]]
        parsed_results.append({
            "title": title,
            "href": href,
            "body": " ".join(part for part in desc_parts if part).strip(),
        })
    return parsed_results


def fetch_ddg_results_http(query):
    """DuckDuckGo HTML üzerinden sade sonuç çeker."""
    try:
        resp = HTTP_SESSION.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            timeout=max(3, SEARCH_HTTP_TIMEOUT - 1),
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


def candidate_domain_suffixes(country=""):
    """Ülkeye göre denenecek alan adı son eklerini üretir."""
    c_fold = fold_text(country)
    suffixes = []
    target_tld = TLD_MAP.get(c_fold, "")
    if target_tld:
        suffixes.append(target_tld)
        if target_tld == ".tr":
            suffixes.append(".com.tr")
    elif c_fold in {"turkiye", "turkey", "tr"}:
        suffixes.extend([".com.tr", ".tr"])

    for fallback in [".com", ".net", ".org"]:
        if fallback not in suffixes:
            suffixes.append(fallback)
    return suffixes


def guess_company_website(company_name, country=""):
    """Firma adından olası domain'leri deneyerek resmi siteyi bulmaya çalışır."""
    tokens = [token for token in normalize_company_identity(company_name).split() if len(token) >= 2]
    if not tokens:
        return None

    base_names = []
    joined = "".join(tokens)
    hyphenated = "-".join(tokens)
    for candidate in [joined, hyphenated]:
        if candidate and candidate not in base_names:
            base_names.append(candidate)

    if len(tokens) >= 2:
        compact_pair = "".join(tokens[:2])
        hyphen_pair = "-".join(tokens[:2])
        for candidate in [compact_pair, hyphen_pair]:
            if candidate and candidate not in base_names:
                base_names.append(candidate)

    best = None
    for base_name in base_names[:6]:
        for suffix in candidate_domain_suffixes(country):
            url = f"https://{base_name}{suffix}/"
            try:
                resp = HTTP_SESSION.get(url, timeout=6, allow_redirects=True)
            except Exception:
                continue

            final_url = normalize_company_site_url(resp.url or url)
            if not final_url or resp.status_code >= 400:
                continue

            html = resp.text or ""
            soup = BeautifulSoup(html, "html.parser")
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            snippet = soup.get_text(" ", strip=True)[:400]
            score = score_company_website_match(company_name, title, snippet, final_url) + 20
            if suffix in {".com.tr", ".tr"}:
                score += 6

            if score < 34:
                continue

            candidate = {
                "company_name": clean_company_name(company_name) or company_name,
                "website": final_url,
                "score": score,
                "is_linkedin": False,
                "snippet": title or snippet or f"Firma: {company_name}",
            }
            if not best or candidate["score"] > best["score"]:
                best = candidate

    return best


def build_http_session(li_at=""):
    """Varsayılan başlıklarla yeni HTTP oturumu oluşturur."""
    session = requests.Session()
    session.trust_env = False
    session.headers.update(DEFAULT_HEADERS)
    if li_at:
        session.cookies.set("li_at", li_at, domain=".linkedin.com", path="/")
    return session


def iter_nested_json_nodes(value):
    """İç içe JSON yapılarındaki tüm düğümleri gezer."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_nested_json_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_nested_json_nodes(child)


def linkedin_slug_candidates(company_name, website_url=""):
    """Firma adına ve domaine göre olası LinkedIn slug adayları üretir."""
    candidates = []
    tokens = [token for token in normalize_company_identity(company_name).split() if len(token) >= 2]

    def add(value):
        value = re.sub(r"[^a-z0-9-]+", "-", fold_text(value or "")).strip("-")
        value = re.sub(r"-{2,}", "-", value)
        if value and value not in candidates:
            candidates.append(value)

    if tokens:
        add("-".join(tokens))
        add("".join(tokens))
        if len(tokens) >= 2:
            add("-".join(tokens[:2]))
            add("".join(tokens[:2]))
        if len(tokens) >= 3:
            add("-".join(tokens[:3]))

    host = urlparse(website_url or "").netloc.lower().replace("www.", "")
    if host:
        host_root = host.split(".")[0]
        add(host_root)
        if tokens:
            add(f"{host_root}-{tokens[0]}")
            add(f"{tokens[0]}-{host_root}")

    return candidates[:10]


def extract_linkedin_company_profile(page_html, company_url="", expected_name=""):
    """LinkedIn şirket sayfasındaki gömülü JSON'dan firma verisini çeker."""
    soup = BeautifulSoup(page_html, "html.parser")
    expected_tokens = company_token_set(expected_name)
    best_name = ""
    best_name_score = -1
    website_url = ""

    def maybe_promote_name(candidate_name):
        nonlocal best_name, best_name_score
        candidate_name = clean_company_name(candidate_name)
        if len(candidate_name) < 2 or not is_plausible_company_name(candidate_name):
            return
        candidate_tokens = company_token_set(candidate_name)
        if expected_tokens and candidate_tokens and not (expected_tokens & candidate_tokens):
            return
        overlap = len(expected_tokens & candidate_tokens) if expected_tokens else len(candidate_tokens)
        score = overlap * 20 + len(candidate_name)
        if score > best_name_score:
            best_name = candidate_name
            best_name_score = score

    for code in soup.find_all("code"):
        raw = (code.get_text() or "").strip()
        if not raw.startswith("{"):
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue

        for node in iter_nested_json_nodes(payload):
            node_name = node.get("name")
            if isinstance(node_name, str):
                maybe_promote_name(node_name)

            node_url = node.get("url")
            if isinstance(node_url, str):
                normalized_li = normalize_linkedin_company_url(node_url)
                normalized_web = normalize_company_site_url(node_url)
                if normalized_li and not best_name:
                    maybe_promote_name(extract_company_name_from_url(normalized_li))
                if normalized_web:
                    website_url = website_url or normalized_web

            if node.get("type") == "VIEW_WEBSITE" and isinstance(node.get("url"), str):
                normalized_cta = normalize_company_site_url(node.get("url"))
                if normalized_cta:
                    website_url = normalized_cta

    decoded = html.unescape(page_html)
    if not website_url:
        website_match = re.search(r'"type":"VIEW_WEBSITE".{0,1500}?"url":"(https?://[^"]+)"', decoded, re.DOTALL)
        if website_match:
            website_url = normalize_company_site_url(website_match.group(1))

    linkedin_url = normalize_linkedin_company_url(company_url)
    summary = ""
    if best_name:
        summary = best_name
        if website_url:
            summary = f"{best_name} | {website_url}"

    if expected_tokens and best_name:
        candidate_tokens = company_token_set(best_name)
        if candidate_tokens and not (expected_tokens & candidate_tokens):
            return None

    if not linkedin_url:
        return None

    return {
        "company_name": best_name or clean_company_name(expected_name) or extract_company_name_from_url(linkedin_url),
        "linkedin_url": linkedin_url,
        "website_url": website_url or "",
        "summary": summary,
    }


def extract_linkedin_search_results_from_html(page_html, limit=15):
    """LinkedIn sirket arama HTML'inden sirket adaylarini cikarir."""
    soup = BeautifulSoup(page_html or "", "html.parser")
    results = []
    seen = set()
    subtitle_selectors = [
        ".entity-result__primary-subtitle",
        ".entity-result__summary",
        ".entity-result__secondary-subtitle",
        '[data-test-app-aware-link] + div span[aria-hidden="true"]',
    ]
    blocked_parts = ["/in/", "/people/", "/pub/", "/jobs/", "/pulse/", "/search/", "/posts/", "/feed/", "/groups/", "/events/", "/school/", "/showcase/"]

    def find_card(node):
        current = node
        while current is not None:
            if getattr(current, "name", None) in {"li", "section", "div"}:
                class_text = " ".join(current.get("class", []))
                if "reusable-search__result-container" in class_text or "entity-result" in class_text:
                    return current
            current = current.parent
        return node.parent if getattr(node, "parent", None) else None

    for index, link in enumerate(soup.select('a[href*="/company/"]')):
        raw_href = (link.get("href") or "").strip()
        linkedin_url = normalize_linkedin_company_url(urljoin("https://www.linkedin.com/", raw_href))
        if not linkedin_url or linkedin_url in seen:
            continue
        lower_url = linkedin_url.lower()
        if any(part in lower_url for part in blocked_parts):
            continue
        seen.add(linkedin_url)

        card = find_card(link)
        name = clean_company_name(link.get_text(" ", strip=True))
        if (not name or len(name) < 2) and card:
            heading = card.select_one('span[aria-hidden="true"], h3, h4')
            if heading:
                name = clean_company_name(heading.get_text(" ", strip=True))
        if not name or len(name) < 2:
            name = extract_company_name_from_url(linkedin_url)
        if not name or len(name) < 2:
            continue

        subtitle = ""
        if card:
            for selector in subtitle_selectors:
                node = card.select_one(selector)
                if node:
                    subtitle = " ".join(node.get_text(" ", strip=True).split())
                    if subtitle:
                        break

        results.append({
            "company_name": name,
            "linkedin_url": linkedin_url,
            "title": subtitle,
            "score": max(limit, 5) * 20 - index,
        })
        if len(results) >= max(limit * 3, 12):
            break

    return results


def fetch_linkedin_company_profile_http(company_url, li_at="", expected_name=""):
    """LinkedIn şirket sayfasını HTTP ile okuyup şirket profilini döndürür."""
    linkedin_url = normalize_linkedin_company_url(company_url)
    if not linkedin_url:
        return None

    session = build_http_session(li_at=li_at)
    try:
        response = session.get(linkedin_url, timeout=LINKEDIN_HTTP_TIMEOUT, allow_redirects=True)
        response.raise_for_status()
    except Exception as exc:
        print(f"LinkedIn profil HTTP hatasi [{linkedin_url}]: {exc}")
        return None

    final_url = normalize_linkedin_company_url(response.url or linkedin_url)
    page_html = response.text or ""
    low_html = page_html.lower()
    if response.status_code != 200 or "authwall" in low_html or "security verification" in low_html:
        return None

    profile = extract_linkedin_company_profile(page_html, company_url=final_url, expected_name=expected_name)
    if not profile:
        return None

    match_score = score_company_website_match(
        expected_name or profile.get("company_name", ""),
        profile.get("company_name", ""),
        profile.get("summary", ""),
        final_url,
    )
    if expected_name and match_score < 24:
        return None

    profile["linkedin_url"] = final_url
    return profile


def find_company_linkedin(company_name, website_url="", li_at=""):
    """Firma adına göre LinkedIn şirket sayfasını tahmin edip doğrular."""
    if not li_at:
        return None

    for slug in linkedin_slug_candidates(company_name, website_url=website_url):
        profile = fetch_linkedin_company_profile_http(
            f"https://www.linkedin.com/company/{slug}/",
            li_at=li_at,
            expected_name=company_name,
        )
        if profile:
            return profile

    return None


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
        combined_results = fetch_brave_results_http(query) + fetch_bing_results_http(query, country)
        if not combined_results:
            combined_results = fetch_ddg_results_http(query)
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

    guessed = guess_company_website(clean_name, country=country)
    if guessed and (not best or guessed["score"] >= best["score"]):
        return guessed

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
        snapshot = openclaw_browser_capture_page(target_id, timeout_ms=20000) or {}
        profile = extract_linkedin_company_profile(
            snapshot.get("html", ""),
            company_url=snapshot.get("url", company_url),
            expected_name="",
        )

        if not (profile and profile.get("website_url")):
            about_url = company_url.rstrip("/") + "/about/"
            openclaw_browser_navigate(target_id, about_url, timeout_ms=OPENCLAW_COMMAND_TIMEOUT_MS)
            openclaw_browser_wait(target_id=target_id, load="domcontentloaded", timeout_ms=15000)
            openclaw_browser_wait(target_id=target_id, time_ms=2500, timeout_ms=5000)
            snapshot = openclaw_browser_capture_page(target_id, timeout_ms=20000) or {}
            profile = extract_linkedin_company_profile(
                snapshot.get("html", ""),
                company_url=snapshot.get("url", about_url),
                expected_name="",
            )

        if not profile or not profile.get("website_url"):
            return None

        return {
            "website_url": normalize_company_site_url(profile.get("website_url", "")) or "",
            "summary": profile.get("summary", ""),
            "label": profile.get("company_name", ""),
        }
    except Exception as exc:
        print(f"OpenClaw LinkedIn website cikarimi basarisiz [{company_url}]: {exc}")
        return None
    finally:
        if company_tab:
            openclaw_browser_close(company_tab.get("targetId") or company_tab.get("id"))


def search_linkedin_companies_openclaw(keyword, sector, location="", country="", li_at=None, limit=5):
    """LinkedIn company search sonucunu OpenClaw browser ile toplar."""
    if not li_at:
        os.environ["OPENCLAW_LAST_LINKEDIN_STATUS"] = linkedin_status_label("skip", "no_token")
        return []

    status = ensure_openclaw_browser_started()
    if not status or (not status.get("running") and not status.get("enabled", True)):
        os.environ["OPENCLAW_LAST_LINKEDIN_STATUS"] = linkedin_status_label("error", "browser_unavailable")
        return []
    if not set_openclaw_linkedin_cookie(li_at):
        os.environ["OPENCLAW_LAST_LINKEDIN_STATUS"] = linkedin_status_label("error", "cookie_set_failed")
        return []

    query = build_query(keyword, sector, location, country)
    search_url = f"https://www.linkedin.com/search/results/companies/?keywords={quote_plus(query)}"
    search_tab = None
    try:
        search_tab = openclaw_browser_open("https://www.linkedin.com/feed/", timeout_ms=OPENCLAW_COMMAND_TIMEOUT_MS)
        target_id = search_tab.get("targetId") or search_tab.get("id")
        if not target_id:
            return []

        openclaw_browser_wait(target_id=target_id, load="domcontentloaded", timeout_ms=20000)
        current_url = str((openclaw_browser_capture_page(target_id, timeout_ms=10000) or {}).get("url", "") or "")
        if "login" in current_url or "authwall" in current_url:
            os.environ["OPENCLAW_LAST_LINKEDIN_STATUS"] = linkedin_status_label("error", "token_rejected")
            return []

        openclaw_browser_navigate(target_id, search_url, timeout_ms=OPENCLAW_COMMAND_TIMEOUT_MS)
        openclaw_browser_wait(target_id=target_id, load="domcontentloaded", timeout_ms=20000)
        try:
            openclaw_browser_wait(
                target_id=target_id,
                selector="li.reusable-search__result-container, a[href*='/company/']",
                timeout_ms=20000,
            )
        except Exception:
            openclaw_browser_wait(target_id=target_id, time_ms=2500, timeout_ms=5000)

        snapshot = openclaw_browser_capture_page(target_id, timeout_ms=20000) or {}
        extracted_results = extract_linkedin_search_results_from_html(
            snapshot.get("html", ""),
            limit=max(limit * 3, 12),
        )
        if not isinstance(extracted_results, list):
            os.environ["OPENCLAW_LAST_LINKEDIN_STATUS"] = linkedin_status_label("error", "invalid_result")
            return []

        final_results = []
        for row in extracted_results[: max(limit * 3, limit)]:
            company_name = clean_company_name(row.get("company_name", ""))
            linkedin_url = normalize_linkedin_company_url(row.get("linkedin_url", ""))
            if not company_name or not linkedin_url:
                continue

            website_info = extract_linkedin_company_website_openclaw(linkedin_url)
            validated = validate_linkedin_company_candidate(
                company_name,
                linkedin_url,
                keyword=keyword,
                sector=sector,
                location=location,
                country=country,
                li_at=li_at,
                title_hint=row.get("title", ""),
                website_hint=(website_info.get("website_url") or website_info.get("website") or "") if website_info else "",
            )
            if not validated:
                continue
            validated["score"] = validated.get("score", 0) + row.get("score", 0)
            final_results.append(validated)
            if len(final_results) >= limit:
                break

        os.environ["OPENCLAW_LAST_LINKEDIN_STATUS"] = linkedin_status_label("ok", str(len(final_results)))
        return final_results
    except Exception as exc:
        os.environ["OPENCLAW_LAST_LINKEDIN_STATUS"] = linkedin_status_label("error", str(exc)[:120])
        print(f"OpenClaw LinkedIn search hatasi: {exc}")
        return []
    finally:
        if search_tab:
            openclaw_browser_close(search_tab.get("targetId") or search_tab.get("id"))


def search_linkedin_company_pages_http(keyword, sector, location="", country="", limit=5, li_at=""):
    """LinkedIn şirket sayfalarını tarayıcı olmadan arar."""
    queries = [
        build_query("site:linkedin.com/company/", keyword, sector, location, country),
        build_query("site:linkedin.com/company/", sector, keyword, location, country),
        build_query("site:www.linkedin.com/company/", f"\"{keyword}\"", sector, location, country),
        build_query("site:www.linkedin.com/company/", keyword, f"\"{sector}\"", location, country),
        build_query(keyword, sector, location, country, "official linkedin company"),
        build_query(keyword, sector, location, country, "\"linkedin\" company"),
    ]

    found = {}
    for query in queries:
        combined_results = fetch_brave_results_http(query) + fetch_bing_results_http(query, country)
        if not combined_results:
            combined_results = fetch_ddg_results_http(query)
        for entry in combined_results:
            url = normalize_linkedin_company_url(entry.get("href", ""))
            if not url:
                continue
            lower_url = url.lower()
            if any(x in lower_url for x in ["/in/", "/people/", "/pub/", "/jobs/", "/pulse/", "/search/", "/posts/"]):
                continue

            title = entry.get("title", "").strip()
            snippet = entry.get("body", "").strip()
            name = clean_company_name(title) or extract_company_name_from_url(url)
            score = score_candidate(
                {"title": title, "body": snippet, "href": url},
                keyword,
                sector,
                location,
                country,
            ) + 120
            haystack = fold_text(f"{title} {snippet}")
            if keyword and fold_text(keyword) in haystack:
                score += 10
            if sector and fold_text(sector) in haystack:
                score += 6

            if url not in found or score > found[url]["score"]:
                found[url] = {
                    "company_name": name,
                    "linkedin_url": url,
                    "title": snippet,
                    "score": score,
                }

    ranked = sorted(found.values(), key=lambda item: item["score"], reverse=True)
    final_results = []
    for row in ranked[: max(limit * 2, limit)]:
        website_info = find_company_website(
            row["company_name"],
            keyword=keyword,
            sector=sector,
            location=location,
            country=country,
        )
        final_results.append({
            "company_name": row["company_name"],
            "linkedin_url": row["linkedin_url"],
            "website_url": (website_info.get("website_url") or website_info.get("website") or "") if website_info else "",
            "title": row["title"],
            "score": row["score"] + (website_info.get("score", 0) if website_info else 0),
        })
        if len(final_results) >= limit:
            break

    return final_results

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
    score += seller_intent_score(haystack)
    
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
    c_fold = fold_text(country).strip()
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
    if looks_like_article_or_info_page(entry.get('title', ''), entry.get('body', ''), entry.get('href', '')):
        score -= 120
        
    return score

# ==========================================
# ARAŞTIRMA FONKSİYONLARI (MOTOR)
# ==========================================

def search_web_companies(keyword, sector, location="", country="", limit=6):
    """Bing üzerinden en sağlam ve engellenemez (CAPTCHA bypass) şekilde şirket arar."""
    target_tld = TLD_MAP.get(country.lower(), "")
    q_loc = f'"{location}"' if location else ""

    web_queries = [
        build_query(keyword, sector, q_loc, country, "manufacturer"),
        build_query(keyword, sector, q_loc, country, "supplier"),
        build_query(keyword, sector, q_loc, country, "distributor"),
        build_query(keyword, sector, q_loc, country, "dealer"),
        build_query(keyword, sector, q_loc, country, "reseller"),
        build_query(keyword, sector, q_loc, country, "company"),
        build_query(keyword, sector, q_loc, country, "firma"),
        build_query(keyword, sector, q_loc, country, "official company website"),
        build_query(keyword, sector, q_loc, country, "kurumsal"),
        build_query(keyword, sector, "manufacturer in", q_loc, country),
        build_query(sector, keyword, "supplier", q_loc, country),
        build_query(sector, keyword, "distributor", q_loc, country),
        build_query(sector, keyword, "bayi", q_loc, country),
        build_query(sector, keyword, "tedarikci", q_loc, country),
    ]
    if target_tld:
        web_queries.append(build_query(f"site:{target_tld}", keyword, sector, "supplier", q_loc))
    
    final_results = {}
    
    if can_use_playwright():
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
            mark_playwright_failed(e)
            print(f"Playwright Arama Hatası, HTTP fallback devreye giriyor: {str(e)}")
    else:
        print("Playwright kapali: OPENCLAW_DISABLE_PLAYWRIGHT=1, HTTP fallback kullaniliyor.")

    if len(final_results) < limit:
        for q in web_queries:
            if len(final_results) >= (limit + 4):
                break
            combined_results = fetch_brave_results_http(q) + fetch_bing_results_http(q, country)
            if not combined_results:
                combined_results = fetch_ddg_results_http(q)
            for entry in combined_results:
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
    verified_results = []
    for candidate in sorted_list[: max(limit * 4, 12)]:
        verified = verify_company_homepage(candidate, keyword, sector, location=location, country=country)
        if not verified:
            continue
        verified_results.append(verified)
        if len(verified_results) >= limit:
            break

    return verified_results[:limit]


for _token in ("company", "school"):
    if _token not in NOISY_NAME_TOKENS:
        NOISY_NAME_TOKENS.append(_token)

def read_website_content(url):
    """Bir web sitesinin içeriğini okur ve temizler."""
    if not url: return "Gecersiz link."
    try:
        resp = HTTP_SESSION.get(url, timeout=12)
        resp.raise_for_status()
        content = trafilatura.extract(resp.text, include_comments=False, include_tables=True)
        if not content:
            downloaded = trafilatura.fetch_url(url)
            content = trafilatura.extract(downloaded, include_comments=False, include_tables=True)
        return content[:3000] if content else "Icerik okunamadi."
    except:
        return "Baglanti hatasi."


def read_website_content(url):
    """Read company-site content with OpenClaw first, then HTTP fallback."""
    if not url:
        return "Geçersiz link."
    try:
        require_host = urlparse(url).netloc.lower().replace("www.", "")
        snapshot = openclaw_fetch_page_snapshot(url, require_host=require_host)
        if snapshot and snapshot.get("text"):
            snapshot_text = "\n".join(part for part in [snapshot.get("title", ""), snapshot.get("text", "")] if part)
            return repair_text(snapshot_text)[:3000]

        resp = HTTP_SESSION.get(url, timeout=8)
        resp.raise_for_status()
        content = trafilatura.extract(resp.text, include_comments=False, include_tables=True)
        if not content:
            downloaded = trafilatura.fetch_url(url)
            content = trafilatura.extract(downloaded, include_comments=False, include_tables=True)
        return repair_text(content)[:3000] if content else "İçerik okunamadı."
    except Exception:
        return "Bağlantı hatası."

def search_linkedin_companies(keyword, sector, location="", li_at=None, limit=5, country=""):
    """LinkedIn üzerinden şirket arar (Playwright - Defansif Mod)."""
    query = build_query(keyword, sector, location, country)
    search_url = f"https://www.linkedin.com/search/results/companies/?keywords={query}"

    fallback_results = search_linkedin_company_pages_http(keyword, sector, location, country, limit=limit, li_at=li_at or "")
    if fallback_results:
        os.environ["OPENCLAW_LAST_LINKEDIN_STATUS"] = linkedin_status_label("http_fallback", str(len(fallback_results)))

    if OPENCLAW_LINKEDIN_BROWSER_ENABLED:
        openclaw_results = search_linkedin_companies_openclaw(
            keyword,
            sector,
            location,
            country=country,
            li_at=li_at,
            limit=limit,
        )
        if openclaw_results:
            return openclaw_results

    if not li_at:
        return fallback_results

    results = []
    if can_use_playwright():
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
                            name = clean_company_name(title_el.inner_text().split("\n")[0].strip())
                            url = normalize_linkedin_company_url(title_el.get_attribute("href"))
                            lower_url = url.lower()
                            if not lower_url:
                                continue
                            if any(x in lower_url for x in ["/in/", "/people/", "/pub/", "/jobs/", "/pulse/", "/search/", "/posts/"]):
                                continue
                            desc_el = item.query_selector('div.entity-result__primary-subtitle')
                            title_hint = desc_el.inner_text().strip() if desc_el else ""
                            validated = validate_linkedin_company_candidate(
                                name,
                                url,
                                keyword=keyword,
                                sector=sector,
                                location=location,
                                country=country,
                                li_at=li_at or "",
                                title_hint=title_hint,
                                website_hint="",
                            )
                            if not validated:
                                continue
                            validated["score"] = validated.get("score", 0) + 10 - i
                            results.append(validated)
                except:
                    pass # Sonuç bulunamadıysa boş dön
                    
                browser.close()
        except Exception as e:
            mark_playwright_failed(e)
            print(f"LinkedIn Hata, HTTP fallback devreye giriyor: {str(e)}")
    else:
        print("LinkedIn Playwright kapali: OPENCLAW_DISABLE_PLAYWRIGHT=1, HTTP fallback kullaniliyor.")

    final_results = results if results else fallback_results
    if results:
        os.environ["OPENCLAW_LAST_LINKEDIN_STATUS"] = linkedin_status_label("playwright", str(len(results)))
    elif not os.environ.get("OPENCLAW_LAST_LINKEDIN_STATUS"):
        os.environ["OPENCLAW_LAST_LINKEDIN_STATUS"] = linkedin_status_label("error", "no_results")
    return final_results


# Runtime overrides for stricter seller/company discovery.
def dedupe_queries(queries):
    """Collapse repeated search queries while preserving order."""
    unique = []
    seen = set()
    for query in queries:
        clean_query = " ".join((query or "").split())
        if not clean_query:
            continue
        key = clean_query.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(clean_query)
    return unique


def score_company_name_candidate(name):
    """Score name chunks so search-engine crumbs lose to real company names."""
    text = re.sub(r"\s+", " ", (name or "").strip())
    if len(text) < 2:
        return -999

    low = fold_text(text)
    score = len(company_token_set(text)) * 18 + min(len(text), 40)
    word_count = len(text.split())

    if 1 <= word_count <= 6:
        score += 12
    elif 7 <= word_count <= 8:
        score -= 18
    elif 9 <= word_count <= 12:
        score -= 75
    elif word_count > 12:
        score -= 140

    if is_plausible_company_name(text):
        score += 10

    if re.search(r"[/:@]|\.com|\.net|\.org|\.tr|www\.", low):
        score -= 35

    if len(text) > 90:
        score -= 120

    if any(token in low for token in ["fiyat", "kiralama", "satilik", "temiz", "bakimli", "uygun", "ikinci el", "2 el"]):
        score -= 100

    for token in NOISY_NAME_TOKENS:
        if token in low:
            score -= 10

    if any(char.isdigit() for char in text):
        score += 4

    return score


def clean_company_name(name):
    """Extract the cleanest company-like label from noisy search titles."""
    text = html.unescape((name or "").strip()).replace("\xa0", " ")
    if not text:
        return ""

    text = re.sub(r"\b(?:site|intitle):\S+\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"https?://\S+", " ", text)
    text = text.replace("›", "|").replace("»", "|").replace("•", "|").replace("·", "|")
    text = re.sub(r"\b(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)+\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()

    candidates = []
    for part in re.split(r"\s*\|\s*|\s+-\s+|\s*:\s*|\s*/\s*|\s*[>»]\s*", text):
        part = re.sub(r"\([^)]*\)", " ", part)
        part = re.sub(r"\[[^\]]*\]", " ", part)
        for token in NOISY_NAME_TOKENS:
            part = re.sub(rf"\b{re.escape(token)}\b", " ", part, flags=re.IGNORECASE)
        part = re.sub(r"[^0-9A-Za-z&+.' -]+", " ", part)
        part = re.sub(r"\s+", " ", part).strip(" -|,")
        if part:
            candidates.append(part)

    if not candidates:
        fallback = re.sub(r"[^0-9A-Za-z&+.' -]+", " ", text)
        return re.sub(r"\s+", " ", fallback).strip(" -|,")

    return max(candidates, key=score_company_name_candidate)


def best_company_name(*candidates):
    """Pick the strongest company label from multiple noisy candidates."""
    best_name = ""
    best_score = -999
    for candidate in candidates:
        cleaned = clean_company_name(candidate)
        score = score_company_name_candidate(cleaned)
        if score > best_score:
            best_name = cleaned
            best_score = score
    return best_name


def clean_company_name(name):
    """Extract the cleanest company-like label from noisy search titles."""
    text = repair_text(name)
    if not text:
        return ""

    text = re.sub(r"\b(?:site|intitle):\S+\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"https?://\S+", " ", text)
    text = text.replace("â€º", "|").replace("Â»", "|").replace("â€¢", "|").replace("Â·", "|")
    text = re.sub(r"\b(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)+\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()

    candidates = []
    for part in re.split(r"\s*\|\s*|\s+-\s+|\s*:\s*|\s*/\s*|\s*[>Â»]\s*", text):
        part = re.sub(r"\([^)]*\)", " ", part)
        part = re.sub(r"\[[^\]]*\]", " ", part)
        for token in NOISY_NAME_TOKENS:
            part = re.sub(rf"\b{re.escape(token)}\b", " ", part, flags=re.IGNORECASE)
        part = repair_text(part)
        part = re.sub(r"[^\w&+.' -]+", " ", part, flags=re.UNICODE).replace("_", " ")
        part = re.sub(r"\s+", " ", part).strip(" -|,")
        if part:
            candidates.append(part)

    if not candidates:
        fallback = re.sub(r"[^\w&+.' -]+", " ", text, flags=re.UNICODE).replace("_", " ")
        return re.sub(r"\s+", " ", fallback).strip(" -|,")

    return max(candidates, key=score_company_name_candidate)


def host_brand_label(url):
    """Return the most brand-like label from a hostname."""
    host = urlparse(url or "").netloc.lower().replace("www.", "")
    labels = [label for label in host.split(".") if label]
    generic = {"com", "net", "org", "co", "gov", "edu", "tr", "uk", "de", "fr", "it"}
    for label in reversed(labels[:-1] if len(labels) > 1 else labels):
        if label not in generic:
            return label
    return labels[0] if labels else ""


def extract_company_name_from_url(url):
    """Prefer brand-like hostnames over random path segments for company names."""
    parsed = urlparse(url or "")
    if is_linkedin_company_url(url):
        segment = parsed.path.strip("/").split("/")[-1] if parsed.path else ""
        segment = re.sub(r"[%_]+", " ", segment)
        segment = segment.replace("-", " ").strip()
        return clean_company_name(segment.title() if segment else "")

    brand = host_brand_label(url)
    if brand:
        return clean_company_name(brand.replace("-", " ").replace("_", " ").title())

    segment = parsed.path.strip("/").split("/")[-1] if parsed.path else ""
    segment = re.sub(r"[%_]+", " ", segment)
    segment = segment.replace("-", " ").strip()
    return clean_company_name(segment.title() if segment else parsed.netloc.replace("www.", ""))


def _cached_results(provider, query):
    """Read provider/query cache."""
    return SEARCH_RESULT_CACHE.get((provider, (query or "").strip().lower()))


def _store_cached_results(provider, query, results):
    """Write provider/query cache."""
    SEARCH_RESULT_CACHE[(provider, (query or "").strip().lower())] = list(results)
    return list(results)


def fetch_brave_results_http(query):
    """Fetch web results from Brave with simple cache and rate-limit backoff."""
    global BRAVE_BACKOFF_UNTIL, BRAVE_FAILURE_COUNT

    cached = _cached_results("brave", query)
    if cached is not None:
        return list(cached)

    if time.time() < BRAVE_BACKOFF_UNTIL:
        return []

    try:
        resp = HTTP_SESSION.get(
            "https://search.brave.com/search",
            params={"q": query},
            timeout=SEARCH_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
    except Exception as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code == 429:
            BRAVE_FAILURE_COUNT += 1
            BRAVE_BACKOFF_UNTIL = time.time() + min(600, 120 * BRAVE_FAILURE_COUNT)
            return []
        print(f"HTTP Brave Hata [{query}]: {exc}")
        return []

    BRAVE_FAILURE_COUNT = 0
    BRAVE_BACKOFF_UNTIL = 0.0

    soup = BeautifulSoup(resp.text, "html.parser")
    parsed_results = []
    for card in soup.select('div[data-type="web"]')[:15]:
        title_el = card.select_one("a.title, a.svelte-14r20fy.l1, a[href^='http']")
        if not title_el:
            continue
        href = title_el.get("href", "").strip()
        if not href.startswith("http"):
            continue
        title = title_el.get_text(" ", strip=True) or card.get_text(" ", strip=True)[:120]
        desc_parts = [node.get_text(" ", strip=True) for node in card.select(".description")[:2]]
        parsed_results.append({
            "title": title,
            "href": href,
            "body": " ".join(part for part in desc_parts if part).strip(),
        })

    return _store_cached_results("brave", query, parsed_results)


def fetch_ddg_results_http(query):
    """Fetch DuckDuckGo results with light backoff when the endpoint flakes."""
    global DDG_BACKOFF_UNTIL, DDG_FAILURE_COUNT

    cached = _cached_results("ddg", query)
    if cached is not None:
        return list(cached)

    if time.time() < DDG_BACKOFF_UNTIL:
        return []

    try:
        resp = HTTP_SESSION.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            timeout=4,
        )
        resp.raise_for_status()
    except Exception as exc:
        DDG_FAILURE_COUNT += 1
        if DDG_FAILURE_COUNT >= 2:
            DDG_BACKOFF_UNTIL = time.time() + 300
        print(f"HTTP DDG Hata [{query}]: {exc}")
        return []

    DDG_FAILURE_COUNT = 0
    DDG_BACKOFF_UNTIL = 0.0

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

    return _store_cached_results("ddg", query, parsed_results)


def search_engine_results(query, country="", allow_ddg=True):
    """Combine search providers without hammering every engine every time."""
    combined = []
    seen_urls = set()

    def add_entries(entries):
        for entry in entries:
            href = unwrap_search_result_url(entry.get("href", ""))
            if not href or href in seen_urls:
                continue
            seen_urls.add(href)
            combined.append({
                "title": entry.get("title", ""),
                "href": href,
                "body": entry.get("body", ""),
            })

    brave_results = fetch_brave_results_http(query)
    add_entries(brave_results[:12])

    if len(combined) < 6:
        add_entries(fetch_bing_results_http(query, country)[:12])

    if allow_ddg and len(combined) < 8:
        add_entries(fetch_ddg_results_http(query)[:10])

    return combined


def linkedin_url_is_rejectable(url):
    """Reject non-company or tracking-heavy LinkedIn URLs."""
    lower_url = (url or "").lower()
    return any(
        token in lower_url
        for token in [
            "/in/", "/people/", "/pub/", "/jobs/", "/pulse/", "/search/", "/posts/",
            "/feed/", "/groups/", "/events/", "/school/", "/showcase/", "/redir/",
            "trk=", "tracking", "redirect"
        ]
    )


def validate_linkedin_company_candidate(company_name, linkedin_url, keyword="", sector="", location="", country="", li_at="", title_hint="", website_hint="", relaxed=False):
    """Keep only LinkedIn company pages that look live and relevant to the requested product."""
    normalized_url = normalize_linkedin_company_url(linkedin_url)
    if not normalized_url or linkedin_url_is_rejectable(normalized_url):
        return None

    profile = fetch_linkedin_company_profile_http(
        normalized_url,
        li_at=li_at,
        expected_name=company_name,
    )
    if not profile:
        return None

    combined_parts = [
        profile.get("company_name", ""),
        profile.get("summary", ""),
        title_hint or "",
    ]

    session = build_http_session(li_at=li_at)
    for page_url in [profile["linkedin_url"], profile["linkedin_url"].rstrip("/") + "/about/"]:
        try:
            response = session.get(page_url, timeout=LINKEDIN_HTTP_TIMEOUT, allow_redirects=True)
            response.raise_for_status()
        except Exception:
            continue

        page_html = response.text or ""
        low_html = page_html.lower()
        if response.status_code != 200 or "authwall" in low_html or "security verification" in low_html:
            continue

        soup = BeautifulSoup(page_html, "html.parser")
        page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
        page_text = trafilatura.extract(page_html, include_comments=False, include_tables=False) or soup.get_text(" ", strip=True)
        page_text = " ".join(page_text.split())[:3500]
        combined_parts.extend([page_title, page_text])

    combined_text = " ".join(part for part in combined_parts if part)
    combined_fold = fold_text(combined_text)
    sector_terms = [fold_text(item) for item in (split_search_phrases(sector, max_parts=5) + translated_sector_variants(sector, country))]
    city_fold = fold_text(location)
    country_tokens = country_alias_tokens(country)
    product_score = best_product_signal_score(keyword, combined_text, country=country)

    reasons = []
    score = 0
    actual_name = profile.get("company_name", "") or company_name
    name_match_score = score_company_website_match(
        company_name or actual_name,
        actual_name,
        combined_text,
        profile["linkedin_url"],
    )
    if company_name and normalize_company_identity(company_name) == normalize_company_identity(actual_name):
        score += 35
        reasons.append("exact name match")
    elif name_match_score >= 24:
        score += 20
        reasons.append("name match")
    else:
        return None

    if product_score >= 12:
        score += 38
        reasons.append("product matched")
    else:
        score += product_score

    if sector_terms and any(item in combined_fold for item in sector_terms):
        score += 12
        reasons.append("industry matched")

    if city_fold:
        if city_fold in combined_fold:
            score += 18
            reasons.append("city matched")
        else:
            score -= 35
    if country_tokens and any(token in combined_fold for token in country_tokens):
        score += 8
        reasons.append("country matched")

    website_candidate = normalize_company_site_url(website_hint or profile.get("website_url", ""))
    verified_website = None
    if website_candidate:
        verified_website = verify_company_homepage(
            {
                "company_name": actual_name,
                "website": website_candidate,
                "score": 0,
                "snippet": profile.get("summary", "") or title_hint or "",
            },
            keyword,
            sector,
            location=location,
            country=country,
        )
        if verified_website:
            score += 26
            reasons.append("website verified")

    footprint_score = company_footprint_score(combined_text)
    sector_hit = bool(sector_terms and any(item in combined_fold for item in sector_terms))

    if footprint_score < (4 if relaxed else 6) and not verified_website:
        return None

    if keyword and product_score < 8 and not verified_website:
        if not relaxed or (product_score < 0 and not sector_hit):
            return None

    if score < (42 if relaxed else 55):
        return None

    return {
        "company_name": actual_name,
        "linkedin_url": profile["linkedin_url"],
        "website_url": (verified_website.get("website") if verified_website else website_candidate) or "",
        "title": title_hint or profile.get("summary", ""),
        "score": score,
        "match_reasons": reasons,
        "match_mode": "relaxed" if relaxed else "strict",
    }


def looks_like_directory_listing(title, snippet, url, page_text=""):
    """Reject directory/marketplace pages that list companies instead of being one."""
    if host_is_directory(url):
        return True

    haystack = fold_text(f"{title} {snippet} {page_text} {url}")
    if not haystack:
        return False

    if any(token in haystack for token in DIRECTORYISH_TOKENS):
        if not any(token in haystack for token in COMPANY_PAGE_HINT_TOKENS):
            return True

    return False


def looks_like_article_or_info_page(title, snippet, url, page_text=""):
    """Filter out news/info pages before they consume company-result slots."""
    haystack = fold_text(f"{title} {snippet} {page_text} {url}")
    host = urlparse(url or "").netloc.lower().replace("www.", "")
    path = urlparse(url or "").path.lower()
    article_path_tokens = [
        "/news/", "/newsroom/", "/blog/", "/article/", "/articles/", "/press/",
        "/press-release/", "/announcement/", "/announcements/", "/haber/",
        "/haberler/", "/basin/", "/duyuru/", "/media/", "/medya/"
    ]
    if any(token in host for token in NON_COMPANY_HOST_TOKENS):
        return True
    if any(token in path for token in BAD_PATH_TOKENS) or any(token in path for token in article_path_tokens):
        return True
    if looks_like_directory_listing(title, snippet, url, page_text=page_text):
        return True
    if looks_like_media_or_entertainment_page(title, snippet, url, page_text=page_text):
        return True
    if any(token in haystack for token in ["haber", "haberler", "press release", "newsroom", "duyuru", "announcement"]):
        return True
    return any(token in haystack for token in ARTICLEISH_TOKENS)


def search_term_tokens(text, min_len=3):
    """Tokenize free-text queries without company-specific stopwords."""
    tokens = [token for token in re.split(r"[^a-z0-9]+", fold_text(text)) if len(token) >= min_len]
    generic = {
        "and", "the", "for", "with", "from", "official", "company", "firma",
        "ltd", "sti", "sanayi", "ticaret"
    }
    return [token for token in tokens if token not in generic]


def product_signal_score(keyword, text):
    """Measure whether the requested product truly appears in the candidate text."""
    keyword_fold = fold_text(keyword)
    haystack = fold_text(text)
    if not keyword_fold:
        return 0
    if re.search(rf"\b{re.escape(keyword_fold)}\b", haystack):
        return 30

    kw_tokens = set(search_term_tokens(keyword))
    hay_tokens = set(search_term_tokens(text))
    if not kw_tokens:
        return 0

    overlap = len(kw_tokens & hay_tokens)
    if len(kw_tokens) >= 2:
        if overlap >= 2:
            return 18 + overlap * 4
        if overlap == 1:
            return -18
        return -36

    return 12 if overlap else -18


def company_footprint_score(text):
    """Reward pages that look like actual company websites."""
    haystack = fold_text(text)
    score = 0
    footprint_tokens = [
        "hakkimizda", "about us", "about company", "corporate", "kurumsal",
        "iletisim", "contact", "contact us", "urunler", "products", "services",
        "catalog", "catalogue", "solution", "cozum", "manufacturer", "supplier",
        "ltd", "sti", "a s", "inc", "llc", "gmbh", "sanayi", "ticaret",
        "atolye", "imalathane", "isletme", "workshop", "machine shop", "trading",
        "export", "exporter", "dealer", "stockist", "store", "shop", "supplier"
    ]
    for token in footprint_tokens:
        if token in haystack:
            score += 6
    return score


def looks_like_media_or_entertainment_page(title, snippet, url, page_text=""):
    """Reject movie/music/news entertainment pages that happen to share product words."""
    haystack = fold_text(f"{title} {snippet} {page_text} {url}")
    media_tokens = [
        "film", "movie", "cinema", "sinema", "dizi", "series", "episode",
        "fragman", "trailer", "izle", "watch online", "imdb", "beyazperde",
        "netflix", "prime video", "box office", "soundtrack", "lyrics", "torrent"
    ]
    return any(token in haystack for token in media_tokens)


def looks_like_article_or_info_page(title, snippet, url):
    """Filter out news/info/directory pages instead of company homes."""
    haystack = fold_text(f"{title} {snippet} {url}")
    host = urlparse(url or "").netloc.lower().replace("www.", "")
    path = urlparse(url or "").path.lower()
    if any(token in host for token in NON_COMPANY_HOST_TOKENS):
        return True
    if any(token in path for token in BAD_PATH_TOKENS):
        return True
    if looks_like_directory_listing(title, snippet, url):
        return True
    if looks_like_media_or_entertainment_page(title, snippet, url):
        return True
    return any(token in haystack for token in ARTICLEISH_TOKENS)


def looks_like_company_result(title, snippet, url, is_li=False):
    """Keep only pages that still look like company results after cleanup."""
    haystack = fold_text(f"{title} {snippet} {url}")
    parsed = urlparse(url or "")
    host = parsed.netloc.lower().replace("www.", "")
    path = parsed.path.lower()

    if not is_li and any(token in path for token in BAD_PATH_TOKENS):
        return False
    if any(host.startswith(f"{prefix}.") for prefix in BAD_SUBDOMAIN_PREFIXES):
        return False
    if looks_like_article_or_info_page(title, snippet, url):
        return False
    if looks_like_directory_listing(title, snippet, url):
        return False
    if any(token in haystack for token in QUESTIONISH_TOKENS) and not any(token in haystack for token in COMPANY_HINT_TOKENS):
        return False

    return True


def verify_company_homepage(candidate, keyword, sector, location="", country="", relaxed=False):
    """Validate a company by combining the root domain with product-page evidence."""
    deadline = time.time() + (10 if relaxed else 12)
    website_url = normalize_company_site_url(candidate.get("website", ""))
    if not website_url:
        return None
    if looks_like_article_or_info_page(candidate.get("company_name", ""), candidate.get("snippet", ""), website_url):
        return None

    session = build_http_session()
    keyword_link_tokens = search_term_tokens(keyword, min_len=4)
    for variant in translated_keyword_variants(keyword, country):
        keyword_link_tokens.extend(search_term_tokens(variant, min_len=2))
    sector_link_tokens = search_term_tokens(sector, min_len=4)
    for variant in translated_sector_variants(sector, country):
        sector_link_tokens.extend(search_term_tokens(variant, min_len=2))
    city_tokens = [fold_text(location)] if location else []
    country_tokens = country_location_tokens(country)
    target_country_code = country_code_for(country)
    target_country_tld = country_tld_for(country)

    def build_page_evidence(final_page_url, title, body_text, raw_links, location_text=""):
        final_host = urlparse(final_page_url).netloc.lower().replace("www.", "")
        clean_title = " ".join((title or "").split())
        clean_text = " ".join((body_text or "").split())[:2600]
        clean_location_text = " ".join((location_text or "").split())[:2200]
        if not clean_title and not clean_text and not clean_location_text:
            return None

        links = []
        seen_links = set()
        for row in raw_links or []:
            absolute_url = unwrap_search_result_url((row.get("url") or "").strip())
            if not absolute_url or not absolute_url.startswith("http"):
                continue
            absolute_host = urlparse(absolute_url).netloc.lower().replace("www.", "")
            if absolute_host != final_host or url_looks_like_asset(absolute_url):
                continue
            path = urlparse(absolute_url).path.lower()
            if path in {"", "/"} or absolute_url in seen_links:
                continue

            anchor_text = " ".join(((row.get("text") or "")).split())
            link_blob = fold_text(f"{anchor_text} {absolute_url}")
            product_link_score = 0
            location_link_score = 0
            if any(token in link_blob for token in keyword_link_tokens):
                product_link_score += 34
            if any(token in link_blob for token in sector_link_tokens):
                product_link_score += 10
            if any(token in link_blob for token in ["urun", "product", "products", "kategori", "category", "cozum", "solution", "disli", "gear", "worm", "reductor", "redaktor", "catalog"]):
                product_link_score += 14
            if any(token in link_blob for token in city_tokens):
                location_link_score += 34
            if any(token in link_blob for token in country_tokens):
                location_link_score += 24
            if any(token in link_blob for token in LOCATION_PAGE_HINT_TOKENS):
                location_link_score += 18
            if any(token in link_blob for token in LOCATION_ROLE_HINT_TOKENS):
                location_link_score += 10
            if target_country_tld and target_country_tld in absolute_url.lower():
                location_link_score += 12
            if target_country_code and any(token in absolute_url.lower() for token in [f"/{target_country_code.lower()}/", f"-{target_country_code.lower()}/"]):
                location_link_score += 10
            if looks_like_article_or_info_page(anchor_text, "", absolute_url):
                product_link_score -= 24
                location_link_score -= 12

            link_score = product_link_score + location_link_score
            if link_score <= 0:
                continue

            seen_links.add(absolute_url)
            links.append({
                "url": absolute_url,
                "text": anchor_text,
                "score": link_score,
                "product_score": product_link_score,
                "location_score": location_link_score,
            })
        links = sorted(links, key=lambda item: (item["score"], item["location_score"], item["product_score"]), reverse=True)[:12]

        return {
            "url": final_page_url,
            "title": clean_title,
            "text": clean_text,
            "location_text": clean_location_text,
            "snippet": (clean_title or clean_text[:220] or clean_location_text[:220]).strip(),
            "links": links,
        }

    def fetch_page_evidence(url, require_host=""):
        if time.time() >= deadline:
            return None
        raw_url = unwrap_search_result_url(url)
        if not raw_url or not raw_url.startswith("http"):
            return None

        openclaw_snapshot = openclaw_fetch_page_snapshot(raw_url, require_host=require_host)
        if openclaw_snapshot:
            return build_page_evidence(
                openclaw_snapshot.get("url", raw_url),
                openclaw_snapshot.get("title", ""),
                openclaw_snapshot.get("text", ""),
                openclaw_snapshot.get("links", []),
                location_text=openclaw_snapshot.get("locationText", ""),
            )

        try:
            resp = session.get(raw_url, timeout=VERIFY_HTTP_TIMEOUT, allow_redirects=True)
            resp.raise_for_status()
        except Exception:
            return None

        final_page_url = resp.url or raw_url
        final_host = urlparse(final_page_url).netloc.lower().replace("www.", "")
        if require_host and final_host != require_host:
            return None

        html_doc = resp.text or ""
        soup = BeautifulSoup(html_doc, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        body_text = trafilatura.extract(html_doc, include_comments=False, include_tables=False) or soup.get_text(" ", strip=True)

        raw_links = []
        for anchor in soup.select("a[href]"):
            href = (anchor.get("href") or "").strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            raw_links.append({
                "url": urljoin(final_page_url, href),
                "text": anchor.get_text(" ", strip=True) or anchor.get("aria-label", "") or anchor.get("title", ""),
            })

        location_parts = []
        location_parts.extend(
            " ".join(node.get_text(" ", strip=True).split())
            for node in soup.select(
                "address, footer, [class*='contact'], [class*='location'], [class*='office'], [class*='branch'], [class*='dealer'], [class*='distributor'], [id*='contact'], [id*='location'], [id*='office'], [id*='branch'], [itemprop='address'], [itemprop='addressCountry']"
            )[:16]
        )
        location_parts.extend(
            " ".join(
                f"{node.get('name') or node.get('property') or ''} {node.get('content') or ''}".split()
            )
            for node in soup.select("meta[name], meta[property]")[:40]
        )
        location_parts.extend(
            " ".join((node.get_text(" ", strip=True) or "").split())
            for node in soup.select("script[type='application/ld+json']")[:8]
        )
        return build_page_evidence(final_page_url, title, body_text, raw_links, location_text=" ".join(location_parts))

    root_page = fetch_page_evidence(website_url)
    if not root_page:
        return None

    final_url = normalize_company_site_url(root_page.get("url") or website_url)
    if not final_url:
        return None

    root_title = root_page.get("title", "")
    root_text = root_page.get("text", "")
    final_host = urlparse(final_url).netloc.lower().replace("www.", "")

    if looks_like_article_or_info_page(root_title, root_text[:300], final_url):
        return None
    if looks_like_directory_listing(root_title, candidate.get("snippet", ""), final_url, page_text=root_text[:600]):
        return None
    if looks_like_media_or_entertainment_page(root_title, candidate.get("snippet", ""), final_url, page_text=root_text[:600]):
        return None

    pages = [root_page]
    source_page = None
    source_url = unwrap_search_result_url(candidate.get("source_url") or "")
    if source_url and normalize_company_site_url(source_url) == final_url and source_url.rstrip("/") != final_url.rstrip("/"):
        fetched_source = fetch_page_evidence(source_url, require_host=final_host)
        if fetched_source and not looks_like_directory_listing(
            fetched_source.get("title", ""),
            candidate.get("snippet", ""),
            fetched_source.get("url", ""),
            page_text=fetched_source.get("text", "")[:600],
        ) and not looks_like_media_or_entertainment_page(
            fetched_source.get("title", ""),
            candidate.get("snippet", ""),
            fetched_source.get("url", ""),
            page_text=fetched_source.get("text", "")[:600],
        ):
            source_page = fetched_source
            pages.append(source_page)

    k_fold = fold_text(keyword)
    s_fold = fold_text(sector)
    sector_terms = [fold_text(item) for item in (split_search_phrases(sector, max_parts=5) + translated_sector_variants(sector, country)) if item]
    city_fold = fold_text(location)
    country_fold = fold_text(country)
    common_company_paths = [
        "/iletisim", "/contact", "/contact-us", "/hakkimizda", "/about", "/kurumsal", "/corporate", "/company",
        "/locations", "/location", "/where-to-buy", "/dealers", "/distributors", "/offices", "/branches",
        "/network", "/partners", "/subeler", "/bayiler", "/ofisler",
    ]
    if target_country_code:
        common_company_paths.extend([
            f"/{target_country_code.lower()}/",
            f"/{target_country_code.lower()}",
        ])

    initial_combined = " ".join(
        part
        for part in [
            candidate.get("company_name", ""),
            candidate.get("snippet", ""),
            root_title,
            root_text,
            source_page.get("title", "") if source_page else "",
            source_page.get("text", "") if source_page else "",
            final_url,
        ]
        if part
    )
    needs_context_page = (
        company_footprint_score(initial_combined) < 6
        or (city_fold and city_fold not in fold_text(initial_combined))
    )

    company_context_page = None
    if needs_context_page:
        for suffix in common_company_paths[:6]:
            probe_url = urljoin(final_url, suffix)
            fetched_page = fetch_page_evidence(probe_url, require_host=final_host)
            if not fetched_page:
                continue
            if normalize_company_site_url(fetched_page.get("url", "")) != final_url:
                continue
            if looks_like_directory_listing(
                fetched_page.get("title", ""),
                candidate.get("snippet", ""),
                fetched_page.get("url", ""),
                page_text=fetched_page.get("text", "")[:600],
            ):
                continue
            if looks_like_media_or_entertainment_page(
                fetched_page.get("title", ""),
                candidate.get("snippet", ""),
                fetched_page.get("url", ""),
                page_text=fetched_page.get("text", "")[:600],
            ):
                continue
            company_context_page = fetched_page
            pages.append(company_context_page)
            break

    seed_product_score = max(
        best_product_signal_score(keyword, candidate.get("snippet", ""), country=country),
        best_product_signal_score(
            keyword,
            " ".join(
                part
                for part in [
                    root_title,
                    root_text,
                    source_page.get("title", "") if source_page else "",
                    source_page.get("text", "") if source_page else "",
                ]
                if part
            ),
            country=country,
        ),
    )
    if keyword and seed_product_score < 8:
        candidate_links = []
        for page in [source_page, root_page, company_context_page]:
            if not page:
                continue
            candidate_links.extend(page.get("links", []))
        for link in sorted(candidate_links, key=lambda item: item.get("score", 0), reverse=True)[:2]:
            if time.time() >= deadline:
                break
            fetched_page = fetch_page_evidence(link.get("url", ""), require_host=final_host)
            if not fetched_page:
                continue
            if looks_like_directory_listing(
                fetched_page.get("title", ""),
                candidate.get("snippet", ""),
                fetched_page.get("url", ""),
                page_text=fetched_page.get("text", "")[:600],
            ):
                continue
            if looks_like_media_or_entertainment_page(
                fetched_page.get("title", ""),
                candidate.get("snippet", ""),
                fetched_page.get("url", ""),
                page_text=fetched_page.get("text", "")[:600],
            ):
                continue

            fetched_product_score = best_product_signal_score(
                keyword,
                " ".join(
                    part
                    for part in [fetched_page.get("title", ""), fetched_page.get("text", ""), fetched_page.get("url", "")]
                    if part
                ),
                country=country,
            )
            if fetched_product_score <= seed_product_score:
                continue
            source_page = fetched_page
            seed_product_score = fetched_product_score
            pages.append(source_page)
            if fetched_product_score >= 18:
                break

    location_pages = []
    if city_tokens or country_tokens:
        location_candidates = []
        seen_location_links = set()
        for page in [company_context_page, source_page, root_page]:
            if not page:
                continue
            for link in page.get("links", []):
                if link.get("location_score", 0) <= 0:
                    continue
                if link["url"] in seen_location_links:
                    continue
                seen_location_links.add(link["url"])
                location_candidates.append(link)

        for link in sorted(location_candidates, key=lambda item: (item.get("location_score", 0), item.get("score", 0)), reverse=True)[:2]:
            if time.time() >= deadline:
                break
            fetched_page = fetch_page_evidence(link.get("url", ""), require_host=final_host)
            if not fetched_page:
                continue
            if normalize_company_site_url(fetched_page.get("url", "")) != final_url:
                continue
            if looks_like_directory_listing(
                fetched_page.get("title", ""),
                candidate.get("snippet", ""),
                fetched_page.get("url", ""),
                page_text=fetched_page.get("text", "")[:600],
            ):
                continue
            if looks_like_media_or_entertainment_page(
                fetched_page.get("title", ""),
                candidate.get("snippet", ""),
                fetched_page.get("url", ""),
                page_text=fetched_page.get("text", "")[:600],
            ):
                continue
            location_pages.append(fetched_page)
            pages.append(fetched_page)

    combined = " ".join(
        part
        for page in pages
        for part in [page.get("title", ""), page.get("text", ""), page.get("url", "")]
        if part
    )
    combined = " ".join(
        part
        for part in [candidate.get("company_name", ""), candidate.get("snippet", ""), combined, final_url]
        if part
    )
    combined_fold = fold_text(combined)
    company_context = " ".join(
        part
        for part in [
            candidate.get("company_name", ""),
            root_title,
            root_text,
            company_context_page.get("title", "") if company_context_page else "",
            company_context_page.get("text", "") if company_context_page else "",
            final_url,
        ]
        if part
    )
    product_context = " ".join(
        part
        for part in [
            candidate.get("snippet", ""),
            source_page.get("title", "") if source_page else "",
            source_page.get("text", "") if source_page else "",
            root_title,
            root_text[:800],
        ]
        if part
    )
    location_context = " ".join(
        part
        for page in [source_page, company_context_page, *location_pages, root_page]
        if page
        for part in [
            page.get("title", ""),
            page.get("location_text", ""),
            page.get("text", "")[:900],
            page.get("url", ""),
        ]
        if part
    )
    location_context_fold = fold_text(location_context)

    name_overlap = company_token_set(candidate.get("company_name", "")) & company_token_set(
        f"{company_context} {extract_company_name_from_url(final_url)}"
    )
    product_score = max(
        best_product_signal_score(keyword, candidate.get("snippet", ""), country=country),
        best_product_signal_score(keyword, product_context, country=country),
        best_product_signal_score(keyword, combined, country=country),
    )
    footprint_score = company_footprint_score(company_context)
    seller_score = seller_intent_score(company_context)
    sector_hit = bool(sector_terms and any(item in combined_fold for item in sector_terms))
    city_hit = bool(city_fold and city_fold in location_context_fold)
    country_hit = bool(country_tokens and any(token in location_context_fold for token in country_tokens))
    location_role_hit = any(token in location_context_fold for token in LOCATION_ROLE_HINT_TOKENS)
    location_page_hit = any(token in location_context_fold for token in LOCATION_PAGE_HINT_TOKENS)
    conflicting_city = ""
    if city_fold and country_fold in {"turkiye", "turkey", "tr"}:
        turkish_city_tokens = {
            fold_text(name)
            for name in [
                "Adana", "Adiyaman", "Afyonkarahisar", "Agri", "Aksaray", "Amasya", "Ankara", "Antalya",
                "Ardahan", "Artvin", "Aydin", "Balikesir", "Bartin", "Batman", "Bayburt", "Bilecik",
                "Bingol", "Bitlis", "Bolu", "Burdur", "Bursa", "Canakkale", "Cankiri", "Corum",
                "Denizli", "Diyarbakir", "Duzce", "Edirne", "Elazig", "Erzincan", "Erzurum",
                "Eskisehir", "Gaziantep", "Giresun", "Gumushane", "Hakkari", "Hatay", "Igdir", "Isparta",
                "Istanbul", "Izmir", "Kahramanmaras", "Karabuk", "Karaman", "Kars", "Kastamonu",
                "Kayseri", "Kirikkale", "Kirklareli", "Kirsehir", "Kilis", "Kocaeli", "Konya", "Kutahya",
                "Malatya", "Manisa", "Mardin", "Mersin", "Mugla", "Mus", "Nevsehir", "Nigde", "Ordu",
                "Osmaniye", "Rize", "Sakarya", "Samsun", "Sanliurfa", "Siirt", "Sinop", "Sirnak",
                "Sivas", "Tekirdag", "Tokat", "Trabzon", "Tunceli", "Usak", "Van", "Yalova", "Yozgat",
                "Zonguldak",
            ]
        }
        other_city_hits = sorted(
            token for token in turkish_city_tokens
            if token != city_fold and token in location_context_fold
        )
        conflicting_city = other_city_hits[0] if other_city_hits else ""

    score = seller_score + footprint_score + product_score

    if k_fold and k_fold in combined_fold and product_score < 30:
        score += 18
    if sector_hit or (s_fold and s_fold in combined_fold):
        score += 10
    if city_hit:
        score += 20
    elif city_fold:
        score -= 10 if conflicting_city else 2
    if country_hit:
        score += 14 if country_code_for(country) not in {"", "TR"} else 6
    elif country_fold:
        score -= 4
    if location_role_hit:
        score += 8
    if location_page_hit:
        score += 6
    if target_country_tld and target_country_tld in final_url.lower():
        score += 8
    if name_overlap:
        score += 18
    if final_url.endswith(".tr/") or ".com.tr/" in final_url:
        score += 6
    if final_url.rstrip("/").count("/") <= 2:
        score += 4
    if city_hit and product_score >= 12:
        score += 10
    if country_hit and product_score >= 12:
        score += 8

    if keyword and product_score < 8:
        if not relaxed or (product_score < 0 and not sector_hit and seller_score < 18 and footprint_score < 12):
            return None

    if footprint_score < 6 and seller_score < 18 and not name_overlap:
        return None

    if score < (20 if relaxed else 32):
        return None

    verified = dict(candidate)
    verified["company_name"] = best_company_name(
        candidate.get("company_name", ""),
        root_title,
        source_page.get("title", "") if source_page else "",
        extract_company_name_from_url(final_url),
    )
    verified["website"] = final_url
    verified["score"] = candidate.get("score", 0) + score
    verified["source_url"] = source_page.get("url", "") if source_page else candidate.get("source_url", "")
    verified["snippet"] = (
        (source_page.get("title", "") if source_page and product_score >= 12 else "")
        or candidate.get("snippet", "")
        or root_title
        or root_text[:220]
    )
    verified["match_mode"] = "relaxed" if relaxed else "strict"
    return verified


def find_company_website(company_name, keyword="", sector="", location="", country=""):
    """Find the official website while avoiding news, directories, and profile pages."""
    clean_name = best_company_name(company_name) or (company_name or "").strip()
    if len(clean_name) < 2:
        return None

    target_tld = country_tld_for(country)
    queries = dedupe_queries([
        build_query(f"\"{clean_name}\"", location, country, "official website"),
        build_query(f"\"{clean_name}\"", keyword, sector, location, country, "company"),
        build_query(f"\"{clean_name}\"", keyword, sector, location, country, "official site"),
        build_query(f"\"{clean_name}\"", location, country, "firma"),
        build_query(f"\"{clean_name}\"", location, country, "kurumsal"),
        build_query(f"site:{target_tld}", f"\"{clean_name}\"", "official") if target_tld else "",
    ])

    best = None
    seen_urls = set()
    for query in queries:
        for entry in search_engine_results(query, country=country, allow_ddg=True):
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
            if looks_like_directory_listing(title, snippet, normalized_url):
                continue

            score = score_company_website_match(clean_name, title, snippet, normalized_url)
            haystack = fold_text(f"{title} {snippet} {normalized_url}")
            if keyword and fold_text(keyword) in haystack:
                score += 6
            if sector and fold_text(sector) in haystack:
                score += 4
            if location:
                if fold_text(location) in haystack:
                    score += 8
                else:
                    score -= 18
            if country and fold_text(country) in haystack:
                score += 5
            if urlparse(normalized_url).path in {"", "/"}:
                score += 5

            if score < 34:
                continue

            candidate = {
                "company_name": best_company_name(clean_name, title, extract_company_name_from_url(normalized_url)),
                "website": normalized_url,
                "source_url": url,
                "score": score,
                "is_linkedin": False,
                "snippet": snippet or f"Firma: {clean_name}",
            }
            if not best or score > best["score"]:
                best = candidate

        if best and best["score"] >= 88:
            break

    if best:
        verified_best = verify_company_homepage(best, keyword, sector, location=location, country=country)
        if verified_best:
            return verified_best
        relaxed_best = verify_company_homepage(best, keyword, sector, location=location, country=country, relaxed=True)
        if relaxed_best:
            return relaxed_best

    guessed = guess_company_website(clean_name, country=country)
    if guessed:
        verified_guess = verify_company_homepage(guessed, keyword, sector, location=location, country=country)
        if verified_guess:
            return verified_guess
        relaxed_guess = verify_company_homepage(guessed, keyword, sector, location=location, country=country, relaxed=True)
        if relaxed_guess:
            return relaxed_guess
        if not best or guessed["score"] >= best["score"]:
            return guessed

    return best


def search_linkedin_company_pages_http(keyword, sector, location="", country="", limit=5, li_at=""):
    """Search for LinkedIn company pages with cleaner names and fewer noisy queries."""
    deadline = time.time() + 25
    sector_variants = split_search_phrases(sector, max_parts=4) + translated_sector_variants(sector, country)
    if not sector_variants:
        sector_variants = [repair_text(sector)]
    keyword_variants = split_search_phrases(keyword, max_parts=4) + translated_keyword_variants(keyword, country)
    queries = []
    for kw in list(dict.fromkeys(item for item in keyword_variants if item))[:5]:
        for sector_term in sector_variants[:3] or [""]:
            queries.extend([
                build_query("site:linkedin.com/company/", f"\"{kw}\"", sector_term, location, country),
                build_query("site:linkedin.com/company/", kw, sector_term, location, country, "manufacturer"),
                build_query("site:linkedin.com/company/", kw, sector_term, location, country, "supplier"),
                build_query("site:www.linkedin.com/company/", kw, sector_term, location, country),
            ])
    queries = dedupe_queries(queries)

    found = {}
    for query in queries:
        if time.time() >= deadline or len(found) >= max(limit * 3, 8):
            break
        for entry in search_engine_results(query, country=country, allow_ddg=True):
            if time.time() >= deadline or len(found) >= max(limit * 3, 8):
                break
            url = normalize_linkedin_company_url(entry.get("href", ""))
            if not url:
                continue
            lower_url = url.lower()
            if any(x in lower_url for x in ["/in/", "/people/", "/pub/", "/jobs/", "/pulse/", "/search/", "/posts/", "/feed/", "/groups/", "/events/", "/school/", "/showcase/"]):
                continue

            title = entry.get("title", "").strip()
            snippet = entry.get("body", "").strip()
            name = best_company_name(title, extract_company_name_from_url(url))
            if len(name) < 2:
                continue

            score = score_candidate(
                {"title": title, "body": snippet, "href": url},
                keyword,
                sector,
                location,
                country,
            ) + 120

            haystack = fold_text(f"{title} {snippet}")
            if keyword and (fold_text(keyword) in haystack or any(fold_text(item) in haystack for item in translated_keyword_variants(keyword, country))):
                score += 10
            if sector and any(fold_text(item) in haystack for item in sector_variants):
                score += 6

            if score < 40:
                continue

            if url not in found or score > found[url]["score"]:
                found[url] = {
                    "company_name": name,
                    "linkedin_url": url,
                    "title": snippet,
                    "score": score,
                }

    ranked = sorted(found.values(), key=lambda item: item["score"], reverse=True)
    final_results = []
    for row in ranked[: max(limit * 4, 12)]:
        if time.time() >= deadline:
            break
        validated = validate_linkedin_company_candidate(
            row["company_name"],
            row["linkedin_url"],
            keyword=keyword,
            sector=sector,
            location=location,
            country=country,
            li_at=li_at,
            title_hint=row["title"],
            website_hint="",
        )
        if not validated:
            continue
        validated["score"] = validated.get("score", 0) + row["score"]
        final_results.append(validated)
        if len(final_results) >= limit:
            break

    if len(final_results) < limit:
        seen_urls = {item.get("linkedin_url", "") for item in final_results}
        for row in ranked[: max(limit * 5, 14)]:
            if time.time() >= deadline:
                break
            if row.get("linkedin_url", "") in seen_urls:
                continue
            relaxed_match = validate_linkedin_company_candidate(
                row["company_name"],
                row["linkedin_url"],
                keyword=keyword,
                sector=sector,
                location=location,
                country=country,
                li_at=li_at,
                title_hint=row["title"],
                website_hint="",
                relaxed=True,
            )
            if not relaxed_match:
                continue
            relaxed_match["score"] = relaxed_match.get("score", 0) + row["score"]
            final_results.append(relaxed_match)
            seen_urls.add(relaxed_match.get("linkedin_url", ""))
            if len(final_results) >= limit:
                break

    return final_results


def score_candidate(entry, keyword, sector, location, country):
    """Score company intent with heavier penalties for info pages and directories."""
    haystack = fold_text(f"{entry.get('title', '')} {entry.get('body', '')} {entry.get('href', '')}").strip()
    if not haystack:
        return 0

    sector_terms = [fold_text(item) for item in (split_search_phrases(sector, max_parts=5) + translated_sector_variants(sector, country))]
    city_fold = fold_text(location)
    country_tokens = country_alias_tokens(country)
    translated_keywords = [fold_text(item) for item in translated_keyword_variants(keyword, country)]

    score = 0
    product_score = best_product_signal_score(keyword, haystack, country=country)
    keyword_tokens = set(search_term_tokens(keyword))
    haystack_tokens = set(search_term_tokens(haystack))
    token_overlap = len(keyword_tokens & haystack_tokens)
    score += product_score
    if translated_keywords and any(item in haystack for item in translated_keywords):
        score += 18
        product_score = max(product_score, 14)
    if len(keyword_tokens) >= 2 and token_overlap >= 1:
        score += 14
    if sector_terms and any(item in haystack for item in sector_terms):
        score += 6
    score += seller_intent_score(haystack)
    score += company_footprint_score(haystack)

    if any(token in haystack for token in INDUSTRY_TOKENS):
        score += 3
    if any(token in haystack for token in ["manufacturer", "uretim", "uretici", "sanayi", "industrial", "fabrik"]):
        score += 7

    city_hit = bool(city_fold and city_fold in haystack)
    country_hit = bool(country_tokens and any(token in haystack for token in country_tokens))
    if city_hit:
        score += 42
    elif city_fold:
        score -= 18
    if country_hit:
        score += 10

    domain = entry.get("href", "").lower()
    c_fold = country.lower().strip()
    is_foreign = c_fold not in ["turkiye", "turkey", "tr"]

    if (".tr" in domain or ".com.tr" in domain) and "linkedin.com" not in domain:
        if is_foreign:
            score -= 60
        else:
            score += 12
            country_hit = True

    target_tld = TLD_MAP.get(c_fold, "")
    if not target_tld and is_foreign:
        c_code = ISO_COUNTRY_MAP.get(c_fold, "").lower()
        if c_code:
            target_tld = f".{c_code}"
    if target_tld and domain.endswith(target_tld):
        score += 18
        country_hit = True

    if country_tokens and not country_hit:
        score -= 4

    if any(x in domain for x in ["/in/", "/pub/", "/people/"]):
        score -= 100
    if host_is_directory(entry.get("href", "")) or looks_like_directory_listing(entry.get("title", ""), entry.get("body", ""), entry.get("href", "")):
        score -= 160
    if looks_like_media_or_entertainment_page(entry.get("title", ""), entry.get("body", ""), entry.get("href", "")):
        score -= 220
    if looks_like_article_or_info_page(entry.get("title", ""), entry.get("body", ""), entry.get("href", "")):
        score -= 120
    if urlparse(entry.get("href", "")).path in {"", "/"} and "linkedin.com" not in domain:
        score += 8
    if keyword and product_score < 0:
        score -= 12 if token_overlap else 30

    return score


def search_web_companies(keyword, sector, location="", country="", limit=6):
    """Find seller/company websites and verify them before surfacing results."""
    deadline = time.time() + 40
    target_tld = country_tld_for(country)
    q_loc = f"\"{location}\"" if location else ""
    negations = "-news -blog -article -wiki -pdf -datasheet -manual -jobs -career -careers -film -movie -dizi -izle -fragman -haber -haberler -press -basin -duyuru -announcement -review -reviews -inceleme -yorum"
    country_fold = fold_text(country)
    product_phrase = f"\"{keyword}\"" if keyword else ""
    ascii_keyword = fold_text(keyword)
    product_tokens = search_term_tokens(keyword, min_len=4)
    sector_variants = split_search_phrases(sector, max_parts=4) + translated_sector_variants(sector, country)
    if not sector_variants:
        sector_variants = [repair_text(sector)]
    token_phrase = " ".join(f"\"{token}\"" for token in product_tokens[:3]) if len(product_tokens) >= 2 else ""
    focus_tokens = dedupe_queries([
        f"\"{product_tokens[-1]}\"" if product_tokens else "",
        product_tokens[-1] if product_tokens else "",
        f"\"{max(product_tokens, key=len)}\"" if len(product_tokens) >= 2 else "",
        max(product_tokens, key=len) if len(product_tokens) >= 2 else "",
    ])
    turkish_query_variants = []
    turkish_focus_tokens = []
    if country_fold in {"turkiye", "turkey", "tr"} and keyword and keyword.isascii():
        turkish_map = {"c": "ç", "g": "ğ", "o": "ö", "s": "ş", "u": "ü"}
        raw_tokens = [token for token in re.split(r"\s+", keyword.strip()) if len(token) >= 3]
        focus_source_tokens = set()
        if raw_tokens:
            focus_source_tokens.add(raw_tokens[-1].lower())
        for idx, token in enumerate(raw_tokens[:4]):
            token_variants = []
            lower_token = token.lower()
            for pos, char in enumerate(lower_token):
                mapped = turkish_map.get(char)
                if not mapped:
                    continue
                variant = token[:pos] + mapped + token[pos + 1:]
                if variant != token and variant not in token_variants:
                    token_variants.append(variant)
            for variant in token_variants[:4]:
                joined = list(raw_tokens)
                joined[idx] = variant
                variant_query = " ".join(joined)
                turkish_query_variants.append(variant_query)
                turkish_query_variants.append(f"\"{variant_query}\"")
                if lower_token in focus_source_tokens:
                    turkish_focus_tokens.append(variant)
                    turkish_focus_tokens.append(f"\"{variant}\"")
    keyword_variants = dedupe_queries([
        product_phrase,
        keyword,
        f"\"{ascii_keyword}\"" if ascii_keyword and ascii_keyword != (keyword or "").lower() else "",
        ascii_keyword if ascii_keyword and ascii_keyword != (keyword or "").lower() else "",
        token_phrase,
        *translated_keyword_variants(keyword, country),
        *focus_tokens,
        *turkish_focus_tokens,
        *turkish_query_variants,
    ])

    if country_fold in {"turkiye", "turkey", "tr"}:
        legal_terms = ["ltd", "sti", "a.s", "sanayi", "ticaret", "kurumsal", "iletisim", "hakkimizda"]
        seller_terms = ["firma", "sirket", "uretici", "imalatci", "tedarikci", "satici", "atolye", "isletme", "urunler"]
    else:
        legal_terms = ["inc", "llc", "gmbh", "company", "corporate", "official", "contact", "about"]
        seller_terms = ["company", "manufacturer", "supplier", "workshop", "dealer", "official", "trading", "contact", "products"]
    localized_terms = country_query_terms(country)

    strict_queries = []
    fallback_queries = []
    for kw in keyword_variants or [product_phrase or keyword]:
        for sector_term in sector_variants[:3] or [""]:
            strict_queries.extend([
                build_query(kw, sector_term, q_loc, country, seller_terms[0], negations),
                build_query(kw, sector_term, q_loc, country, seller_terms[1], negations),
                build_query(kw, sector_term, q_loc, country, seller_terms[2], negations),
                build_query(kw, q_loc, country, legal_terms[0], legal_terms[1], negations),
                build_query(kw, q_loc, country, legal_terms[2], legal_terms[3], negations),
                build_query(kw, q_loc, country, seller_terms[6], seller_terms[8], negations),
            ])
            fallback_queries.extend([
                build_query(kw, sector_term, country, seller_terms[1], negations),
                build_query(kw, sector_term, country, seller_terms[2], negations),
                build_query(kw, country, seller_terms[0], seller_terms[6], negations),
                build_query(kw, seller_terms[3], seller_terms[8], negations),
                build_query(kw, legal_terms[4], legal_terms[5], negations),
                build_query(kw, legal_terms[6], legal_terms[7], negations),
            ])
        for local_term in localized_terms[:6]:
            for sector_term in sector_variants[:2] or [""]:
                strict_queries.append(build_query(kw, sector_term, q_loc, country, local_term, negations))
            fallback_queries.append(build_query(kw, country, local_term, negations))
        if target_tld:
            for sector_term in sector_variants[:2] or [""]:
                strict_queries.extend([
                    build_query(f"site:{target_tld}", kw, q_loc, seller_terms[1], legal_terms[0]),
                    build_query(f"site:{target_tld}", kw, sector_term, q_loc, seller_terms[2]),
                ])
            fallback_queries.append(build_query(f"site:{target_tld}", kw, country, seller_terms[0]))

    final_results = {}
    verified_results = []
    seen_domains = set()
    verification_attempts = set()

    def collect_candidates(queries, budget, query_cap):
        for query in dedupe_queries(queries)[:query_cap]:
            if time.time() >= deadline or len(final_results) >= budget:
                break
            for entry in search_engine_results(query, country=country, allow_ddg=True):
                if time.time() >= deadline or len(final_results) >= budget:
                    break
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
                if len(final_results) >= budget:
                    break

    def append_verified_results(relaxed=False, candidate_cap=0):
        top_candidates = sorted(final_results.values(), key=lambda item: item["score"], reverse=True)[: candidate_cap or max(limit * 3, 9)]
        for candidate in top_candidates:
            if time.time() >= deadline:
                break
            attempt_key = ("relaxed" if relaxed else "strict", candidate.get("website", ""))
            if attempt_key in verification_attempts:
                continue
            verification_attempts.add(attempt_key)
            verified = verify_company_homepage(
                candidate,
                keyword,
                sector,
                location=location,
                country=country,
                relaxed=relaxed,
            )
            if not verified:
                continue
            host = urlparse(verified.get("website", "")).netloc.lower()
            if host in seen_domains:
                continue
            seen_domains.add(host)
            verified_results.append(verified)
            if len(verified_results) >= limit:
                break

    collect_candidates(strict_queries, max(limit * 5, 18), 10)
    append_verified_results(relaxed=False, candidate_cap=max(limit * 3, 10))
    if len(verified_results) < limit and time.time() < deadline:
        collect_candidates(fallback_queries, max(limit * 7, 24), 8)
        append_verified_results(relaxed=False, candidate_cap=max(limit * 4, 14))
    if len(verified_results) < limit and time.time() < deadline:
        append_verified_results(relaxed=True, candidate_cap=max(limit * 6, 20))

    return verified_results[:limit]
