"""Interactive local installer: python setup.py. No extra Python dependencies."""
import getpass
import os
import secrets
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent


def save_secret(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def configure(profile, hardware, bind, api_base="", model="", provider_key="", root=ROOT):
    if profile not in {"basic", "byok"} or hardware not in {"cpu", "gpu"}:
        raise ValueError("Perfil/hardware inválidos.")
    if profile == "byok":
        url = urlparse(api_base)
        if url.scheme != "https" or not url.netloc or not model or not provider_key:
            raise ValueError("BYOK exige endpoint HTTPS, modelo e sua chave API.")
    key_path = root / "secrets/mangalate_key.txt"
    access = key_path.read_text().strip() if key_path.exists() else secrets.token_urlsafe(32)
    if len(access) < 24:
        raise ValueError("Chave existente fraca: renomeie o arquivo e rode novamente.")
    save_secret(key_path, access)
    provider_path = root / "secrets/provider_key.txt"
    save_secret(provider_path, provider_key if profile == "byok" else "")
    lines = [
        f"MANGALATE_PROFILE={profile}", f"MANGALATE_BIND={bind}",
        "MANGALATE_KEY_FILE=./secrets/mangalate_key.txt",
        "MANGALATE_API_KEY_FILE=./secrets/provider_key.txt",
        "MANGALATE_ALLOW_ART_TEXT=false",
        f"CUSTOM_OPENAI_API_BASE={api_base}", f"CUSTOM_OPENAI_MODEL={model}",
    ]
    if any("\n" in value or "\r" in value for value in (api_base, model, bind)):
        raise ValueError("Valores não podem conter quebras de linha.")
    (root / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return key_path, hardware


def main():
    print("MANGALATE | instalação guiada")
    print("Básico: sem API paga. BYOK: servidor e API pagos diretamente por você, sem cobrança Mangalate.")
    profile = "byok" if input("Perfil [1 Básico / 2 BYOK] (1): ").strip() == "2" else "basic"
    hardware = "gpu" if input("Placa NVIDIA preparada para Docker? [s/N]: ").lower() == "s" else "cpu"
    bind = "0.0.0.0" if input("Celular na mesma rede Wi-Fi? Liberar rede local [s/N]: ").lower() == "s" else "127.0.0.1"
    if bind == "0.0.0.0":
        print("Use somente rede confiável; NÃO abra a porta 5003 no roteador/internet.")
    base = model = key = ""
    if profile == "byok":
        print("Requer API Chat Completions compatível (max_tokens/temperature/top_p). Limite gastos na conta do provedor.")
        base = input("Endpoint HTTPS (ex.: https://api.deepseek.com/v1): ").strip()
        model = input("Nome EXATO do modelo fornecido pelo provedor: ").strip()
        key = getpass.getpass("Sua chave API (oculta; nunca será enviada ao app): ").strip()
    if (ROOT / ".env").exists() and input("Já existe configuração. Substituir .env? [s/N]: ").lower() != "s":
        return
    path, hardware = configure(profile, hardware, bind, base, model, key)
    print("\nArquivo da chave Mangalate:", path)
    print("No app cole o conteúdo desse arquivo em Chave Mangalate, NÃO a chave da API.")
    print("Essa senha é privada. Não compartilhe prints dela.")
    print("Chave Mangalate:", path.read_text().strip())
    print("Endereço no app: http://IP-DO-COMPUTADOR:5003 (use ipconfig no Windows / hostname -I no Linux)")
    print("Para iniciar: docker compose --profile", hardware, "up --build -d")
    print("Prepare modelos e teste UMA página antes de abrir um capítulo: python check.py --warmup")
    if input("Verificar Docker e iniciar agora? [s/N]: ").lower() == "s":
        subprocess.run(["docker", "compose", "version"], cwd=ROOT, check=True)
        subprocess.run(["docker", "compose", "--profile", hardware, "up", "--build", "-d"], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
