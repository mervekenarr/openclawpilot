import streamlit as st
import os
import json
import time
import requests
import re
from engine import search_web_companies, search_linkedin_companies, read_website_content
import pandas as pd
import io

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
def call_llm_raw(messages, mode="direct", gateway_pw="", timeout=20):
    """SDK kullanmadan, doğrudan HTTP üzerinden Yapay Zeka ile konuşur."""
    if mode == "direct":
        base_url = settings.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        url = f"{base_url}/api/chat"
        payload = {
            "model": settings.get("OLLAMA_MODEL", "qwen2.5:14b"),
            "messages": messages,
            "stream": False,
            "options": {"num_ctx": 4096, "temperature": 0.2, "num_predict": 1500}
        }
    else:
        url = "http://127.0.0.1:18789/v1/chat/completions"
        headers = {"Authorization": f"Bearer {gateway_pw}"}
        payload = {"model": f"ollama/{settings.get('OLLAMA_MODEL', 'qwen2.5:14b')}", "messages": messages, "stream": False, "temperature": 0.2, "max_tokens": 1500}

    try:
        start_t = time.time()
        response = requests.post(url, json=payload, timeout=timeout)
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
    4. **Yapay Zeka Skoru:** AI her şirketi inceler ve profesyonel bir faaliyet raporu hazırlar.
    5. **Raporu İndir:** Sonuçları sayfa sonundaki butonla **Excel/CSV** olarak indirebilirsiniz.
    """)

if not sector or not product:
    st.info("💡 Başlamak için sektör ve ürün bilgilerini girin.")
else:
    if st.sidebar.button("🚀 Kapsamlı Analizi Başlat", use_container_width=True, type="primary"):
        st.subheader(f"📊 {sector} Ürün/Sektör Analiz Raporu")
        
        found_set = set()
        findings_area = st.container()
        log_area = st.empty()
        debug_area = st.expander("🛠️ Teknik Detaylar / Loglar")

        # --- SMART START: HİBRİT ARAMA (DİNAMİK & ÇEŞİTLİ) ---
        import random
        st.warning(f"⚡ **Smart Start: '{sector}' sektörü için farklı kaynaklar taranıyor...**")
        
        with st.status("🔍 Yeni Şirketler Keşfediliyor...", expanded=True) as status:
            li_queries = [
                f"site:linkedin.com/company/ \"{product}\" {sector} {selected_city} {selected_country}",
                f"intitle:company site:linkedin.com/company/ \"{product}\" {selected_city}"
            ]
            # 1. LinkedIn Araması (Daha fazla sonuç çekip yeni olanları ayıklayacağız)
            l_data = search_linkedin_companies(product, sector, f"{selected_city} {selected_country}".strip(), session_token, limit=15)
            num_l = len(l_data) if isinstance(l_data, list) else 0
            
            # 2. Web Araması
            target_total = 6
            w_limit = max(10, target_total - num_l)
            w_data = search_web_companies(product, sector, selected_city, selected_country, limit=20)
            
            status.update(label=f"✅ {num_l + len(w_data)} Potansiyel Şirket Keşfedildi", state="complete")
            
            # Yeni bir arama başladığında eski sonuçları temizle
            st.session_state.current_results = []
            
            # --- DATA INTEGRATION & MEMORY FILTER (GÖRÜLMEMİŞLERİ SEÇ) ---
            all_candidates = []
            if isinstance(l_data, list):
                for c in l_data:
                    url = c.get("linkedin_url", "")
                    if url in st.session_state.seen_urls: continue # Hafızada varsa atla
                    
                    is_garbage = any(x in url.lower() for x in ["/search/", "/people/", "/pub/", "/in/", "/jobs/", "/pulse/", "/posts/"])
                    if not is_garbage and "linkedin.com/company/" in url.lower():
                        all_candidates.append({"name": c.get("company_name"), "url": url, "is_li": True})
            
            for c in w_data:
                url = c.get("website", "")
                if url in st.session_state.seen_urls: continue # Hafızada varsa atla
                all_candidates.append({"name": c.get("company_name"), "url": url, "is_li": c.get("is_linkedin", False)})

            # İSME GÖRE TEKİLLEŞTİR (Ama LİNKEDİN OLAN KAZANSIN!)
            final_map = {}
            for cand in all_candidates:
                name = cand["name"].split("-")[0].split("|")[0].strip()
                if not name or len(name) < 2: continue
                if name not in final_map or (not final_map[name]["is_li"] and cand["is_li"]):
                    final_map[name] = cand

            # Yeni bulunanları hafızaya ekle (Max 6 tanesini gösterip hafızaya alacağız)
            new_selection = list(final_map.values())[:6]
            for item in new_selection:
                st.session_state.seen_urls.add(item["url"])

            for data in new_selection:
                name = data["name"]
                icon = "🟦" if data["is_li"] else "🌐"
                label = "LINKEDIN" if data["is_li"] else "WEB"
                findings_area.markdown(f"{icon} **[{label}]** {name} | [Bağlantıya Git 🔗]({data['url']})")
                found_set.add(name)

        if not found_set:
            st.error("❌ Belirlenen kriterlerde yeni şirket bulunamadı.")
            st.stop()

        # --- YAPAY ZEKA ANALİZ FAZI ---
        st.divider()
        st.subheader("🧐 Detaylı Firma Analiz Raporları")
        analysis_area = st.container()
        
        m_str = "direct" if direct_mode else "gateway"
        g_pw = settings.get("GATEWAY_PASSWORD", "openclaw123")

        messages_history = [
            {"role": "system", "content": "Sen kıdemli bir iş analistisin. Şirketleri LOKASYON ve TÜR UYUMUNA göre denetle. 'analysis' kısmına bu firmanın tam olarak NE YAPTIĞINI, hangi ürünleri ürettiğini ve uzmanlık alanlarını anlatan, profesyonel ve MADDELER HALİNDE (bullet points) detaylı bir rapor yaz. Outreach/Satış mesajı hazırlama, sadece objektif analiz yap. Format: `{\"score\": 9, \"analysis\": \"...\"}`"},
            {"role": "user", "content": f"Ürün: {product}, Sektör: {sector}, Lokasyon: {selected_city}/{selected_country}\nAdaylarımız: {list(found_set)}\nNOT: Her firma için 'Bu firma tam olarak ne iş yapıyor, pazar payı ve ürünleri nedir?' sorularına maddelerle cevap ver."}
        ]

        # 5 ADAY ANALİZİ (İstek üzerine analiz sayısını artırdık)
        for i, comp in enumerate(list(found_set)[:5]): 
            with analysis_area:
                with st.expander(f"📌 Analiz ve Teklif: {comp}", expanded=True):
                    # 1. Siteyi bul ve içeriği al
                    with st.status(f"🌐 {comp} araştırılıyor...", expanded=False) as s:
                        # Eğer LinkedIn URL ise oradan okumaya çalışmaz, sadece metadata gösterir
                        # Ama biz genel olarak search_web_companies'den gelen URL'leri tercih ederiz
                        read_res = read_website_content(next((c.get("website") for c in w_data if c.get("company_name") == comp), ""))
                        s.update(label=f"✅ {comp} incelendi", state="complete")
                    
                    # 2. AI'ya analiz ettir
                    with st.spinner("🤖 Derin analiz yapılıyor..."):
                        prompt = f"Şu veriye göre {comp} için detaylı faaliyet raporu hazırla:\n{read_res[:2500]}"
                        messages_history.append({"role": "user", "content": prompt})
                        ai_ana, info = call_llm_raw(messages_history, mode=m_str, gateway_pw=g_pw, timeout=60)
                        
                        # 3. ANALİZ KARTINI BAS (JSON TEMİZLEME)
                        # Varsayılan değerler (Hata durumunda)
                        f_score = 5
                        f_analysis = next((c.get("snippet", "Detaylı analiz yapılamadı.") for c in w_data if c.get("company_name") == comp), "Firma bilgisi alınamadı.")

                        try:
                            if ai_ana:
                                match = re.search(r'\{.*\}', ai_ana, re.DOTALL)
                                if match:
                                    ana_json = json.loads(match.group(0))
                                    f_score = ana_json.get("score", 5)
                                    f_analysis = ana_json.get("analysis", f_analysis)
                                else:
                                    f_analysis = ai_ana if len(ai_ana) > 20 else f_analysis
                        except:
                            pass

                        col1, col2 = st.columns([1, 4])
                        col1.metric("Uygunluk", f"{f_score}/10")
                        col2.markdown(f"**🔍 Profesyonel Faaliyet Raporu:**\n\n{f_analysis}")
                        st.caption(f"🤖 Kaynak Bilgisi & Hız: {info}")

                        # Rapor için veriyi sakla
                        st.session_state.current_results.append({
                            "Şirket": comp,
                            "Skor": f_score,
                            "Detaylı Analiz": f_analysis,
                            "Kaynak": info,
                            "URL": next((data["url"] for name, data in final_map.items() if name == comp), "")
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
            worksheet.set_column('D:D', 15, body_format) # Kaynak
            worksheet.set_column('E:E', 40, body_format) # URL
            
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
else:
    st.info("ℹ️ Rapor hazırlamak için en az bir analiz tamamlanmış olmalıdır.")

st.sidebar.markdown("---")
st.sidebar.caption("OpenClaw Pilot - Sales Assistant Pro v2.5")
