# OpenClaw Pilot

FastAPI tabanli satis pilotu. Guvenli web arastirmasi, AI draft review ve CRM akisina odaklanir.

## PostgreSQL with Docker

1. Copy `.env.example` to `.env`
2. Adjust `POSTGRES_*` and `DATABASE_URL` if needed
3. Start PostgreSQL:

```bash
docker compose up -d
```

4. Run the API:

```bash
uvicorn app.main:app --reload
```

The app loads `.env` automatically on startup and uses `DATABASE_URL` when present.

## OpenClaw Setup

Pilot su anda `FastAPI -> OpenClaw adapter -> draft review` siniri ile calisir.
OpenClaw hicbir zaman veritabanina dogrudan baglanmaz.

Detayli guvenli kurulum notlari:

- [docs/openclaw-secure-setup.md](docs/openclaw-secure-setup.md)

Ornek `.env` ayarlari:

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

Modlar:

- `sandbox`: OpenClaw request/response panelini acik tutar, ama canli call yapmaz
- `gateway`: gateway konfigurasyonunu bekler; canli call bu pilotta henuz kapali

## OpenClaw Docker Kurulumu

Resmi docs'a gore Docker opsiyoneldir. Izole ve ayri bir Gateway runtime istiyorsan dogru secenek; ama tek makinede en hizli dev loop icin zorunlu degildir.

Bu repo artik guvenli varsayilanlarla opsiyonel bir Docker OpenClaw profili tasir:

- servis adi: `openclaw-gateway`
- profil: `openclaw`
- port: `18789`
- PostgreSQL baglantisi yok
- browser otomasyonu bizim uygulama tarafinda kapali kalir
- state: Docker named volume `openclaw_home`
- host repo/workspace mount yok

Onerilen guvenli akış:

1. `.env.example` icindeki `OPENCLAW_DOCKER_*` degiskenlerini gerekirse `.env`e kopyala.
2. Ilk onboarding'i resmi manual flow ile container icinde yap:

```bash
docker compose --profile openclaw run --rm --no-deps --entrypoint node openclaw-gateway dist/index.js onboard --mode local --no-install-daemon
docker compose --profile openclaw run --rm --no-deps --entrypoint node openclaw-gateway dist/index.js config set gateway.mode local
docker compose --profile openclaw run --rm --no-deps --entrypoint node openclaw-gateway dist/index.js config set gateway.bind loopback
```

3. Token auth ac:

```bash
docker compose --profile openclaw run --rm --no-deps --entrypoint node openclaw-gateway dist/index.js config set gateway.auth.mode token
docker compose --profile openclaw run --rm --no-deps --entrypoint node openclaw-gateway dist/index.js config set gateway.auth.token "<uzun-random-token>"
```

4. Gateway'i baslat:

```bash
docker compose --profile openclaw up -d openclaw-gateway
```

5. UI/health kontrol:

```bash
curl http://127.0.0.1:18789/healthz
curl http://127.0.0.1:18789/readyz
```

6. Dashboard URL'ini al:

```bash
docker compose --profile openclaw run --rm openclaw-cli dashboard --no-open
```

Bu repo icin guvenli sinir:

- `bind=loopback`
- `auth.mode=token`
- DB mount yok
- repo workspace mount yok
- host dosya sistemi mount yok
- LinkedIn / browser / live send kapali
- OpenClaw sadece FastAPI arkasinda, kontrollu tool katmaniyla kullanilir

Onerilen sira:

1. `OPENCLAW_MODE=sandbox`
2. `OPENCLAW_DRY_RUN_ONLY=false`
3. `SAFE_WEB_RESEARCH_ENABLED=true` yapmadan once sadece AI draft test et
4. Gercek web arastirmasi icin dashboarddaki `Firma arama` veya `Gercek firma ekle` yolunu kullan
5. LinkedIn ve browser automation kapali kalsin

## Ollama Hazirligi

Yarin hizli ilerlemek icin hedef:

1. `Ollama` lokal calissin
2. `OLLAMA_MODEL` indirilsin
3. `.env` icinde `OPENCLAW_MODEL_PROVIDER=ollama` kalsin
4. Ilk test sadece `dry run` veya `smoke test` olsun

Guvenlik cizgisi:

- `OPENCLAW_ALLOW_BROWSER_AUTOMATION=false`
- `OPENCLAW_ALLOW_LIVE_SEND=false`
- OpenClaw dogrudan DB'ye baglanmaz
- OpenClaw sadece draft uretir, kayda yazma yine FastAPI onayi ile olur

## Default URLs

- API docs: `http://127.0.0.1:8000/docs`
- Dashboard: `http://127.0.0.1:8000/dashboard`
