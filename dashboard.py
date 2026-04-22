import streamlit as st
import os
import json
import time
import requests
import re
from engine import BLOCKED_HOST_TOKENS, openclaw_discover_companies, read_website_content
import pandas as pd
import io
from urllib.parse import urlsplit, urlunsplit

# Ayar Dosyası Yolu
ENV_PATH = ".env"

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
        "N8N_WEBHOOK_URL": os.getenv("N8N_WEBHOOK_URL", ""),
        "OLLAMA_BASE_URL": os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434"),
        "OLLAMA_MODEL": os.getenv("OLLAMA_MODEL", "qwen2.5:14b"),
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


def replace_url_host(url, new_host):
    parsed = urlsplit((url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return url

    auth = ""
    if parsed.username:
        auth = parsed.username
        if parsed.password:
            auth += f":{parsed.password}"
        auth += "@"

    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit((parsed.scheme, f"{auth}{new_host}{port}", parsed.path, parsed.query, parsed.fragment))


def build_n8n_webhook_candidates(webhook_url):
    raw_url = (webhook_url or "").strip()
    if not raw_url:
        return []

    candidates = [raw_url]
    host = (urlsplit(raw_url).hostname or "").lower()

    if host == "n8n":
        for alias in ["localhost", "127.0.0.1"]:
            candidate = replace_url_host(raw_url, alias)
            if candidate not in candidates:
                candidates.append(candidate)
    elif host in {"localhost", "127.0.0.1"}:
        candidate = replace_url_host(raw_url, "n8n")
        if candidate not in candidates:
            candidates.append(candidate)

    return candidates


def shorten_response_text(response, limit=220):
    text = (response.text or "").strip().replace("\r", " ").replace("\n", " ")
    return text[:limit] + ("..." if len(text) > limit else "")

settings = load_secure_settings()

# --- KEŞİF HAFIZASI & RAPORLAMA ---
if "seen_urls" not in st.session_state:
    st.session_state.seen_urls = set()
if "current_results" not in st.session_state:
    st.session_state.current_results = []

st.set_page_config(page_title="Dikkan Vana | AI Satış Asistanı", page_icon="🤖", layout="wide")

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
    
    /* Status Messages & Alerts Contrast Fix */
    .stAlert {
        border-radius: 10px !important;
        background-color: #EBF8FF !important; /* Soft Blue */
        border: 1px solid #BEE3F8 !important;
    }
    
    .stAlert p, .stAlert div {
        color: #2C5282 !important; /* Deep Blue for readability */
        font-weight: 500 !important;
    }

    /* Success Messages */
    div[data-testid="stNotification"] {
        background-color: #F0FFF4 !important;
        color: #276749 !important;
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
def call_llm_raw(messages, timeout=60):
    """Ollama'ya direkt HTTP isteği gönderir."""
    base_url = settings.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip("/")
    url = f"{base_url}/api/chat"
    payload = {
        "model": settings.get("OLLAMA_MODEL", "qwen2.5:14b"),
        "messages": messages,
        "stream": False,
        "options": {"num_ctx": 8192, "temperature": 0.3, "num_predict": 2500}
    }
    last_error = None
    for attempt in range(2):
        try:
            start_t = time.time()
            response = requests.post(url, json=payload, timeout=timeout)
            end_t = time.time()
            if response.status_code == 200:
                content = response.json().get("message", {}).get("content", "")
                if content and len(content.strip()) > 10:
                    info = f"{end_t-start_t:.1f}sn"
                    if attempt:
                        info += f" (retry {attempt})"
                    return content, info
                last_error = "Bos LLM cevabi"
            else:
                last_error = f"Hata: {response.status_code}"
        except Exception as e:
            last_error = str(e)
        time.sleep(1.2)
    return None, last_error or "LLM hatasi"


def has_meaningful_content(value):
    text = (value or "").strip()
    if not text:
        return False
    invalid_markers = {
        "hata",
        "analiz yapilamadi.",
        "analiz yapÄ±lamadÄ±.",
        "linkedin sayfasi okundu ama icerik cikarilamadi.",
        "linkedin sayfasÄ± okundu ama iÃ§erik Ã§Ä±karÄ±lamadÄ±.",
    }
    return text.lower() not in invalid_markers and len(text) > 40


def build_company_context(company_name, product, sector, city, country, company_item, session_token):
    website_url = company_item.get("website", "")
    linkedin_url = company_item.get("linkedin_url", "")
    snippet = (company_item.get("snippet") or "").strip()

    sources = []
    if website_url:
        sources.append(("website", website_url))
    if linkedin_url and linkedin_url != website_url:
        sources.append(("linkedin", linkedin_url))

    content_parts = []
    source_notes = []

    for source_type, url in sources:
        content = read_website_content(url, linkedin_token=session_token)
        if has_meaningful_content(content):
            label = "Web sitesi" if source_type == "website" else "LinkedIn"
            content_parts.append(f"{label} ({url}):\n{content[:2500]}")
            source_notes.append(label)

    if snippet:
        content_parts.append(f"Arama ozeti:\n{snippet[:500]}")
        source_notes.append("Arama ozeti")

    if not content_parts:
        fallback_context = [
            f"Firma adi: {company_name}",
            f"Urun/anahtar kelime: {product}",
            f"Sektor: {sector}",
            f"Lokasyon: {city}/{country}",
        ]
        if website_url:
            fallback_context.append(f"Website: {website_url}")
        if linkedin_url:
            fallback_context.append(f"LinkedIn: {linkedin_url}")
        if snippet:
            fallback_context.append(f"Ozet: {snippet[:300]}")
        return "\n".join(fallback_context), "Kaynak bulunamadi"

    return "\n\n".join(content_parts), " + ".join(source_notes)


def parse_analysis_response(raw_text):
    default_analysis = "Analiz yapilamadi."
    default_script = "Mesaj hazirlanamadi."
    score = 5
    analysis = default_analysis
    script = default_script

    try:
        if raw_text:
            match = re.search(r'\{.*\}', raw_text, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                score = int(parsed.get("score", 5))
                analysis = (parsed.get("analysis") or analysis).strip()
                script = (parsed.get("sales_script") or script).strip()
            elif len(raw_text.strip()) > 20:
                analysis = raw_text.strip()
    except Exception:
        pass

    score = max(1, min(score, 10))
    return score, analysis, script


def generate_fallback_sales_script(company_name, product, sector, city, country):
    return (
        f"Merhaba, {company_name} icin hazirladigimiz cozumlerin "
        f"{sector} alanindaki operasyonlara ve {product} ihtiyaclarina destek olabilecegini dusunuyoruz. "
        f"{city or country} tarafindaki hedefleriniz uygunsa kisa bir gorusmede tanismak isteriz."
    )


def analyze_company(company_name, product, sector, city, country, company_context, website_url="", linkedin_url=""):
    system_prompt = {
        "role": "system",
        "content": (
            "Sen kıdemli bir B2B iş geliştirme analistisin. "
            "Verilen firma bilgileri ve web içeriğine dayanarak aşağıdaki JSON formatında yanıt üret. "
            "JSON dışında hiçbir şey yazma.\n\n"
            "Format:\n"
            "{\n"
            '  "score": <1-10 tam sayı>,\n'
            '  "location_match": <true/false — firma hedef şehirde mi?>,\n'
            '  "company_type": "<üretici/distribütör/hizmet/perakende/diğer>",\n'
            '  "key_activities": "<firmanın ana faaliyet alanları, 1-2 cümle>",\n'
            '  "pain_points": "<bu firmanın muhtemelen ihtiyaç duyduğu şeyler, 1-2 cümle>",\n'
            '  "analysis": "<kapsamlı faaliyet raporu — şehir uyumu, sektör uyumu, ürün uyumu değerlendir, en az 4 cümle>",\n'
            '  "sales_script": "<LinkedIn mesajı — kişisel, samimi, 3-4 cümle, emoji yok, satışçı havası yok>"\n'
            "}\n\n"
            "SKORLAMA KRİTERLERİ:\n"
            "10: Hedef şehirde, hedef sektörde, ürüne açık bir ihtiyacı var\n"
            "7-9: Şehir/sektör uyumu var ama ürün bağlantısı dolaylı\n"
            "4-6: Kısmi uyum, belirsizlik var\n"
            "2-3: Yanlış şehir VEYA yanlış sektör\n"
            "1: Hem şehir hem sektör uyumsuz\n\n"
            "Sales script için: Firma adını, sektörünü ve ürünü bağdaştır. "
            "'Değerli yönetici' gibi genel ifadeler kullanma. Direkt ve özlü ol."
        ),
    }

    url_context = ""
    if website_url:
        url_context += f"Website: {website_url}\n"
    if linkedin_url:
        url_context += f"LinkedIn: {linkedin_url}\n"

    user_prompt = (
        f"Firma adı: {company_name}\n"
        f"{url_context}"
        "Kritik kural: Kaynaklarda hedef urun/hizmet acikca gecmiyorsa score en fazla 3 olmali.\n"
        f"Hedef ürün/hizmet: {product}\n"
        f"Hedef sektör: {sector}\n"
        f"Hedef şehir: {city}, {country}\n\n"
        f"Kaynak içeriği:\n{company_context[:3000]}"
    )

    for extra in ["", "\n\nJSON dışında hiçbir şey yazma. Tüm alanları doldur."]:
        raw, info = call_llm_raw(
            [system_prompt, {"role": "user", "content": user_prompt + extra}],
            timeout=90,
        )
        score, analysis, script = parse_analysis_response(raw)
        if has_meaningful_content(analysis) and has_meaningful_content(script):
            # Extract extra fields if present
            try:
                match = re.search(r'\{.*\}', raw, re.DOTALL)
                if match:
                    parsed = json.loads(match.group(0))
                    location_match = parsed.get("location_match", True)
                    if not location_match:
                        score = min(score, 3)
            except Exception:
                pass
            return score, analysis, script, info

    fallback_analysis = (
        f"{company_name} için otomatik derin analiz tamamlanamadı, ancak bulunan kaynaklar "
        f"firmanın {sector} alanında {product} ile ilişkili faaliyet gösterdiğine işaret ediyor. "
        "Kesin faaliyet kapsamı için firma sayfası veya LinkedIn profili manuel olarak gözden geçirilmelidir."
    )
    fallback_script = generate_fallback_sales_script(company_name, product, sector, city, country)
    return 5, fallback_analysis, fallback_script, "LLM fallback"

def send_to_n8n(data):
    """Bulunan adayları n8n webhook'una gönderir."""
    webhook_url = settings.get("N8N_WEBHOOK_URL")
    if not webhook_url:
        return False, "N8N_WEBHOOK_URL ayarlanmamış."
    
    try:
        response = requests.post(webhook_url, json=data, timeout=10)
        if response.status_code in [200, 201]:
            return True, "Başarıyla gönderildi."
        return False, f"Hata: {response.status_code}"
    except Exception as e:
        return False, str(e)

# --- GÜVENLİ OTURUM (ARKA PLAN) ---
# Token artık kullanıcıdan istenmiyor, doğrudan arka plandan okunuyor.
def send_to_n8n_with_fallback(data):
    webhook_url = settings.get("N8N_WEBHOOK_URL")
    if not webhook_url:
        return False, "N8N_WEBHOOK_URL ayarlanmamis."

    candidate_urls = build_n8n_webhook_candidates(webhook_url)
    connection_errors = []

    for candidate_url in candidate_urls:
        try:
            response = requests.post(candidate_url, json=data, timeout=12)
        except requests.RequestException as exc:
            connection_errors.append(f"{candidate_url} -> {exc}")
            continue

        if response.status_code in [200, 201, 202]:
            if candidate_url != webhook_url:
                settings["N8N_WEBHOOK_URL"] = candidate_url
                save_secure_setting("N8N_WEBHOOK_URL", candidate_url)
            return True, f"Basariyla gonderildi ({candidate_url})."

        response_hint = shorten_response_text(response)
        if response.status_code == 404:
            return (
                False,
                f"Webhook bulunamadi ({candidate_url}). Workflow aktif mi ve webhook path dogru mu? "
                f"HTTP 404 {response_hint}",
            )
        return False, f"n8n yanit verdi ama istegi kabul etmedi ({candidate_url}). HTTP {response.status_code} {response_hint}"

    tried_urls = ", ".join(candidate_urls)
    last_error = connection_errors[-1] if connection_errors else "Bilinmeyen baglanti hatasi"
    return False, f"n8n'e ulasilamadi. Denenen adresler: {tried_urls}. Son hata: {last_error}"


send_to_n8n = send_to_n8n_with_fallback

session_token = settings.get("LINKEDIN_SESSION_TOKEN", "")

# --- SİDEBAR DÜZENİ ---
with st.sidebar:
    # LOGO YERLEŞİMİ (Tam Kontrol İçin HTML Kullanımı - Büyütme Butonunu Devre Dışı Bırakır)
    if os.path.exists("assets/logo.png"):
        import base64
        with open("assets/logo.png", "rb") as f:
            data = f.read()
            b64_logo = base64.b64encode(data).decode()
        
        st.markdown(
            f"""
            <div style="display: flex; justify-content: center; margin-bottom: 20px;">
                <img src="data:image/png;base64,{b64_logo}" width="220" style="object-fit: contain;">
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

    if st.button("🗑️ Önbelleği Temizle", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    if st.button("🔄 Keşif Hafızasını Sıfırla", use_container_width=True):
        st.session_state.seen_urls = set()
        st.success("Hafıza sıfırlandı!")
        time.sleep(1)
        st.rerun()

st.markdown("<h1 style='color: #1A202C;'>🤖 Dikkan AI Satış Asistanı | Pro</h1>", unsafe_allow_html=True)
st.markdown("<p style='color: #718096; font-size: 1.1rem;'>Yapay Zeka Destekli Şirket & Pazar Analisti</p>", unsafe_allow_html=True)
st.markdown("---")

# --- NASIL KULLANILIR? REHBERİ ---
with st.expander("📖 Hızlı Başlangıç & Kullanım Kılavuzu", expanded=False):
    st.markdown("""
    1. **Sektör & Ürün Girin:** Sol panelden hedeflediğiniz sektörü ve ürününüzü yazın.
    2. **Lokasyon Belirleyin:** Aramanın yapılacağı ülkeyi seçin (Varsayılan: Türkiye).
    3. **Analizi Başlat:** Sistem önce Bing ve LinkedIn üzerinden şirketleri bulur.
    4. **Yapay Zeka Skoru:** AI her şirketi inceler ve profesyonel bir faaliyet raporu hazırlar.
    5. **Raporu İndir:** Sonuçları sayfa sonundaki butonla **Excel/CSV** olarak indirebilirsiniz.
    """)

if not sector or not product:
    st.info("💡 Başlamak için sektör ve ürün bilgilerini girin.")
else:
    if st.sidebar.button("🚀 Kapsamlı Analizi Başlat", use_container_width=True, type="primary"):
        findings_area = st.empty()
        found_set = []  # set yerine list: sıra korunur, URL eşleşmesi bozulmaz

        # --- SMART START: OPENCLAW AGENTIC DISCOVERY ---
        st.warning(f"⚡ **OpenClaw Ajanı Görevlendirildi: '{sector}' sektörü için derin araştırma yapılıyor...**")

        with st.status("🔍 OpenClaw Ajanı Şirketleri Keşfediyor...", expanded=True) as status:
            # 1. OpenClaw Agent Discovery
            discovered_data = openclaw_discover_companies(product, sector, selected_city, selected_country, limit=10)

            status.update(label=f"✅ {len(discovered_data)} Nitelikli Şirket Bulundu", state="complete")

            # Yeni bir arama başladığında eski sonuçları temizle
            st.session_state.current_results = []

            # --- DATA INTEGRATION & MEMORY FILTER ---
            for item in discovered_data:
                memory_key = item.get("linkedin_url") or item.get("website", "")
                if memory_key in st.session_state.seen_urls:
                    continue
                name = item.get("company_name", "Bilinmeyen")
                found_set.append(name)
                st.session_state.seen_urls.add(memory_key)

        # Keşif listesini link_button ile göster
        findings_area.empty()
        st.subheader("Bulunan Firmalar")
        for item in discovered_data:
            website_url = item.get("website", "")
            linkedin_url = item.get("linkedin_url", "")
            url = linkedin_url or website_url
            name = item.get("company_name", "Bilinmeyen")
            is_li = item.get("is_linkedin", False)
            is_openclaw = item.get("is_openclaw", False)
            label = "🟦 LinkedIn" if is_li else "🌐 Web"
            if is_openclaw:
                label = "OpenClaw + LinkedIn" if linkedin_url else "OpenClaw + Web"
            if not is_openclaw and not is_li and linkedin_url:
                label = "Web + LinkedIn"
            col_a, col_b = st.columns([3, 1])
            col_a.markdown(f"**{name}** — {label}")
            col_b.markdown(f'<a href="{url}" target="_blank" style="display:block;text-align:center;background:#EC6602;color:white;padding:6px 12px;border-radius:8px;text-decoration:none;font-weight:600;">Aç</a>', unsafe_allow_html=True)

        if not found_set:
            st.error("❌ OpenClaw belirlenen kriterlerde yeni şirket bulamadı.")
            st.stop()

        # --- YAPAY ZEKA ANALİZ FAZI ---
        st.divider()
        st.subheader("🧐 Detaylı Firma Analiz Raporları")
        analysis_area = st.container()


        # 5 ADAY ANALİZİ — her firma için bağımsız LLM çağrısı
        for i, comp in enumerate(found_set[:5]):
            with analysis_area:
                with st.expander(f"📌 Analiz ve Teklif: {comp}", expanded=True):
                    # 1. Siteyi bul ve içeriği al
                    company_item = next((item for item in discovered_data if item["company_name"] == comp), {})
                    company_url = company_item.get("website", "")
                    linkedin_url = company_item.get("linkedin_url", "")
                    lead_url = linkedin_url or company_url
                    with st.status(f"🌐 {comp} araştırılıyor...", expanded=False) as s:
                        company_context, source_info = build_company_context(
                            comp,
                            product,
                            sector,
                            selected_city,
                            selected_country,
                            company_item,
                            session_token,
                        )
                        s.update(label=f"✅ {comp} incelendi", state="complete")

                    # 2. AI'ya analiz ettir
                    with st.spinner("🤖 Derin analiz yapılıyor..."):
                        f_score, f_analysis, f_script, info = analyze_company(
                            comp,
                            product,
                            sector,
                            selected_city,
                            selected_country,
                            company_context,
                            website_url=company_url,
                            linkedin_url=linkedin_url,
                        )

                        col1, col2, col3 = st.columns([1, 4, 1])
                        col1.metric("Uygunluk", f"{f_score}/10")
                        col2.markdown(f"**🔍 Profesyonel Faaliyet Raporu:**\n\n{f_analysis}")
                        if lead_url:
                            button_label = "LinkedIn'e Git" if linkedin_url else "Siteye Git"
                            col3.markdown(f'<a href="{lead_url}" target="_blank" style="display:block;text-align:center;background:#EC6602;color:white;padding:6px 12px;border-radius:8px;text-decoration:none;font-weight:600;">{button_label}</a>', unsafe_allow_html=True)
                        with st.expander("✉️ Hazırlanan Satış Mesajı"):
                            st.write(f_script)
                        st.caption(f"🤖 Kaynak Bilgisi & Hız: {info}")

                        # Rapor için veriyi sakla
                        st.session_state.current_results.append({
                            "Şirket": comp,
                            "Sirket": comp,
                            "company_name": comp,
                            "Skor": f_score,
                            "score": f_score,
                            "Detaylı Analiz": f_analysis,
                            "analysis": f_analysis,
                            "Sales Script": f_script,
                            "sales_script": f_script,
                            "message": f_script,
                            "Kaynak": info,
                            "kaynak": info,
                            "Website": company_url,
                            "website": company_url,
                            "LinkedIn URL": linkedin_url,
                            "linkedin_url": linkedin_url,
                            "URL": lead_url
                        })

        st.success("🏁 Şirket analizleri başarıyla tamamlandı. Raporunuz hazır!")

# ==========================================
# RAPOR DIŞA AKTARMA (REPORT EXPORT)
# ==========================================
st.divider()
st.subheader("💾 Analiz Raporunu İndir")

if st.session_state.current_results:
    # DataFrame Hazırlama
    df = pd.DataFrame(st.session_state.current_results)
    
    col_dl1, col_dl2 = st.columns(2)
    
    # CSV indirme butonu
    csv_data = df.to_csv(index=False).encode('utf-8-sig')
    col_dl1.download_button(
        label="📥 CSV Olarak İndir (Sade)",
        data=csv_data,
        file_name=f"dikkan_raporu_{int(time.time())}.csv",
        mime='text/csv',
        use_container_width=True
    )
    
    # Excel indirme butonu
    try:
        import io
        buffer = io.BytesIO()
        # xlsxwriter motorunu kullanarak profesyonel formatlama yapıyoruz
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='AnalizSonuclari')
            
            workbook  = writer.book
            worksheet = writer.sheets['AnalizSonuclari']
            
            # Formatlar
            header_format = workbook.add_format({
                'bold': True,
                'text_wrap': True,
                'valign': 'vcenter',
                'fg_color': '#EC6602', # Dikkan Turuncusu
                'font_color': '#FFFFFF',
                'border': 1
            })
            
            body_format = workbook.add_format({
                'text_wrap': True,
                'valign': 'top',
                'border': 1
            })

            # Başlıkları formatla
            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, header_format)
            
            # Sütun genişliklerini ayarla ve kaydırma (wrap) ekle
            worksheet.set_column('A:A', 25, body_format) # Şirket
            worksheet.set_column('B:B', 10, body_format) # Skor
            worksheet.set_column('C:C', 85, body_format) # Detaylı Analiz (Genişletildi)
            worksheet.set_column('D:D', 55, body_format) # Sales Script
            worksheet.set_column('E:E', 15, body_format) # Kaynak
            worksheet.set_column('F:F', 40, body_format) # Website
            worksheet.set_column('G:G', 40, body_format) # LinkedIn URL
            worksheet.set_column('H:H', 40, body_format) # URL
            
            # Satır yüksekliğini otomatik ayarla (Metin kaydırma için)
            worksheet.set_default_row(60)
        
        col_dl2.download_button(
            label="📊 Excel Olarak İndir (Profesyonel)",
            data=buffer.getvalue(),
            file_name=f"dikkan_analiz_raporu_{int(time.time())}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    except Exception as e:
        col_dl2.error(f"Excel Hatası: {str(e)}")
    
    st.info("💡 Not: İndirdiğiniz dosyayı doğrudan CRM sisteminize aktarabilirsiniz.")
    
    st.divider()
    st.subheader("🚀 Otonom Satış Kampanyası (Faz 3)")
    if st.button("🤖 Adayları n8n'e Gönder ve Kampanyayı Başlat", use_container_width=True, type="primary"):
        with st.spinner("📦 Veriler paketleniyor ve n8n'e gönderiliyor..."):
            success, msg = send_to_n8n(st.session_state.current_results)
            if success:
                st.success(f"✅ Başarılı! {len(st.session_state.current_results)} aday n8n otonom akışına eklendi.")
            else:
                st.error(f"❌ Gönderim Hatası: {msg}")
else:
    st.info("ℹ️ Rapor hazırlamak için en az bir analiz tamamlanmış olmalıdır.")

st.sidebar.markdown("---")
st.sidebar.caption("OpenClaw Pilot - Sales Assistant Pro v2.5")
