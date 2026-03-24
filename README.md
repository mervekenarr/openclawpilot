# OpenClaw Pilot

Mock sales workflow pilot built with FastAPI.

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

Ornek `.env` ayarlari:

```env
OPENCLAW_MODE=sandbox
OPENCLAW_DRY_RUN_ONLY=true
OPENCLAW_CHANNEL=api
OPENCLAW_WORKSPACE_TAG=sales-pilot
OPENCLAW_GATEWAY_URL=
OPENCLAW_API_KEY=
OPENCLAW_MODEL_PROVIDER=ollama
OPENCLAW_MODEL_NAME=qwen2.5:7b-instruct
OPENCLAW_ALLOW_BROWSER_AUTOMATION=false
OPENCLAW_ALLOW_LIVE_SEND=false
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5:7b-instruct
```

Modlar:

- `mock`: mevcut demo davranisi
- `sandbox`: OpenClaw request/response panelini acik tutar, ama canli call yapmaz
- `gateway`: gateway konfigurasyonunu bekler; canli call bu pilotta henuz kapali

Onerilen sira:

1. `OPENCLAW_MODE=sandbox`
2. `OPENCLAW_DRY_RUN_ONLY=true`
3. Dashboard uzerinden `OpenClaw sandbox` panelini kullan
4. Ancak guvenlik karari verildikten sonra gateway URL ve API key ekle

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
