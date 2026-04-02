import streamlit as st
import os
import json
import time
import requests
import re
import base64
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


def normalize_company_key(name):
    """Farkli kaynaklardaki firma adlarini tek anahtarda toplar."""
    raw = (name or "").split("-")[0].split("|")[0].strip().lower()
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
    return label.title()


def display_company_name(name, url=""):
    """Ekranda devasa basliklar yerine kisa ve okunur firma adi goster."""
    clean = re.sub(r"\s+", " ", (name or "")).strip(" |-")
    fallback = fallback_name_from_url(url)
    words = clean.split()
    if not clean:
        clean = fallback
        words = clean.split()

    low_words = [word.lower() for word in words]
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

    return clean


def compact_snippet(text, fallback_url=""):
    """Sonuc aciklamasini kisa ve okunur halde tut."""
    clean = re.sub(r"\s+", " ", (text or "")).strip()
    if not clean:
        return fallback_url
    if len(clean) <= 180:
        return clean
    return clean[:177].rstrip() + "..."


def load_logo_data_uri():
    """Logo dosyasini base64 data URI olarak hazirlar."""
    if not LOGO_PATH.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(LOGO_PATH.read_bytes()).decode()

settings = load_secure_settings()
LOGO_DATA_URI = load_logo_data_uri()

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

st.markdown("<h1 style='color: #1A202C;'>🤖 Dikkan AI Satış Asistanı | Pro</h1>", unsafe_allow_html=True)
st.markdown("<p style='color: #718096; font-size: 1.1rem;'>Yapay Zeka Destekli Şirket & Pazar Analisti</p>", unsafe_allow_html=True)
st.markdown("---")

# --- NASIL KULLANILIR? REHBERİ ---
with st.expander("📖 Hızlı Başlangıç & Kullanım Kılavuzu", expanded=False):
    st.markdown("""
    1. **Sektör & Ürün Girin:** Sol panelden hedeflediğiniz sektörü ve ürününüzü yazın.
    2. **Lokasyon Belirleyin:** Aramanın yapılacağı ülkeyi seçin (Varsayılan: Türkiye).
    3. **Analizi Başlat:** Sistem önce Bing ve LinkedIn üzerinden şirketleri bulur.
    4. **Yapay Zeka Skoru:** AI her şirketi inceler ve size özel satış mesajı hazırlar.
    5. **Raporu İndir:** Sonuçları sayfa sonundaki butonla **Excel/CSV** olarak indirebilirsiniz.
    """)

if not sector or not product:
    st.info("💡 Başlamak için sektör ve ürün bilgilerini girin.")
