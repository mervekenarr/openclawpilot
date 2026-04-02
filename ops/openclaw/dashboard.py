import streamlit as st
import os
import json
import time
import requests
import re
import base64
import html
import unicodedata
from urllib.parse import urlparse
from pathlib import Path
from engine import (
    search_web_companies,
    search_linkedin_companies,
    read_website_content,
)
import pandas as pd
import io

# Ayar Dosyası Yolu
ENV_PATH = ".env"
APP_DIR = Path(__file__).resolve().parent
LOGO_PATH = APP_DIR / "assets" / "logo.png"
HTTP_SESSION = requests.Session()
HTTP_SESSION.trust_env = False
DISCOVERED_LLM_BASE_URL = ""
DISCOVERED_LLM_MODEL = ""
DISCOVERED_LLM_FETCHED = False

# ==========================================
# GÜVENLİ AYAR YÖNETİMİ
# ==========================================
def is_allowed_domain(url, is_foreign=False):
    """Çöp siteleri ve sosyal medyayı eler. Yurt dışı aramasında Türk sitelerini bloklar."""
    domain = url.lower()
    if is_foreign and (".tr" in domain or ".com.tr" in domain) and "linkedin.com" not in domain:
        return False
    return not any(token in domain for token in BLOCKED_HOST_TOKENS)

def load_secure_settings():
    """Çevresel değişkenleri (.env) yükler."""
    settings = {
        "LINKEDIN_SESSION_TOKEN": "",
        "GATEWAY_PASSWORD": "openclaw123"
    }
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line:
                    key, val = line.strip().split("=", 1)
                    settings[key] = val
    return settings

def save_secure_setting(key, value):
    """Ayar kaydeder."""
    lines = []
    found = False
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
    
    new_lines = []
    for line in lines:
        if line.startswith(f"{key}="):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)
            
    if not found:
        new_lines.append(f"{key}={value}\n")
        
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


