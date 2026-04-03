# AI Satis Asistani & Sirket Analisti

Bu proje, satis ekiplerinin sirket kesfi, on eleme ve kisisellestirilmis teklif hazirlama akislarini yerelde calistiran bir Streamlit uygulamasidir.

Kodun tek kanonik kopyasi `ops/openclaw` altindadir.
Kokteki `dashboard.py`, `engine.py` ve `setup_openclaw.py` dosyalari bu klasore yonlendiren ince wrapper dosyalaridir.

## Hizli Baslangic

1. Python bagimliliklarini kurun:

```bash
py setup_openclaw.py
```

2. Uygulamayi baslatin:

```text
AnaliziBaslat.bat
```

Isterseniz Streamlit'i dogrudan da baslatabilirsiniz:

```bash
py -m streamlit run dashboard.py
```

## Gereksinimler

- Python 3.10+
- Ollama
- Opsiyonel LinkedIn `li_at` oturum cerezi

`setup_openclaw.py`, gerekli Python paketlerini ve Playwright Chromium kurulumunu yapar.
Kurulum sirasinda `ops/openclaw/.env` dosyasi olusturulur veya mevcutsa korunur.
Windows üzerinde Python 3.14 kullanılıyorsa Playwright tabanlı tarayıcı modu otomatik kapatılır ve HTTP fallback devrede kalır. Tam tarayıcı akışı için Python 3.10-3.13 önerilir.

## Proje Yapisi

- `ops/openclaw/dashboard.py`: kanonik Streamlit arayuzu
- `ops/openclaw/engine.py`: arama, filtreleme ve veri toplama motoru
- `ops/openclaw/setup_openclaw.py`: kurulum sihirbazi
- `AnaliziBaslat.bat`: uygulama baslaticisi

## Notlar

- Kokteki wrapper dosyalari, eski dokuman ve komutlari bozmadan tek kaynak kod duzenini korumak icindir.
- `runtime-workspace` klasoru calisma zamani artefaktlari icin tutulur; uygulamanin esas kaynak kodu degildir.
