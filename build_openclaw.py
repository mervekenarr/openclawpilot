import os
import subprocess
import json
import sys

def run_command(command, shell=True):
    try:
        result = subprocess.check_output(command, shell=shell, stderr=subprocess.STDOUT, text=True)
        return result.strip()
    except subprocess.CalledProcessError as e:
        print(f"Hata oluştu: {e.output}")
        sys.exit(1)

def main():
    print("--- OpenClaw Docker Build (Python) ---")
    
    # 1. Global npm root bulma
    npm_root = run_command("npm root -g")
    if not npm_root:
        print("Hata: Global npm root bulunamadı.")
        sys.exit(1)
        
    source_dir = os.path.join(npm_root, "openclaw")
    if not os.path.exists(source_dir):
        print(f"Hata: Global openclaw paketi bulunamadı: {source_dir}")
        sys.exit(1)
        
    # 2. Versiyon okuma
    package_json_path = os.path.join(source_dir, "package.json")
    if not os.path.exists(package_json_path):
        print(f"Hata: package.json bulunamadı: {package_json_path}")
        sys.exit(1)
        
    with open(package_json_path, "r", encoding="utf-8") as f:
        package_data = json.load(f)
        version = package_data.get("version")
        
    if not version:
        print("Hata: openclaw versiyonu okunamadı.")
        sys.exit(1)
        
    # 3. Docker build
    # Dockerfile.local dosyası bu betikle aynı dizinde olmalı
    script_dir = os.path.dirname(os.path.abspath(__file__))
    dockerfile_path = os.path.join(script_dir, "Dockerfile.local")
    image_tag = f"openclaw-local:{version}"
    
    print(f"OpenClaw kaynak dizini: {source_dir}")
    print(f"Docker image etiketi: {image_tag}")
    
    build_cmd = f'docker build -t {image_tag} -f "{dockerfile_path}" "{source_dir}"'
    print(f"Çalıştırılıyor: {build_cmd}")
    
    os.system(build_cmd)
    print("\nDerleme tamamlandı.")

if __name__ == "__main__":
    main()
