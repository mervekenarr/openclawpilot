# OpenClaw Secure Setup

Bu dokumanin amaci projede OpenClaw tarafini "guvenli minimum yetki" mantigi ile kurmaktir.

## 1. Hedef Mimari

Bu projede ana kontrol siniri hep su olacak:

`Dashboard -> FastAPI -> OpenClaw adapter -> Ollama`

ve

`Dashboard -> FastAPI -> PostgreSQL`

Temel kural:

- OpenClaw dogrudan DB'ye baglanmaz
- OpenClaw dogrudan CRM'e yazmaz
- OpenClaw dogrudan mesaj gondermez
- OpenClaw dogrudan LinkedIn hesabina girmez
- Son yazma karari her zaman FastAPI + kullanici onayi ile olur

## 2. Bugun Itibariyla Durum

Su an projede bunlar hazir:

- FastAPI backend hazir
- PostgreSQL baglantisi hazir
- Dashboard hazir
- AI draft / review akisi hazir
- Remote Ollama baglantisi dogrulandi
- Sanitize edilmis payload ile canli enrichment draft uretebiliyoruz

Su an bunlar kapali veya henuz yok:

- LinkedIn arama otomasyonu
- Browser automation
- Canli mesaj gonderimi
- OpenClaw gateway uzerinden tam ajan akisi

## 3. Zorunlu Guvenlik Kurallari

Asagidaki maddeler bu proje icin kirmizi cizgidir:

1. Kisisel LinkedIn hesabi kullanma.
2. Gecici mail ile sahte LinkedIn hesabi acma.
3. OpenClaw'a DB connection string verme.
4. OpenClaw'a CRM yazma yetkisi verme.
5. OpenClaw'a browser automation yetkisini erken verme.
6. Insan onayi olmadan mesaj gonderme.
7. Tum lead havuzunu veya tum CRM export'unu modele gonderme.

## 4. Gerekli Ortamlar

Minimum kurulum:

- Lokal FastAPI uygulamasi
- Lokal veya Docker PostgreSQL
- Remote Ollama sunucusu
- Opsiyonel local OpenClaw UI/gateway

Not:

- OpenClaw UI kurulu olsa bile proje entegrasyonu otomatik olarak tamam sayilmaz
- Asil onemli olan proje icindeki adapter siniridir

## 5. .env Ayarlari

Guvenli minimum ayarlar:

```env
OPENCLAW_MODE=sandbox
OPENCLAW_DRY_RUN_ONLY=false
OPENCLAW_CHANNEL=api
OPENCLAW_WORKSPACE_TAG=sales-pilot
OPENCLAW_GATEWAY_URL=
OPENCLAW_API_KEY=

OPENCLAW_MODEL_PROVIDER=ollama
OPENCLAW_MODEL_NAME=qwen2.5:14b

OPENCLAW_ALLOW_BROWSER_AUTOMATION=false
OPENCLAW_ALLOW_LIVE_SEND=false
SAFE_WEB_RESEARCH_ENABLED=false
SAFE_WEB_RESEARCH_TIMEOUT=8

OLLAMA_BASE_URL=http://172.16.41.43:11434
OLLAMA_MODEL=qwen2.5:14b
OLLAMA_TIMEOUT=300
```

Anlamlari:

- `OPENCLAW_MODE=sandbox`: adapter guvenli sinirda calisir
- `OPENCLAW_DRY_RUN_ONLY=false`: gercek Ollama draft uretilmesine izin verir
- `OPENCLAW_ALLOW_BROWSER_AUTOMATION=false`: tarayiciya dokunma yok
- `OPENCLAW_ALLOW_LIVE_SEND=false`: mesaj gonderme yok
- `SAFE_WEB_RESEARCH_ENABLED=true`: sadece sirket web sitesi tabanli read-only arastirmayi acar

## 6. Adim Adim Kurulum

### Adim 1

PostgreSQL ayaga kalksin:

```powershell
docker compose up -d
```

### Adim 2

API acilsin:

```powershell
uvicorn app.main:app --reload
```

### Adim 3

Ollama baglantisini dogrula:

- `GET /system/ollama-check`

Beklenen sonuc:

- `reachable: true`
- `model_installed: true`

### Adim 4

Dashboard ac:

- `/dashboard`

### Adim 5

Bir raw lead sec ve AI taslagi uret.

Beklenen davranis:

- Sadece sanitize edilmis payload gider
- Model draft dondurur
- Draft dogrudan kayda uygulanmaz
- Kullanici onayi beklenir

### Adim 6

Gercek firma ile read-only arastirma yapmak istersen:

- `.env` icinde `SAFE_WEB_RESEARCH_ENABLED=true`
- Dashboard'da `Gercek firma ekle`
- Gercek bir sirket sitesi ile kayit olustur
- Sonra `Arastirmayi calistir`

Bu akista:

- Sadece public web sitesi okunur
- LinkedIn kullanilmaz
- Browser automation kullanilmaz

## 7. OpenClaw'a Giden Veri

Guvenli payload:

- `raw_lead_id`
- `company_name`
- `website`
- `sector`
- `keyword`
- `source`
- `missing_fields`

## 8. OpenClaw'a Asla Gitmeyecek Veri

- `DATABASE_URL`
- DB kullanici bilgileri
- `.env` tam icerigi
- LinkedIn sifresi / cookie / token
- Tarayici profili
- Tum CRM dump'i
- Tum lead havuzu
- Kullaniciya ait hassas notlar

## 9. LinkedIn'e Gecmeden Once Zorunlu Kontrol

LinkedIn tarafina ancak su kosullardan sonra gecilebilir:

1. Ollama draft akisi kararli calisiyor olmali.
2. Review/onay akisi net olusmali.
3. Browser automation hala kapali olmali.
4. Read-only arastirma adapter'i tasarlanmis olmali.
5. Kullanilacak hesap sirket onayli ayrik bir hesap olmali.
6. Mumkunse ayri browser profile ya da VM kullanilmali.

## 10. Bir Sonraki Guvenli Adim

Bir sonraki dogru teknik adim:

- LinkedIn otomasyonu degil
- Once `read-only company research adapter`
- Sonra `manual review`
- En son `opsiyonel browser automation`

Yani siralama:

`Ollama draft -> review -> safe research adapter -> LinkedIn read-only -> browser automation en son`
