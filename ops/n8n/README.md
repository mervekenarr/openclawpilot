# n8n Workflow Notes

Bu klasördeki `openclaw_linkedin_lead_pipeline.json`, mevcut `OpenClaw - LinkedIn Lead Pipeline` akışının daha dayanıklı bir sürümüdür.

Ne düzeldi:
- Webhook'tan gelen payload önce normalize edilir.
- `LinkedIn URL` varsa lead `linkedin_ready` olarak işaretlenir.
- LinkedIn URL yoksa lead sessizce düşmez; `web_only` olarak işaretlenir.
- LinkedIn hazır olan kayıtlar `http://openclaw-sales-assistant:8502/send-message` endpoint'ine gider.
- İki branch de en sonda merge edilir, böylece execution datasında neler işlendiği daha net görünür.

Beklenen input alanları:
- `Şirket`
- `Sales Script`
- `Website`
- `LinkedIn URL`
- `URL`

Not:
- Uygulama tarafı artık `Website`, `LinkedIn URL` ve `URL` alanlarını birlikte gönderiyor.
- `URL` alanı downstream için öncelikli lead URL'dir; LinkedIn varsa LinkedIn URL, yoksa website olur.
