Bu dizin OpenClaw Docker kurulum ve skill paketidir.

Ana dosyalar:

- `setup-openclaw-docker.ps1`
  tum kurulumu baslatir
- `build-openclaw.ps1`
  global OpenClaw paketinden lokal Docker image build eder
- `docker-compose.yml`
  OpenClaw gateway ve CLI servisleri
- `dashboard/index.html`
  yardimci yerel panel
- `skills/`
  workspace skill'leri

Runtime'da olusacak local klasorler:

- `runtime-home/`
- `runtime-workspace/`

Bu klasorler git'e girmez.

Beklenen kullanim:

```powershell
cd .\ops\openclaw
powershell -ExecutionPolicy Bypass -File .\setup-openclaw-docker.ps1
```

Paneli acmak icin:

```powershell
start .\dashboard\index.html
```

Not:

- panel LinkedIn giris sayfasini acabilir
- ama LinkedIn sifresi, cookie veya session saklamaz
- web arama icin OpenClaw gateway tokenini elle girersin