else:
    if st.sidebar.button("🚀 Kapsamlı Analizi Başlat", use_container_width=True, type="primary"):
        st.subheader(f"📊 {sector} Ürün/Sektör Analiz Raporu")
        
        found_set = set()
        selection_lookup = {}
        findings_area = st.container()
        log_area = st.empty()
        debug_area = st.expander("🛠️ Teknik Detaylar / Loglar")

        # --- SMART START: HİBRİT ARAMA (DİNAMİK & ÇEŞİTLİ) ---
        import random
        st.warning(f"⚡ **Smart Start: '{sector}' sektörü için farklı kaynaklar taranıyor...**")
        
        with st.status("🔍 Yeni Şirketler Keşfediliyor...", expanded=True) as status:
            linkedin_target = 5
            web_target = 5

            # 1. LinkedIn Aramasi
            l_data = search_linkedin_companies(
                product,
                sector,
                selected_city,
                li_at=session_token,
                limit=max(linkedin_target + 2, 4),
                country=selected_country,
            )
            num_l = len(l_data) if isinstance(l_data, list) else 0
            linkedin_status = os.getenv("OPENCLAW_LAST_LINKEDIN_STATUS", "unknown")
            
            # 2. Web Aramasi
            w_data = search_web_companies(product, sector, selected_city, selected_country, limit=max(web_target + 2, 6))
            
            status.update(label=f"✅ {num_l + len(w_data)} Potansiyel Şirket Keşfedildi", state="complete")
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

            linkedin_selection = sorted(
                linkedin_map.values(),
                key=lambda item: (-item.get("score", 0), item["name"].lower()),
            )[:linkedin_target]

            web_selection = sorted(
                web_map.values(),
                key=lambda item: (-item.get("score", 0), item["name"].lower()),
            )[:web_target]

            if web_selection:
                findings_area.markdown("**Web Sirketleri**")
                for data in web_selection:
                    snippet = compact_snippet(data.get("snippet", ""), data.get("website_url", ""))
                    findings_area.markdown(f"🌐 **{data['name']}** | [Firma Sitesi]({data['website_url']})")
                    if snippet:
                        findings_area.caption(snippet)
                    st.session_state.seen_urls.add(data["website_url"])
                    existing = selection_lookup.get(normalize_company_key(data["name"]))
                    if not existing or (data.get("website_url") and not existing.get("website_url")):
                        selection_lookup[normalize_company_key(data["name"])] = data
                    found_set.add(data["name"])

            if linkedin_selection:
                findings_area.markdown("**LinkedIn Sirketleri**")
                for data in linkedin_selection:
                    snippet = compact_snippet(data.get("snippet", "") or data.get("title", ""), data.get("linkedin_url", ""))
                    findings_area.markdown(f"💼 **{data['name']}** | [LinkedIn]({data['linkedin_url']})")
                    if snippet:
                        findings_area.caption(snippet)
                    st.session_state.seen_urls.add(data["linkedin_url"])
                    selection_lookup[normalize_company_key(data["name"])] = data
                    found_set.add(data["name"])

            st.caption(f"Secilen sonuclar: Web={len(web_selection)}, LinkedIn={len(linkedin_selection)}")

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
            st.error("❌ Belirlenen kriterlerde yeni şirket bulunamadı.")
            st.stop()

        # --- YAPAY ZEKA ANALİZ & SATIŞ MESAJI FAZI ---
        st.divider()
        st.subheader("🧐 Karar Destek & Kişiselleştirilmiş Satış Mesajları")
        analysis_area = st.container()
        
        m_str = "direct" if direct_mode else "gateway"
        g_pw = settings.get("GATEWAY_PASSWORD", "openclaw123")

        messages_history = [
            {"role": "system", "content": "Sen kıdemli bir satış analistisin. Şirketleri LOKASYON ve TÜR UYUMUNA göre denetle. 'summary' kısmına bu firmanın NE YAPTIĞINI anlatan tam olarak 2 CÜMLELİK bir özet yaz. 'sales_script' kısmına ise Dikkan Vana adına özgün bir teklif hazırla. Format: `{\"score\": 9, \"summary\": \"...\", \"sales_script\": \"...\"}`"},
            {"role": "user", "content": f"Ürün: {product}, Sektör: {sector}, Lokasyon: {selected_city}/{selected_country}\nAdaylarımız: {selected_companies}\nNOT: Her firma için 'Bu firma tam olarak ne iş yapıyor?' sorusuna 2 cümlelik net bir cevap ver."}
        ]

        # 5 ADAY ANALİZİ (İstek üzerine analiz sayısını artırdık)
        for i, comp in enumerate(selected_companies[:5]): 
            with analysis_area:
                with st.expander(f"📌 Analiz ve Teklif: {comp}", expanded=True):
                    # 1. Siteyi bul ve içeriği al
                    with st.status(f"🌐 {comp} araştırılıyor...", expanded=False) as s:
                        company_data = selection_lookup.get(normalize_company_key(comp), {})
                        # Eğer LinkedIn URL ise oradan okumaya çalışmaz, sadece metadata gösterir
                        # Ama biz genel olarak search_web_companies'den gelen URL'leri tercih ederiz
                        read_res = read_website_content(company_data.get("website_url", ""))
                        s.update(label=f"✅ {comp} incelendi", state="complete")
                    
                        # 2. AI'ya analiz ettir
                        with st.spinner("🤖 Strateji oluşturuluyor..."):
                            prompt = f"Şu veriye göre {comp} için satış teklifi hazırla:\n{read_res[:2500]}"
                            messages_history.append({"role": "user", "content": prompt})
                            ai_ana, info = call_llm_raw(messages_history, mode=m_str, gateway_pw=g_pw, timeout=60)
                            
                            # 3. ANALİZ KARTINI BAS (REGEX İLE JSON TEMİZLEME)
                            # Varsayılan değerler (Hata durumunda)
                            f_score = 5
                            f_summary = company_data.get("snippet", "") or company_data.get("website_url") or company_data.get("linkedin_url") or "Firma bilgisi alınamadı."
                            f_script = "Yapay Zeka yanıt vermedi, lütfen tekrar deneyin veya bağlantıyı kontrol edin."

                            try:
                                if ai_ana:
                                    match = re.search(r'\{.*\}', ai_ana, re.DOTALL)
                                    if match:
                                        ana_json = json.loads(match.group(0))
                                        f_score = ana_json.get("score", 5)
                                        f_summary = ana_json.get("summary", f_summary)
                                        f_script = ana_json.get("sales_script", f_script)
                                    else:
                                        f_summary = ai_ana if len(ai_ana) > 20 else f_summary
                            except:
                                pass

                            col1, col2 = st.columns([1, 4])
                            col1.metric("Uygunluk", f"{f_score}/10")
                            col2.markdown(f"**📄 Firma Özeti:** {f_summary}")
                            
                            st.info(f"**✉️ Özel Satış Mesajı Taslağı:**\n\n{f_script}")
                            st.caption(f"🤖 Kaynak Bilgisi: {info}")

                        # Rapor için veriyi sakla
                        st.session_state.current_results.append({
                            "Şirket": comp,
                            "Skor": f_score,
                            "Özet": f_summary,
                            "Satış Mesajı": f_script,
                            "Kaynak": info,
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
