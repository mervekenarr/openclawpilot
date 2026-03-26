# OpenClaw Pilot

Bu repo artik `OpenClaw-first` teslim paketidir.

Amac:

- OpenClaw ile `urun + sektor` bazli firma aramak
- bulunan resmi web sitelerini okumak
- kisa ve satis odakli ozet cikarmak
- bunu guvenli, `read-only` ve LinkedIn otomasyonsuz yapmak

Bu repoda artik `FastAPI`, CRM ve outreach kodu yoktur. Teslim paketi Docker'da calisan OpenClaw gateway, skill'ler ve yardimci panelden olusur.

## Mimari

```text
OpenClaw Docker Gateway -> Skills -> Public Web Search / Official Website Read -> Ollama
```

Guvenlik siniri:

- LinkedIn otomasyonu yok
- browser automation yok
- canli mesaj gonderimi yok
- cookie / sifre / oturum saklama yok
- sadece public web ve resmi website okuma var

## Repo Yapisi

- `ops/openclaw/`
  OpenClaw Docker kurulum ve skill paketi
- `ops/openclaw/skills/company-search/`
  urun + sektor ile firma arama
- `ops/openclaw/skills/company-website-read/`
  resmi website okuma
- `ops/openclaw/skills/company-lead-discovery/`
  arama + website okuma + kisa liste
- `ops/openclaw/dashboard/index.html`
  yerel yardimci panel

## Hizli Kurulum

1. Docker Desktop'i ac.
2. Makinede global `openclaw` npm paketi kurulu olsun.
3. Asagidaki scripti calistir:

```powershell
cd C:\Users\bt.stajyer\openclawpilot\openclawpilot\ops\openclaw
powershell -ExecutionPolicy Bypass -File .\setup-openclaw-docker.ps1
```

Varsayilanlar:

- Ollama URL: `http://172.16.41.43:11434`
- Model: `qwen2.5:14b`
- Gateway: `127.0.0.1:18789`

Script ne yapar:

- global OpenClaw paketinden lokal Docker image build eder
- Docker icinde OpenClaw onboarding yapar
- `loopback + token auth` ayarlar
- browser'i kapatir
- remote Ollama'ya baglar
- gateway'i ayaga kaldirir
- skill'leri runtime workspace'e kopyalar

## Yardimci Panel

Yardimci paneli acmak icin:

```powershell
start C:\Users\bt.stajyer\openclawpilot\openclawpilot\ops\openclaw\dashboard\index.html
```

Panel ne yapar:

- OpenClaw arama promptunu hazirlar
- OpenClaw arayuzunu token ile acar
- LinkedIn giris sayfasini ayri sekmede acar

LinkedIn butonu sadece giris sayfasini acar. Otomatik login, session tasima veya token saklama yapilmaz.

## OpenClaw'da Kullanim

OpenClaw chat'te su prompt ile baslayabilirsin:

```text
Vana ve metal sektorunde Turkiye'deki uretici firmalari ara. company-lead-discovery skillini kullan. Bana firma adi, resmi web sitesi, kisa Turkce ozet ve neden uygun olabilecegini listele. LinkedIn kullanma.
```

## LinkedIn Notu

Bu repo LinkedIn'e otomatik girmez.

Ozellikle yapmadigimiz seyler:

- sahte hesap
- gecici mail
- otomatik login
- bot / scraping
- cookie / session kopyalama

OpenClaw burada `web arama ve website arastirma` motorudur.
