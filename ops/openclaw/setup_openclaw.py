from pathlib import Path
import subprocess
import sys

APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parents[1]
REQUIREMENTS_PATH = REPO_ROOT / "requirements.txt"
ENV_PATH = APP_DIR / ".env"


def run_command(command, cwd):
    try:
        subprocess.run(command, cwd=str(cwd), check=True)
        return True
    except subprocess.CalledProcessError:
        return False


def main():
    print("==================================================")
    print("OpenClaw AI Satis Asistani - Kurulum Sihirbazi")
    print("==================================================")

    print("\n[1/3] Python kutuphaneleri kuruluyor...")
    if REQUIREMENTS_PATH.exists() and run_command(
        [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_PATH)],
        REPO_ROOT,
    ):
        print("Kutuphaneler basariyla kuruldu.")
    else:
        print("HATA: Kutuphaneler kurulurken bir sorun olustu.")
        return

    print("\n[2/3] Tarayici motoru (Playwright) hazirlaniyor...")
    if run_command([sys.executable, "-m", "playwright", "install", "chromium"], REPO_ROOT):
        print("Tarayici hazir.")
    else:
        print("HATA: Playwright kurulurken bir sorun olustu.")
        return

    print("\n[3/3] Yapilandirma dosyasi (.env) kontrol ediliyor...")
    if not ENV_PATH.exists():
        ollama_url = input("Ollama URL'niz (Varsayilan: http://127.0.0.1:11434): ").strip()
        if not ollama_url:
            ollama_url = "http://127.0.0.1:11434"

        li_at = input("LinkedIn 'li_at' cereziniz (bos birakilabilir): ").strip()

        ENV_PATH.write_text(
            "\n".join(
                [
                    f"OLLAMA_BASE_URL={ollama_url}",
                    f"LINKEDIN_SESSION_TOKEN={li_at}",
                    "OPENCLAW_MODE=sandbox",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        print(".env dosyasi olusturuldu.")
    else:
        print("Mevcut .env dosyasi korundu.")

    print("\n==================================================")
    print("Kurulum basariyla tamamlandi.")
    print("Artik 'AnaliziBaslat.bat' ile uygulamayi acabilirsiniz.")
    print("==================================================")


if __name__ == "__main__":
    main()
