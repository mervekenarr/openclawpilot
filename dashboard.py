import streamlit as st
import subprocess
import os
import json
import time
import concurrent.futures
import requests

# Ayar Dosyası Yolu
ENV_PATH = ".env"
SKILLS_DIR = os.path.abspath("skills")

# ==========================================
# GÜVENLİ AYAR YÖNETİMİ
# ==========================================
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
    st.header("🔍 Araştırma Parametreleri")
    sector = st.text_input("Hedef Sektör", placeholder="Örn: Insaat, Yazilim")
    product = st.text_input("Anahtar Kelime / Ürün", placeholder="Örn: Beton, CRM")
    
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
# SKILL EXECUTOR (UTF-8 & TAM YOL)
# ==========================================
def run_skill(skill_name, params):
    script_map = {
        "linkedin-company-search": "linkedin-company-search/scripts/linkedin_search.mjs",
        "company-search": "company-search/scripts/company_search.mjs",
        "company-website-read": "company-website-read/scripts/company_website_read.mjs"
    }
    script_path = os.path.join(SKILLS_DIR, script_map.get(skill_name, ""))
    cmd = ["node", script_path]
    for k, v in params.items(): cmd.extend([f"--{k}", str(v)])
    try:
        # UTF-8 Zorlaması (Karakter hatalarını çözer)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
        out, err = proc.communicate(timeout=60)
        return out if proc.returncode == 0 else json.dumps({"error": err})
    except Exception as e: return json.dumps({"error": str(e)})

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
        # Her aramada farklı sonuçlar gelmesi için sorgu varyasyonları
        suffixes = ["firmalar listesi", "en iyi şirketler", "yeni imalatçılar", "ana oyuncular", "sektörel rehber"]
        rand_query = f"{sector} {product} {random.choice(suffixes)} siteleri"
        
        st.warning(f"⚡ **Smart Start: '{sector}' sektörü için farklı kaynaklar taranıyor...**")
        
        with st.status("🔍 Yeni Şirketler Keşfediliyor...", expanded=True) as status:
            # Rastgeleleştirilmiş sorgu ile farklı sonuçlar alıyoruz
            initial_res = run_skill("company-search", {"query": rand_query})
            li_res = run_skill("linkedin-company-search", {"keyword": product, "sector": sector, "li_at": session_token})
            status.update(label="✅ Yeni Liste Hazırlandı", state="complete")
            
            def add_candidate(name, url=None, source="Web"):
                if not name or len(name) < 3: return
                name = name.split("-")[0].split("|")[0].strip()
                if name not in found_set:
                    found_set.add(name)
                    icon = "🌐 Web" if source == "Web" else "🔵 LinkedIn"
                    link_text = f" [🔗 Site]({url})" if url else ""
                    findings_area.success(f"📍 **{name}** ({icon}){link_text}")

            try:
                w_data = json.loads(initial_res)
                for c in w_data.get("candidates", []): add_candidate(c.get("company_name") or c.get("title"), c.get("url"), "Web")
                l_data = json.loads(li_res)
                for c in l_data.get("candidates", []): add_candidate(c.get("company_name"), c.get("linkedin_url"), "LinkedIn")
            except: pass

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
            {"role": "system", "content": "Sen kıdemli bir satış analistisin. Şirketleri 0-10 arası PUANLA, ÖZETLE ve KİŞİSELLEŞTİRİLMİŞ SATIŞ MESAJI yaz. Format: `{\"score\": 9, \"summary\": \"...\", \"sales_script\": \"...\"}`"},
            {"role": "user", "content": f"Ürün: {product}, Sektör: {sector}\nAdaylarımız: {list(found_set)}\nVakaları analiz et ve bana her biri için özel satış kancası (hook) oluştur."}
        ]

        # 5 ADAY ANALİZİ (İstek üzerine analiz sayısını artırdık)
        for i, comp in enumerate(list(found_set)[:5]): 
            with analysis_area:
                with st.expander(f"📌 Analiz ve Teklif: {comp}", expanded=True):
                    # 1. Siteyi bul ve içeriği al
                    with st.status(f"🌐 {comp} araştırılıyor...", expanded=False) as s:
                        read_res = run_skill("company-website-read", {"company": comp})
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
