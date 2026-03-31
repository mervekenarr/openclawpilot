# 🤖 AI Satış Asistanı & Şirket Analisti (Pro v2.5)

Bu proje, satış ekiplerinin pazar araştırması, rakip analizi ve aday müşteri (prospekt) bulma süreçlerini tamamen otomatize eden, Python tabanlı profesyonel bir yapay zeka aracıdır.

---

## 🔥 Temel Özellikler

- **⚡ Smart Start (Hibrit Keşif)**: Bing, DuckDuckGo ve LinkedIn ağını aynı anda tarayarak en güncel şirket listelerini saniyeler içinde oluşturur.
- **🧐 AI Karar Destek (0-10 Uygunluk Skoru)**: Yapay zeka, bulunan her şirketin web sitesine girer, içeriği okur ve belirlediğiniz ürün/sektörle ne kadar uyumlu olduğunu puanlar.
- **📄 Akıllı Şirket Özeti**: Her aday firmanın ne iş yaptığını ve hangi sektörlere odaklandığını tek cümlede raporlar.
- **✉️ Kişiselleştirilmiş Satış Mesajları**: AI, her firma için o firmaya özel, "kanca" cümleler (Hook) barındıran satış teklifi taslakları hazırlar.
- **🛡️ Güvenli & Yerel Veri**: Tüm analizler yerel ağınızda (Ollama) gerçekleşir; verileriniz dışarı sızmaz.

## 🚀 Hızlı Başlangıç

### 1. Gereksinimler
- **Python 3.10+**
- **Ollama** (LLM Sunucusu - `qwen2.5:3b` modeli yüklü olmalıdır)
- **LinkedIn li_at Token** (LinkedIn aramaları için opsiyoneldir, `.env` dosyasına eklenir)

### 2. Kurulum
Bağımlılıkları yüklemek için terminalden şu komutu çalıştırın:
```bash
pip install -r requirements.txt
playwright install chromium
```
*(Ya da manuel olarak: `streamlit run ops/openclaw/dashboard.py`)*

### 3. Çalıştırma
Proje kök dizinindeki başlatıcıyı kullanabilirsiniz:
```text
AnaliziBaslat.bat
```
*(Ya da manuel olarak: `streamlit run ops/openclaw/dashboard.py`)*

## 🏗️ Proje Yapısı

- **`dashboard.py`**: Modern ve kullanıcı dostu Streamlit arayüzü.
- **`engine.py`**: Arama, web kazıma ve puanlama yapan ana Python motoru.
- **`setup_openclaw.py`**: İlk kurulum ve yapılandırma sihirbazı.
- **`AnaliziBaslat.bat`**: Kullanıcı dostu tek tıkla başlatma dosyası.

---

## 🛠️ Teknik Detaylar
- **UI**: Streamlit
- **Search Engine**: Playwright (Geçici Tarayıcı Otomasyonu) + HTTP Scrapers
- **AI Model**: Ollama / Qwen 2.5 (3B / 7B / 14B destekler)
- **Veri Okuma**: Trafilatura (Hızlı ve Temiz Metin Ekstraksiyonu)

---
*OpenClaw Pilot Proje - Geleceğin Satış Otomasyonu Çözümleri*
