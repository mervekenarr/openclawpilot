import os
import subprocess
import json
import secrets
import shutil
import time
import argparse

def run_command(command, check=True):
    try:
        # Check if command is a list for subprocess
        if isinstance(command, str):
            res = subprocess.run(command, shell=True, check=check, capture_output=True, text=True)
        else:
            res = subprocess.run(command, check=check, capture_output=True, text=True)
        return res.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Hata oluştu: {e.stderr}")
        if check:
            exit(1)
        return None

def invoke_openclaw_config(args):
    compose_args = [
        "docker", "compose", "run", "--rm", "--no-deps",
        "--entrypoint", "node", "openclaw-gateway", "dist/index.js"
    ] + args
    print(f"Konfigürasyon çalıştırılıyor: {' '.join(args)}")
    subprocess.run(compose_args, check=True)

def main():
    parser = argparse.ArgumentParser(description="OpenClaw Docker Kurulumu (Python)")
    parser.add_argument("--ollama-url", default="http://172.16.41.43:11434", help="Ollama Base URL")
    parser.add_argument("--ollama-model", default="qwen2.5:14b", help="Ollama Model Adı")
    parser.add_argument("--token", default="", help="Gateway Token (boşsa rastgele oluşturulur)")
    parser.add_argument("--force-build", action="store_true", help="Docker imajını zorla build et")
    
    args = parser.parse_args()
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    gateway_token = args.token if args.token else secrets.token_hex(32)
    runtime_home = os.path.join(script_dir, "runtime-home")
    runtime_workspace = os.path.join(script_dir, "runtime-workspace")
    
    os.makedirs(runtime_home, exist_ok=True)
    os.makedirs(runtime_workspace, exist_ok=True)
    
    print(f"\n--- OpenClaw Docker Kurulumu Başlıyor ---")
    print(f"Runtime Home: {runtime_home}")
    print(f"Runtime Workspace: {runtime_workspace}")
    print(f"Ollama: {args.ollama_url} | Model: {args.ollama_model}\n")
    
    # 1/5 - Docker Image Hazırlığı
    npm_root = run_command("npm root -g")
    package_json = os.path.join(npm_root, "openclaw", "package.json")
    with open(package_json, "r") as f:
        version = json.load(f).get("version")
    
    image_tag = f"openclaw-local:{version}"
    os.environ["OPENCLAW_IMAGE"] = image_tag
    
    # Image kontrolü
    check_image = run_command(f"docker image inspect {image_tag}", check=False)
    if args.force_build or not check_image:
        print("Docker image build ediliyor...")
        subprocess.run(["python", "build_openclaw.py"], check=True)
    else:
        print(f"Mevcut image kullanılıyor: {image_tag}")
        
    # .env dosyası oluşturma
    with open(".env", "w") as f:
        f.write(f"OPENCLAW_IMAGE={image_tag}\n")
        f.write("OPENCLAW_GATEWAY_BIND=loopback\n")

    # 2/5 - Konfigürasyon Ayarları
    print("\n2/5 - Konfigürasyon ve Güvenlik ayarları yazılıyor...")
    config_steps = [
        ["config", "set", "gateway.mode", "local"],
        ["config", "set", "gateway.bind", "loopback"],
        ["config", "set", "gateway.auth.mode", "token"],
        ["config", "set", "gateway.auth.token", gateway_token],
        ["config", "set", "gateway.controlUi.allowedOrigins", '["http://127.0.0.1:18789","http://localhost:18789"]', "--strict-json"],
        ["config", "set", "browser.enabled", "false", "--strict-json"],
        ["config", "set", "models.providers.ollama.apiKey", "ollama-local"],
        ["config", "set", "models.providers.ollama.baseUrl", args.ollama_url],
        ["config", "set", "models.providers.ollama.api", "ollama"],
        ["config", "set", "agents.defaults.model.primary", f"ollama/{args.ollama_model}"]
    ]
    
    for step in config_steps:
        invoke_openclaw_config(step)
        
    # Batch konfigürasyon (Ollama modelleri için)
    batch_config = [
        {
            "path": "models.providers.ollama.models",
            "value": [
                {
                    "id": args.ollama_model,
                    "name": args.ollama_model,
                    "reasoning": False,
                    "input": ["text"],
                    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                    "contextWindow": 32768,
                    "maxTokens": 81920
                }
            ]
        },
        {
            "path": "agents.defaults.models",
            "value": {f"ollama/{args.ollama_model}": {}}
        }
    ]
    
    batch_path_host = os.path.join(runtime_home, "config-set.batch.json")
    batch_path_container = "/home/node/.openclaw/config-set.batch.json"
    
    with open(batch_path_host, "w") as f:
        json.dump(batch_config, f, indent=2)
        
    invoke_openclaw_config(["config", "set", "--batch-file", batch_path_container])
    if os.path.exists(batch_path_host):
        os.remove(batch_path_host)

    # 3/5 - Onboarding
    print("\n3/5 - İlk onboarding çalıştırılıyor...")
    invoke_openclaw_config(["onboard", "--mode", "local", "--no-install-daemon"])

    # 4/5 - Skills Kopyalama
    print("\n4/5 - Skill'ler runtime workspace'e kopyalanıyor...")
    skills_source = os.path.join(script_dir, "skills")
    skills_target = os.path.join(runtime_workspace, "skills")
    
    if os.path.exists(skills_source):
        # Shutil.copytree requires target NOT to exist or handle it
        if os.path.exists(skills_target):
            shutil.rmtree(skills_target)
        shutil.copytree(skills_source, skills_target)

    # 5/5 - Gateway Başlatma
    print("\n5/5 - Gateway başlatılıyor...")
    subprocess.run(["docker", "compose", "up", "-d", "openclaw-gateway"], check=True)
    time.sleep(5)
    subprocess.run(["docker", "compose", "ps"], check=True)
    
    print(f"\n✅ OpenClaw Docker kurulumu tamamlandı.")
    print(f"Dashboard: http://127.0.0.1:18789/")
    print(f"Token: {gateway_token}")
    print(f"\nKontrol için: docker compose run --rm openclaw-cli skills list")

if __name__ == "__main__":
    main()
