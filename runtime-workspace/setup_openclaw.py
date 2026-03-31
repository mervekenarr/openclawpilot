import os
import sys
import subprocess
import secrets

def run_command(command):
    try:
        subprocess.run(command, shell=True, check=True)
        return True
    except subprocess.CalledProcessError:
        return False

def main():
    print("==================================================")
    print("🤖 OpenClaw AI Satış Asistanı - Kurulum Sihirbazı")
    print("==================================================")
    
    # 1. Bağımlılıkların Kontrolü
    print("\n[1/3] Python kütüphaneleri kuruluyor...")
    if run_command("pip install -r requirements.txt"):
        print("✅ Kütüphaneler başarıyla kuruldu.")
    else:
        print("❌ HATA: Kütüphaneler kurulurken bir sorun oluştu.")
        return

    # 2. Playwright Kurulumu
    print("\n[2/3] Tarayıcı motoru (Playwright) hazırlanıyor...")
    if run_command("playwright install chromium"):
        print("✅ Tarayıcı hazır.")
    else:
        print("❌ HATA: Playwright kurulurken bir sorun oluştu.")
        return

    # 3. Yapılandırma (.env) Oluşturma
    print("\n[3/3] Yapılandırma dosyası (.env) kontrol ediliyor...")
    
    if not os.path.exists(".env"):
        ollama_url = input("Ollama URL'niz (Varsayılan: http://127.0.0.1:11434): ").strip()
        if not ollama_url:
            ollama_url = "http://127.0.0.1:11434"
            
        li_at = input("LinkedIn 'li_at' Çerezi (Boş bırakılabilir): ").strip()
        
        with open(".env", "w", encoding="utf-8") as f:
            f.write(f"OLLAMA_BASE_URL={ollama_url}\n")
            f.write(f"LINKEDIN_SESSION_TOKEN={li_at}\n")
            f.write("OPENCLAW_MODE=sandbox\n")
        print("✅ .env dosyası oluşturuldu.")
    else:
        print("ℹ️  Mevcut .env dosyası korundu.")

    print("\n==================================================")
    print("🎉 Kurulum Başarıyla Tamamlandı!")
    print("Artık 'AnaliziBaslat.bat' ile uygulamayı açabilirsiniz.")
    print("==================================================")

if __name__ == "__main__":
    main()
