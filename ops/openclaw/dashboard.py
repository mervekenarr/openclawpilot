import streamlit as st
import os
import json
import time
import requests
import re
from engine import search_web_companies, search_linkedin_companies, read_website_content

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

st.set_page_config(page_title="AI Şirket Analisti | Pro", page_icon="🤖", layout="wide")

# ==========================================
# LLM BRIDGE (ROBUST HTTP + SPEED TEST)
# ==========================================
def call_llm_raw(messages, mode="direct", gateway_pw="", timeout=20):
    """SDK kullanmadan, doğrudan HTTP üzerinden Yapay Zeka ile konuşur."""
    if mode == "direct":
        url = "http://127.0.0.1:11434/api/chat"
        payload = {
            "model": "qwen2.5:3b",
            "messages": messages,
            "stream": False,
            "options": {"num_ctx": 4096, "temperature": 0.1, "num_predict": 512}
        }
    else:
        url = "http://127.0.0.1:18789/v1/chat/completions"
        headers = {"Authorization": f"Bearer {gateway_pw}"}
        payload = {"model": "ollama/qwen2.5:3b", "messages": messages, "stream": False}

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
    sector = st.text_input("Hedef Sektör", placeholder="Örn: Insaat, Yazilim")
    product = st.text_input("Anahtar Kelime / Ürün", placeholder="Örn: Beton, CRM")
    
    st.markdown("---")
    st.subheader("📍 Lokasyon Filtresi")
    selected_country = st.text_input("Ülke", placeholder="Örn: Turkiye, Singapore, Germany", value="Turkiye")
    selected_city = st.text_input("Şehir", placeholder="Örn: Istanbul, Izmir, Berlin")
    
    st.markdown("---")
    st.subheader("🛠️ Geliştirici Ayarları")
    with st.expander("Sistem & Bağlantı Kontrolü", expanded=False):
        # AI Hız Testi
        if st.button("⚡ Yapay Zeka Hız Testi", use_container_width=True):
            with st.spinner("Test yapılıyor..."):
                ai_resp, speed = call_llm_raw([{"role": "user", "content": "Tamam de."}], timeout=10)
                if ai_resp: st.success(f"✅ Bağlantı İyi: {speed}")
                else: st.error(f"❌ Hata: {speed} (Yavaş/Kapalı)")
        
        # Bağlantı Testi
        if st.button("🔍 Port Kontrol Et", use_container_width=True):
            try:
                r = requests.get("http://127.0.0.1:11434/api/tags", timeout=2)
                st.success("✅ Ollama: Aktif") if r.status_code == 200 else st.error("❌ Ollama: Hata")
            except: st.error("❌ Ollama: Kapalı")
            
        st.write(f"LinkedIn Token: `***{session_token[-5:] if session_token else 'Yok'}`")
        direct_mode = st.toggle("🚀 Doğrudan Ollama Modu", value=True)

    if st.button("🗑️ Önbelleği Temizle", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

st.title("🤖 AI Satış Asistanı | Pro")
st.markdown("---")

# ==========================================
# RESEARCH ENGINE (PYTHON NATIVE)
# ==========================================
# Artık Node.js veya Skill klasörlerine gerek yok. 
# Tüm mantık engine.py içinde Python ile çalışıyor.

st.title("🤖 Yapay Zeka Şirket & Pazar Analisti")
st.markdown("---")

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
            # 1. LinkedIn Araması (En fazla 3-5 arası)
            l_data = search_linkedin_companies(product, sector, f"{selected_city} {selected_country}".strip(), session_token, limit=5)
            num_l = len(l_data) if isinstance(l_data, list) else 0
            
            # 2. Web Araması (Hedef 6 firmaya tamamlamak)
            target_total = 6
            w_limit = max(3, target_total - num_l)
            w_data = search_web_companies(product, sector, selected_city, selected_country, limit=w_limit + 5)
            
            status.update(label=f"✅ {num_l + len(w_data)} Potansiyel Şirket Keşfedildi", state="complete")
            
            # --- DATA INTEGRATION (ZORUNLU LİNKEDİN ÖNCELİĞİ) ---
            all_candidates = []
            if isinstance(l_data, list):
                for c in l_data:
                    # LİNKEDİN ŞİRKET FİLTRESİ (SIFIR TOLERANS)
                    url = c.get("linkedin_url", "")
                    is_garbage = any(x in url.lower() for x in ["/search/", "/people/", "/pub/", "/in/", "/jobs/", "/pulse/"])
                    if not is_garbage and "linkedin.com/company/" in url.lower():
                        all_candidates.append({"name": c.get("company_name"), "url": url, "is_li": True})
            
            for c in w_data:
                all_candidates.append({"name": c.get("company_name"), "url": c.get("website"), "is_li": c.get("is_linkedin", False)})

            # İSME GÖRE TEKİLLEŞTİR (Ama LİNKEDİN OLAN KAZANSIN!)
            final_map = {}
            for cand in all_candidates:
                name = cand["name"].split("-")[0].split("|")[0].strip()
                if not name or len(name) < 2: continue
                # Eğer kayıt yoksa ekle, VEYA kayıt web'se ve yeni gelen LinkedIn'se ÜZERİNE YAZ
                if name not in final_map or (not final_map[name]["is_li"] and cand["is_li"]):
                    final_map[name] = cand

            for name, data in final_map.items():
                if data["is_li"]:
                    findings_area.success(f"🟦 **[LİNKEDİN]** {name} [🔗 Profil Linki]({data['url']})")
                else:
                    findings_area.success(f"🌐 **[WEB]** {name} [🔗 Site Linki]({data['url']})")
                found_set.add(name)

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
            {"role": "system", "content": f"Sen kıdemli bir satış analistisin. Şirketleri LOKASYON ve TÜR UYUMUNA göre denetle. Eğer sayfa bir 'LinkedIn Arama Sonucu' veya 'Kişi Listesi' ise, 'score': 0 ver ve 'summary' kısmına 'Şirket Değil, Liste Sayfası' yaz. Sadece kurumsal organizasyon sayfalarını kabul et. Format: `{{\"score\": 9, \"summary\": \"...\", \"sales_script\": \"...\"}}`"},
            {"role": "user", "content": f"Ürün: {product}, Sektör: {sector}, Lokasyon: {selected_city}/{selected_country}\nAdaylarımız: {list(found_set)}\nNOT: Sadece doğrudan şirket profillerini analiz et."}
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
                    with st.spinner("🤖 Strateji oluşturuluyor..."):
                        prompt = f"Şu veriye göre {comp} için satış teklifi hazırla:\n{read_res[:2000]}"
                        messages_history.append({"role": "user", "content": prompt})
                        ai_ana, info = call_llm_raw(messages_history, mode=m_str, gateway_pw=g_pw, timeout=25)
                        
                        # 3. ANALİZ KARTINI BAS (REGEX İLE JSON TEMİZLEME)
                        try:
                            match = re.search(r'\{.*\}', ai_ana, re.DOTALL)
                            if match:
                                ana_json = json.loads(match.group(0))
                                f_score = ana_json.get("score", 5)
                                f_summary = ana_json.get("summary", "Özet mevcut değil.")
                                f_script = ana_json.get("sales_script", "Mesaj hazır değil.")
                            else:
                                f_score, f_summary, f_script = 5, ai_ana, "Mesaj hazır değil."
                        except:
                            f_score, f_summary, f_script = 5, ai_ana, "Hata oluştu."

                        col1, col2 = st.columns([1, 4])
                        col1.metric("Uygunluk", f"{f_score}/10")
                        col2.markdown(f"**📄 Firma Özeti:** {f_summary}")
                        
                        st.info(f"**✉️ Özel Satış Mesajı Taslağı:**\n\n{f_script}")
                        st.caption(f"🤖 Kaynak Bilgisi: {info}")

        st.success("🏁 Satış analizi başarıyla tamamlandı. Raporunuz hazır!")

st.sidebar.markdown("---")
st.sidebar.caption("OpenClaw Pilot - Sales Assistant Pro v2.5")