TEXT_FIXUPS = {
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
    """Arayuzde gorunen metinleri temizler ve bozuk karakterleri duzeltir."""
    clean = html.unescape((text or "").replace("\xa0", " "))
    for bad, good in TEXT_FIXUPS.items():
        clean = clean.replace(bad, good)
    clean = clean.replace("\u200b", "")
    return re.sub(r"\s+", " ", clean).strip()


def normalize_text(text):
    """Metni karsilastirma ve kisa kalite kontrolleri icin normalize eder."""
    clean = repair_text(text)
    normalized = unicodedata.normalize("NFKD", clean)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return normalized.lower()


def keyword_tokens(text, min_len=3):
    return [token for token in re.split(r"[^a-z0-9]+", normalize_text(text)) if len(token) >= min_len]


def normalize_company_key(name):
    """Farkli kaynaklardaki firma adlarini tek anahtarda toplar."""
    raw = normalize_text((name or "").split("-")[0].split("|")[0].strip())
    raw = re.sub(r"\b(?:inc|ltd|llc|corp|co|company|holding|group|san|tic|as|a s|a\\.s|sti|sirketi|limited)\b", " ", raw)
    raw = re.sub(r"[^a-z0-9]+", " ", raw)
    return " ".join(raw.split())


def fallback_name_from_url(url):
    """Uzun veya kirli basliklarda hosttan daha okunur firma adi uret."""
    parsed = urlparse(url or "")
    host = parsed.netloc.lower().replace("www.", "")
    if "linkedin.com" in host and parsed.path:
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        label = parts[-1] if parts else ""
    else:
        label = host.split(".")[0] if host else ""
    label = re.sub(r"[-_]+", " ", label).strip()
    return repair_text(label).title()


def display_company_name(name, url=""):
    """Ekranda devasa basliklar yerine kisa ve okunur firma adi goster."""
    clean = repair_text(name).strip(" |-")
    fallback = fallback_name_from_url(url)
    words = clean.split()
    if not clean:
        clean = fallback
        words = clean.split()

    low_words = [normalize_text(word) for word in words]
    noisy_name = (
        len(words) > 4
        or len(clean) > 70
        or sum(1 for word in words if len(word) <= 2) >= 2
        or any(token in low_words[:4] for token in ["izmir", "ankara", "istanbul", "mahallesi", "organize", "sanayi"])
        or bool(re.search(r"\b\d{5,}\b", clean))
    )

    if noisy_name:
        if fallback:
            clean = fallback
        else:
            clean = " ".join(words[:4]).strip()
    elif len(words) > 8 or len(clean) > 90:
        if fallback:
            clean = fallback
        else:
            clean = " ".join(words[:8]).strip()

    return repair_text(clean)


def compact_snippet(text, fallback_url=""):
    """Sonuc aciklamasini kisa ve okunur halde tut."""
    clean = repair_text(text)
    if not clean:
        return repair_text(fallback_url)
    if len(clean) <= 180:
        return clean
    return clean[:177].rstrip() + "..."


def load_logo_data_uri():
    """Logo dosyasini base64 data URI olarak hazirlar."""
    if not LOGO_PATH.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(LOGO_PATH.read_bytes()).decode()


def friendly_model_status(info):
    low = normalize_text(info)
    if not info:
        return "Yerel taslak kullanıldı."
    if "read timed out" in low or "timeout" in low or "time out" in low:
        return "Yerel model zaman aşımına uğradı."
    if "connection refused" in low or "failed to establish a new connection" in low:
        return "Yerel model servisine bağlanılamadı."
    if low.startswith("hata:"):
        return repair_text(info)
    if "zira:" in low:
        return repair_text(info.replace("Zira:", "").strip())
    return repair_text(info)


def cleaned_sentences(text, max_sentences=2):
    clean = repair_text(text)
    if not clean:
        return []
    raw_parts = re.split(r"(?<=[.!?])\s+", clean)
    sentences = []
    banned = {"cookie", "privacy", "gizlilik", "javascript", "oturum", "login"}
    for part in raw_parts:
        part = part.strip(" -")
        if len(part) < 25:
            continue
        if any(token in normalize_text(part) for token in banned):
            continue
        if part not in sentences:
            if part[-1] not in ".!?":
                part = part.rstrip(",;:") + "."
            sentences.append(part)
        if len(sentences) >= max_sentences:
            break
    if not sentences and clean:
        chunk = clean[:220].rstrip(" ,;:")
        if chunk:
            sentences.append(chunk + ("." if chunk[-1] not in ".!?" else ""))
    return sentences


def fallback_fit_score(company_name, company_data, website_text, product, sector, city, country):
    haystack = normalize_text(
        " ".join(
            [
                company_name,
                company_data.get("snippet", ""),
                company_data.get("website_url", ""),
                company_data.get("linkedin_url", ""),
                website_text,
            ]
        )
    )
    score = 5
    product_hits = sum(1 for token in keyword_tokens(product, min_len=4) if token in haystack)
    sector_hits = sum(1 for token in keyword_tokens(sector, min_len=4) if token in haystack)
    location_hits = sum(1 for token in keyword_tokens(f"{city} {country}", min_len=3) if token in haystack)
    if product_hits >= 2:
        score += 2
    elif product_hits == 1:
        score += 1
    if sector_hits:
        score += 1
    if location_hits:
        score += 1
    if company_data.get("website_url"):
        score += 1
    return max(4, min(score, 9))


def fallback_summary(company_name, company_data, website_text, product, sector):
    sentences = cleaned_sentences(website_text, max_sentences=2)
    if len(sentences) >= 2:
        return " ".join(sentences[:2])

    snippet_sentences = cleaned_sentences(company_data.get("snippet", ""), max_sentences=2)
    if len(snippet_sentences) >= 2:
        return " ".join(snippet_sentences[:2])
    if len(snippet_sentences) == 1:
        focus = repair_text(product or sector or "ilgili ürün grubu")
        return f"{snippet_sentences[0]} {company_name}, {focus} odağında değerlendirilebilecek bir firma profili sunuyor."

    focus = repair_text(product or sector or "ilgili ürün grubu")
    return (
        f"{company_name}, {focus} odağında faaliyet gösteren bir firma olarak görünüyor. "
        "Satın alma ve iş birliği değerlendirmesi için temel firma sinyalleri sunuyor."
    )


def fallback_sales_script(company_name, product, sector, city, country):
    focus = repair_text(product or sector or "ilgili ürün grubu")
    location_label = " / ".join(part for part in [repair_text(city), repair_text(country)] if part)
    location_line = (
        f"Eğer {location_label} tarafında yeni tedarikçi veya proje çözüm ortağı arıyorsanız,"
        if location_label
        else "Eğer yeni bir tedarikçi veya proje çözüm ortağı arıyorsanız,"
    )
    return (
        f"Merhaba {company_name} ekibi,\n\n"
        f"{focus} alanındaki faaliyetlerinizi inceledik. Dikkan olarak vana, akış kontrol ve proje bazlı teknik ihtiyaçlarda hızlı teklif ve teknik değerlendirme desteği sunuyoruz.\n\n"
        f"{location_line} ürün gamınıza uygun seçenekleri ve kısa bir teklif çerçevesini paylaşabiliriz. "
        "Uygunsanız bu hafta 15 dakikalık bir görüşme planlayalım."
    )


def build_analysis_fallback(company_name, company_data, website_text, product, sector, city, country):
    return {
        "score": fallback_fit_score(company_name, company_data, website_text, product, sector, city, country),
        "summary": fallback_summary(company_name, company_data, website_text, product, sector),
        "sales_script": fallback_sales_script(company_name, product, sector, city, country),
    }

settings = load_secure_settings()
LOGO_DATA_URI = load_logo_data_uri()

# --- KEŞİF HAFIZASI & RAPORLAMA ---
if "seen_urls" not in st.session_state:
    st.session_state.seen_urls = set()
if "current_results" not in st.session_state:
    st.session_state.current_results = []

st.set_page_config(page_title="Dikkan | Satış İstihbarat Asistanı", page_icon="🤖", layout="wide")

# ==========================================
# PREMIUM UI (CSS INJECTION)
# ==========================================
st.markdown("""
    <style>
    /* Global Styles & Light Mode Enforcement */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    .stApp {
        background-color: #FFFFFF !important;
        color: #262730 !important;
    }
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    /* GÖRSEL BÜYÜTME BUTONUNU KALDIR (Streamlit Modern Selectors) */
    [data-testid="stImageHoverControls"] {
        display: none !important;
    }
    button[title="Enlarge image"] {
        display: none !important;
    }
    
    /* Sidebar Styling */
    [data-testid="stSidebar"] {
        background-color: #F8F9FA !important;
        border-right: 1px solid #E9ECEF !important;
    }

    /* Header Bar Fix */
    header[data-testid="stHeader"] {
        background-color: #FFFFFF !important;
        border-bottom: 1px solid #E9ECEF !important;
    }
    
    /* Input Fields */
    .stTextInput>div>div>input {
        background-color: #FFFFFF !important;
        color: #262730 !important;
        border: 1px solid #DEE2E6 !important;
        border-radius: 8px !important;
    }
    
    /* Buttons */
    .stButton>button {
        background-color: #EC6602 !important;
        color: #FFFFFF !important;
        border-radius: 8px !important;
        border: none !important;
        padding: 0.6rem 1.2rem !important;
        font-weight: 600 !important;
        width: 100% !important;
        transition: all 0.2s ease !important;
    }
    
    .stButton>button:hover {
        background-color: #D15A02 !important;
        box-shadow: 0 4px 12px rgba(236, 102, 2, 0.2) !important;
        transform: translateY(-1px);
    }
    
    /* Expanders & Cards */
    .stExpander {
        background-color: #FFFFFF !important;
        border: 1px solid #E9ECEF !important;
        border-radius: 12px !important;
        box-shadow: 0 2px 4px rgba(0,0,0,0.03) !important;
        margin-bottom: 1.5rem !important;
    }
    
    /* Metrics */
    [data-testid="stMetricValue"] {
        color: #EC6602 !important;
        font-weight: 700 !important;
    }
    
    .stMetric {
        background-color: #FFF9F5 !important;
        padding: 15px !important;
        border-radius: 10px !important;
        border: 1px solid #FFE8D6 !important;
    }
    
    /* Headers & Text & Labels */
    h1, h2, h3, label, .stMarkdown p {
        color: #1A202C !important;
        font-weight: 600 !important;
    }
    
    .stTextInput label {
        color: #2D3748 !important;
        font-weight: 600 !important;
    }

    /* Input Field Text & Placeholders */
    .stTextInput>div>div>input {
        background-color: #FFFFFF !important;
        color: #1A202C !important;
        border: 1px solid #DEE2E6 !important;
        border-radius: 8px !important;
    }
    
    ::placeholder {
        color: #A0AEC0 !important;
        opacity: 1; /* Firefox fix */
    }

    .header-style {
        color: #1A202C !important;
        letter-spacing: -0.02em;
    }
    
    /* Status Messages */
    .stAlert {
        border-radius: 10px !important;
    }
    
    /* Horizontal Dividers */
    hr {
        border-top: 1px solid #E9ECEF !important;
    }
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# LLM BRIDGE (ROBUST HTTP + SPEED TEST)
# ==========================================
def resolve_local_llm_runtime(preferred_model=""):
    """Yerel ve gercekten kurulu modeli tercih et; uzaktaki timeout'a saplanma."""
    global DISCOVERED_LLM_BASE_URL, DISCOVERED_LLM_MODEL, DISCOVERED_LLM_FETCHED

    preferred = (preferred_model or settings.get("OLLAMA_MODEL", "")).strip()
    if DISCOVERED_LLM_BASE_URL and DISCOVERED_LLM_MODEL:
        return DISCOVERED_LLM_BASE_URL, DISCOVERED_LLM_MODEL
    if DISCOVERED_LLM_FETCHED:
        return DISCOVERED_LLM_BASE_URL or "http://127.0.0.1:11434", DISCOVERED_LLM_MODEL or preferred or "qwen2.5:3b"

    candidate_urls = []
    for base_url in ["http://127.0.0.1:11434", settings.get("OLLAMA_BASE_URL", "").rstrip("/")]:
        clean = (base_url or "").rstrip("/")
        if clean and clean not in candidate_urls:
            candidate_urls.append(clean)

    selected_base = ""
    selected_model = ""
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
            models = [model for model in models if model]
            if not models:
                continue
            selected_base = base_url
            selected_model = preferred if preferred and preferred in models else models[0]
            break
        except Exception:
            continue

    DISCOVERED_LLM_FETCHED = True
    DISCOVERED_LLM_BASE_URL = selected_base or settings.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/") or "http://127.0.0.1:11434"
    DISCOVERED_LLM_MODEL = selected_model or preferred or "qwen2.5:3b"
    return DISCOVERED_LLM_BASE_URL, DISCOVERED_LLM_MODEL


def call_llm_raw(messages, mode="direct", gateway_pw="", timeout=20):
    """SDK kullanmadan, doğrudan HTTP üzerinden Yapay Zeka ile konuşur."""
    if mode == "direct":
        base_url = settings.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        url = f"{base_url}/api/chat"
        payload = {
            "model": settings.get("OLLAMA_MODEL", "qwen2.5:14b"),
            "messages": messages,
            "stream": False,
            "options": {"num_ctx": 4096, "temperature": 0.1, "num_predict": 512}
        }
    else:
        url = "http://127.0.0.1:18789/v1/chat/completions"
        headers = {"Authorization": f"Bearer {gateway_pw}"}
        payload = {"model": f"ollama/{settings.get('OLLAMA_MODEL', 'qwen2.5:14b')}", "messages": messages, "stream": False}

    try:
        start_t = time.time()
        response = HTTP_SESSION.post(url, json=payload, timeout=timeout)
        end_t = time.time()
        
        if response.status_code == 200:
            res_json = response.json()
            content = res_json.get("message", {}).get("content", "") if mode == "direct" else res_json.get("choices", [{}])[0].get("message", {}).get("content", "")
            return content, f"{end_t-start_t:.1f}sn"
        return None, f"Hata: {response.status_code}"
    except Exception as e:
        return None, f"Zira: {str(e)}"

# --- GÜVENLİ OTURUM (ARKA PLAN) ---
# Token artık kullanıcıdan istenmiyor, doğrudan arka plandan okunuyor.
def call_llm_raw(messages, mode="direct", gateway_pw="", timeout=20):
    """Yapay zeka istegini once yerel modele, gerekirse gateway'e yollar."""
    attempts = []
    base_url, model_name = resolve_local_llm_runtime(settings.get("OLLAMA_MODEL", ""))
    direct_attempt = {
        "label": "Yerel model",
        "mode": "direct",
        "url": f"{base_url}/api/chat",
        "headers": {},
        "payload": {
            "model": model_name,
            "messages": messages,
            "stream": False,
            "options": {"num_ctx": 4096, "temperature": 0.1, "num_predict": 512},
        },
    }
    gateway_attempt = {
        "label": "Gateway",
        "mode": "gateway",
        "url": "http://127.0.0.1:18789/v1/chat/completions",
        "headers": {"Authorization": f"Bearer {gateway_pw}"} if gateway_pw else {},
        "payload": {
            "model": f"ollama/{model_name}",
            "messages": messages,
            "stream": False,
        },
    }

    if mode == "direct":
        attempts.append(direct_attempt)
        if gateway_pw:
            attempts.append(gateway_attempt)
    else:
        attempts.append(gateway_attempt)
        attempts.append(direct_attempt)

    errors = []
    for attempt in attempts:
        try:
            start_t = time.time()
            response = HTTP_SESSION.post(
                attempt["url"],
                json=attempt["payload"],
                headers=attempt["headers"],
                timeout=timeout,
            )
            elapsed = time.time() - start_t
            if response.status_code != 200:
                errors.append(f"{attempt['label']}: Hata {response.status_code}")
                continue

            res_json = response.json()
            if attempt["mode"] == "direct":
                content = res_json.get("message", {}).get("content", "")
            else:
                content = res_json.get("choices", [{}])[0].get("message", {}).get("content", "")
            if content:
                return content, f"{attempt['label']} | {elapsed:.1f} sn"
            errors.append(f"{attempt['label']}: Bos yanit")
        except Exception as exc:
            errors.append(f"{attempt['label']}: {exc}")

    return None, " | ".join(errors[:2]) if errors else "Model yanıtı alınamadı"


session_token = settings.get("LINKEDIN_SESSION_TOKEN", "")

# --- SİDEBAR DÜZENİ ---
with st.sidebar:
    # LOGO YERLEŞİMİ (Tam Kontrol İçin HTML Kullanımı - Büyütme Butonunu Devre Dışı Bırakır)
    if LOGO_DATA_URI:
        st.markdown(
            f"""
            <div style="display: flex; justify-content: center; margin-bottom: 20px;">
                <img src="{LOGO_DATA_URI}" width="220" style="object-fit: contain;">
            </div>
            """,
            unsafe_allow_html=True
        )
    else:
        st.title("🛡️ DIKKAN")
    
    st.markdown("<h3 class='header-style'>🤖 Keşif Parametreleri</h3>", unsafe_allow_html=True)
    sector = st.text_input("Hedef Sektör", placeholder="Örn: Insaat, Yazilim")
    product = st.text_input("Anahtar Kelime / Ürün", placeholder="Örn: Beton, CRM")
    
    st.markdown("---")
    st.subheader("📍 Lokasyon Filtresi")
    selected_country = st.text_input("Ülke", placeholder="Örn: Turkiye, Singapore, Germany", value="Turkiye")
    selected_city = st.text_input("Şehir", placeholder="Örn: Istanbul, Izmir, Berlin")

    # Arka planda varsayılan ayarlar (UI'dan kaldırıldı)
    direct_mode = True 

    if st.button("🗑️ Önbelleği Temizle", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    if st.button("🔄 Keşif Hafızasını Sıfırla", use_container_width=True):
        st.session_state.seen_urls = set()
        st.success("Hafıza sıfırlandı!")
        time.sleep(1)
        st.rerun()

st.markdown("<h1 style='color: #1A202C;'>🤖 Dikkan Satış İstihbarat Asistanı</h1>", unsafe_allow_html=True)
st.markdown("<p style='color: #718096; font-size: 1.1rem;'>Şirket keşfi, firma doğrulama ve satış aksiyonu taslakları tek ekranda.</p>", unsafe_allow_html=True)
st.markdown("---")

# --- NASIL KULLANILIR? REHBERİ ---
with st.expander("📖 Hızlı Başlangıç", expanded=False):
    st.markdown("""
    1. **Sektör ve ürün girin:** Sol panelden hedeflediğiniz sektör ile ürün anahtar kelimesini yazın.
    2. **Lokasyonu belirleyin:** Ülke ve gerekiyorsa şehir filtresini ekleyin.
    3. **Analizi başlatın:** Sistem web ve LinkedIn kaynaklarından firma adaylarını tarar.
    4. **Karar desteğini inceleyin:** Uygunluk skoru, firma özeti ve satış mesajı taslağını kontrol edin.
    5. **Raporu indirin:** Sonuçları sayfa sonundaki butonla CSV olarak dışa aktarın.
    """)

if not sector or not product:
    st.info("💡 Başlamak için sektör ve ürün bilgisini girin.")
else:
    if st.sidebar.button("🚀 Analizi Başlat", use_container_width=True, type="primary"):
        st.subheader(f"📊 {repair_text(product)} / {repair_text(sector)} Şirket Analiz Raporu")
        
        found_set = set()
        selection_lookup = {}
        findings_area = st.container()
        log_area = st.empty()
        debug_area = st.expander("🛠️ Teknik Detaylar / Loglar")

        # --- SMART START: HİBRİT ARAMA (DİNAMİK & ÇEŞİTLİ) ---
        import random
        st.info(f"⚡ {repair_text(sector)} sektörü için web ve LinkedIn kaynakları taranıyor.")
        
        with st.status("🔍 Yeni Şirketler Keşfediliyor...", expanded=True) as status:
            total_target = 5
            linkedin_target = 5
            web_target = 5
            discovery_limit = max(total_target + 5, 8)

            # 1. LinkedIn Aramasi
            l_data = search_linkedin_companies(
                product,
                sector,
                selected_city,
                li_at=session_token,
                limit=max(linkedin_target + 5, discovery_limit),
                country=selected_country,
            )
            num_l = len(l_data) if isinstance(l_data, list) else 0
            linkedin_status = os.getenv("OPENCLAW_LAST_LINKEDIN_STATUS", "unknown")
            
            # 2. Web Aramasi
            w_data = search_web_companies(product, sector, selected_city, selected_country, limit=max(web_target + 5, discovery_limit))
            
            status.update(label=f"✅ {num_l + len(w_data)} potansiyel şirket keşfedildi", state="complete")
            if num_l == 0:
                st.info(f"LinkedIn şirket araması sonuç vermedi. Durum: {linkedin_status}")
            else:
                st.caption(f"Kaynak dağılımı: LinkedIn={num_l}, Web={len(w_data)} | LinkedIn durumu: {linkedin_status}")
            
            # Yeni bir arama başladığında eski sonuçları temizle
            st.session_state.current_results = []
            
            # --- KAYNAKLARI AYRI TUT: LinkedIn aramasi ile Web aramasi birbirine karismasin ---
            linkedin_map = {}
            if isinstance(l_data, list):
                for c in l_data:
                    linkedin_url = c.get("linkedin_url", "")
                    if not linkedin_url or linkedin_url in st.session_state.seen_urls:
                        continue

                    lower_url = linkedin_url.lower()
                    is_garbage = any(x in lower_url for x in ["/search/", "/people/", "/pub/", "/in/", "/jobs/", "/pulse/", "/posts/", "/feed/", "/groups/", "/events/", "/showcase/"])
                    if is_garbage or "linkedin.com/company/" not in lower_url:
                        continue

                    name = display_company_name(c.get("company_name", ""), linkedin_url)
                    match_key = normalize_company_key(name)
                    if not match_key or len(name) < 2:
                        continue

                    candidate = {
                        "source": "linkedin",
                        "name": name,
                        "snippet": c.get("title", ""),
                        "score": c.get("score", 0),
                        "website_url": c.get("website_url", ""),
                        "linkedin_url": linkedin_url,
                    }
                    existing = linkedin_map.get(match_key)
                    if not existing or candidate["score"] > existing["score"]:
                        linkedin_map[match_key] = candidate

            web_map = {}
            for c in w_data:
                website_url = c.get("website", "")
                if not website_url or website_url in st.session_state.seen_urls:
                    continue

                name = display_company_name(c.get("company_name", ""), website_url)
                match_key = normalize_company_key(name)
                if not match_key or len(name) < 2:
                    continue
                candidate = {
                    "source": "web",
                    "name": name,
                    "snippet": c.get("snippet", ""),
                    "score": c.get("score", 0),
                    "website_url": website_url,
                    "linkedin_url": "",
                }
                existing = web_map.get(match_key)
                if not existing or candidate["score"] > existing["score"]:
                    web_map[match_key] = candidate

            linkedin_ranked = sorted(
                linkedin_map.values(),
                key=lambda item: (-item.get("score", 0), item["name"].lower()),
            )

            web_ranked = sorted(
                web_map.values(),
                key=lambda item: (-item.get("score", 0), item["name"].lower()),
            )

            web_selection = []
            linkedin_selection = []
            selected_company_keys = set()

            def add_unique_rows(target_rows, ranked_rows, max_items):
                for row in ranked_rows:
                    company_key = normalize_company_key(row["name"])
                    if not company_key or company_key in selected_company_keys:
                        continue
                    selected_company_keys.add(company_key)
                    target_rows.append(row)
                    if len(target_rows) >= max_items:
                        break

            add_unique_rows(web_selection, web_ranked, web_target)
            add_unique_rows(linkedin_selection, linkedin_ranked, linkedin_target)

            if len(selected_company_keys) < total_target:
                overflow_rows = sorted(
                    web_ranked[len(web_selection):] + linkedin_ranked[len(linkedin_selection):],
                    key=lambda item: (-item.get("score", 0), item["name"].lower()),
                )
                for row in overflow_rows:
                    company_key = normalize_company_key(row["name"])
                    if not company_key or company_key in selected_company_keys:
                        continue
                    if row["source"] == "web":
                        web_selection.append(row)
                    else:
                        linkedin_selection.append(row)
                    selected_company_keys.add(company_key)
                    if len(selected_company_keys) >= total_target:
                        break

            for row in web_ranked + linkedin_ranked:
                company_key = normalize_company_key(row["name"])
                if not company_key:
                    continue
                existing = selection_lookup.get(company_key, {})
                merged = dict(existing)
                merged["source"] = row.get("source") or merged.get("source", "")
                merged["name"] = row.get("name") or merged.get("name", "")
                merged["score"] = max(row.get("score", 0), merged.get("score", 0))
                merged["snippet"] = row.get("snippet") or merged.get("snippet", "")
                if row.get("website_url"):
                    merged["website_url"] = row["website_url"]
                else:
                    merged.setdefault("website_url", existing.get("website_url", ""))
                if row.get("linkedin_url"):
                    merged["linkedin_url"] = row["linkedin_url"]
                else:
                    merged.setdefault("linkedin_url", existing.get("linkedin_url", ""))
                selection_lookup[company_key] = merged

            if web_selection:
                findings_area.markdown("**Web Şirketleri**")
                for data in web_selection:
                    snippet = compact_snippet(data.get("snippet", ""), data.get("website_url", ""))
                    findings_area.markdown(f"🌐 **{data['name']}** | [Resmi Site]({data['website_url']})")
                    if snippet:
                        findings_area.caption(snippet)
                    st.session_state.seen_urls.add(data["website_url"])
                    found_set.add(data["name"])

            if linkedin_selection:
                findings_area.markdown("**LinkedIn Şirketleri**")
                for data in linkedin_selection:
                    snippet = compact_snippet(data.get("snippet", "") or data.get("title", ""), data.get("linkedin_url", ""))
                    findings_area.markdown(f"💼 **{data['name']}** | [LinkedIn]({data['linkedin_url']})")
                    if snippet:
                        findings_area.caption(snippet)
                    st.session_state.seen_urls.add(data["linkedin_url"])
                    found_set.add(data["name"])

            st.caption(f"Seçilen sonuçlar: Web={len(web_selection)}, LinkedIn={len(linkedin_selection)}, Toplam benzersiz={len(selected_company_keys)}")

            ordered_for_analysis = []
            seen_company_keys = set()
            for item in web_selection + linkedin_selection:
                company_key = normalize_company_key(item["name"])
                if not company_key or company_key in seen_company_keys:
                    continue
                seen_company_keys.add(company_key)
                ordered_for_analysis.append(item)

            selected_companies = [data["name"] for data in ordered_for_analysis]

        if not found_set:
            st.error("❌ Belirlenen kriterlerde uygun şirket bulunamadı.")
            st.stop()

        # --- YAPAY ZEKA ANALİZ & SATIŞ MESAJI FAZI ---
        st.divider()
        st.subheader("🧐 Karar Destek ve Kişiselleştirilmiş Satış Mesajları")
        analysis_area = st.container()
        
        m_str = "direct" if direct_mode else "gateway"
        g_pw = settings.get("GATEWAY_PASSWORD", "openclaw123")

        legacy_messages = [
            {"role": "system", "content": "Sen kıdemli bir satış analistisin. Şirketleri LOKASYON ve TÜR UYUMUNA göre denetle. 'summary' kısmına bu firmanın NE YAPTIĞINI anlatan tam olarak 2 CÜMLELİK bir özet yaz. 'sales_script' kısmına ise Dikkan Vana adına özgün bir teklif hazırla. Format: `{\"score\": 9, \"summary\": \"...\", \"sales_script\": \"...\"}`"},
            {"role": "user", "content": f"Ürün: {product}, Sektör: {sector}, Lokasyon: {selected_city}/{selected_country}\nAdaylarımız: {selected_companies}\nNOT: Her firma için 'Bu firma tam olarak ne iş yapıyor?' sorusuna 2 cümlelik net bir cevap ver."}
        ]

        # 5 ADAY ANALİZİ (İstek üzerine analiz sayısını artırdık)
        base_messages = [
            {"role": "system", "content": "Sen kıdemli bir satış analistisin. Şirketleri lokasyon ve ürün uyumuna göre denetle. Yalnızca JSON döndür. Format: {\"score\": 9, \"summary\": \"...\", \"sales_script\": \"...\"}. summary tam olarak iki cümle olsun. sales_script ise Dikkan adına kısa, profesyonel ve kişiselleştirilmiş bir satış mesajı olsun."},
            {"role": "user", "content": f"Ürün: {repair_text(product)}\nSektör: {repair_text(sector)}\nLokasyon: {repair_text(selected_city)}/{repair_text(selected_country)}\nAday firmalar: {[repair_text(name) for name in selected_companies]}\nHer firma için net ve ticari bir çıktı üret."},
        ]

        for comp in selected_companies[:5]:
            with analysis_area:
                with st.expander(f"📌 Analiz ve Teklif: {repair_text(comp)}", expanded=True):
                    # 1. Siteyi bul ve içeriği al
                    with st.status(f"🌐 {repair_text(comp)} araştırılıyor...", expanded=False) as s:
                        company_data = selection_lookup.get(normalize_company_key(comp), {})
                        # Eğer LinkedIn URL ise oradan okumaya çalışmaz, sadece metadata gösterir
                        # Ama biz genel olarak search_web_companies'den gelen URL'leri tercih ederiz
                        read_res = read_website_content(company_data.get("website_url", ""))
                        s.update(label=f"✅ {repair_text(comp)} incelendi", state="complete")
                    
                        # 2. AI'ya analiz ettir
                        with st.spinner("🤖 Strateji oluşturuluyor..."):
                            prompt = (
                                f"Firma: {repair_text(comp)}\n"
                                f"Website: {company_data.get('website_url', '')}\n"
                                f"LinkedIn: {company_data.get('linkedin_url', '')}\n"
                                f"Arama özeti: {repair_text(company_data.get('snippet', ''))}\n"
                                f"Site içeriği:\n{repair_text(read_res)[:2200]}"
                            )
                            analysis_messages = base_messages + [{"role": "user", "content": prompt}]
                            ai_ana, info = call_llm_raw(analysis_messages, mode=m_str, gateway_pw=g_pw, timeout=25)
                            
                            # 3. ANALİZ KARTINI BAS (REGEX İLE JSON TEMİZLEME)
                            # Varsayılan değerler (Hata durumunda)
                            fallback = build_analysis_fallback(
                                repair_text(comp),
                                company_data,
                                read_res,
                                product,
                                sector,
                                selected_city,
                                selected_country,
                            )
                            f_score = fallback["score"]
                            f_summary = company_data.get("snippet", "") or company_data.get("website_url") or company_data.get("linkedin_url") or "Firma bilgisi alınamadı."
                            f_script = "Yapay Zeka yanıt vermedi, lütfen tekrar deneyin veya bağlantıyı kontrol edin."

                            f_summary = fallback["summary"]
                            f_script = fallback["sales_script"]
                            source_note = f"Yerel taslak | {friendly_model_status(info)}"

                            try:
                                if ai_ana:
                                    match = re.search(r'\{.*\}', ai_ana, re.DOTALL)
                                    if match:
                                        ana_json = json.loads(match.group(0))
                                        f_score = max(1, min(int(ana_json.get("score", f_score)), 10))
                                        f_summary = repair_text(ana_json.get("summary", f_summary))
                                        f_script = repair_text(ana_json.get("sales_script", f_script))
                                        source_note = friendly_model_status(info)
                                    else:
                                        cleaned_ai = repair_text(ai_ana)
                                        if len(cleaned_ai) > 20:
                                            f_summary = cleaned_ai
                                        source_note = friendly_model_status(info)
                            except Exception:
                                pass

                            col1, col2 = st.columns([1, 4])
                            col1.metric("Uygunluk", f"{f_score}/10")
                            if len(f_summary) > 320:
                                f_summary = f_summary[:317].rstrip() + "..."
                            col2.markdown(f"**📄 Firma Özeti:** {repair_text(f_summary)}")

                            st.info(f"**✉️ Özel Satış Mesajı Taslağı:**\n\n{repair_text(f_script)}")
                            st.caption(f"🤖 Kaynak bilgisi: {repair_text(source_note)}")

                        # Rapor için veriyi sakla
                        st.session_state.current_results.append({
                            "Şirket": repair_text(comp),
                            "Skor": f_score,
                            "Özet": repair_text(f_summary),
                            "Satış Mesajı": repair_text(f_script),
                            "Kaynak": repair_text(source_note),
                            "Website": company_data.get("website_url", ""),
                            "LinkedIn": company_data.get("linkedin_url", ""),
                            "URL": company_data.get("website_url") or company_data.get("linkedin_url") or ""
                        })

        st.success("🏁 Satış analizi başarıyla tamamlandı. Raporunuz hazır!")

# ==========================================
# RAPOR DIŞA AKTARMA (REPORT EXPORT)
# ==========================================
if st.session_state.current_results:
    st.divider()
    st.subheader("💾 Analiz Raporunu İndir")
    col_dl1, col_dl2 = st.columns([1, 1])
    
    # DataFrame Hazırlama
    df = pd.DataFrame(st.session_state.current_results)
    
    # CSV indirme butonu
    csv = df.to_csv(index=False).encode('utf-8-sig')
    col_dl1.download_button(
        label="📥 CSV Olarak İndir (CRM İçin)",
        data=csv,
        file_name=f"dikkan_satis_raporu_{sector}_{int(time.time())}.csv",
        mime='text/csv',
        use_container_width=True
    )
    
    st.info("💡 Not: İndirdiğiniz dosyayı doğrudan Excel'e veya CRM sisteminize aktarabilirsiniz.")

st.sidebar.markdown("---")
st.sidebar.caption("OpenClaw Pilot - Sales Assistant Pro v2.5")
