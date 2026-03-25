Bu dizin, Docker ile calistirilacak OpenClaw gateway state'i icin ayrildi.

Beklenen alt dizinler:

- `home/`
- `workspace/`

Bu klasorler git'e girmez. Amac:

- OpenClaw state'ini uygulama kodundan ayirmak
- DB ve repo workspace'i ile ayni trust boundary'de tutmamak
- Gerekirse Docker OpenClaw runtime'ini tek hamlede temizleyebilmek

Bu dizinler ilk kurulumda manuel olusturulabilir:

```powershell
New-Item -ItemType Directory -Force -Path .\ops\openclaw\home, .\ops\openclaw\workspace
```
