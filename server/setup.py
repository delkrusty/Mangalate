"""Interactive local installer: python setup.py. No extra Python dependencies."""
import getpass
import os
import secrets
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlparse
from hardware import detect
from providers import PRESETS, dump_secret, validate_base

ROOT = Path(__file__).resolve().parent


def save_secret(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def configure(profile, hardware, bind, api_base="", model="", provider_key="", root=ROOT, providers=None):
    # "basic" (NLLB) is no longer offered by the menu; it stays accepted for the
    # keyless CI pipeline check and for installations made before 0.5.3.
    if profile not in {"basic", "byok"} or hardware not in {"cpu", "gpu", "amd-rocm"}:
        raise ValueError("Perfil/hardware inválidos.")
    if profile == "byok" and providers:
        for item in providers:
            if not validate_base(item["base"]) or not item["model"]:
                raise ValueError(f"{item['name']}: endereço HTTPS (ou Ollama local) e modelo são obrigatórios.")
            if not item["key"] and urlparse(item["base"]).hostname not in {"host.docker.internal", "localhost", "127.0.0.1"}:
                raise ValueError(f"{item['name']}: falta a chave API.")
        api_base, model = providers[0]["base"], providers[0]["model"]
        provider_key = dump_secret(providers)
    elif profile == "byok":
        if not validate_base(api_base) or not model or not provider_key:
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


KEY_PREFIXES = {"groq": ("gsk_",), "gemini": ("AIza", "AQ."), "openrouter": ("sk-or-",)}


def read_clipboard():
    """Windows clipboard via PowerShell; '' when unavailable."""
    if os.name != "nt":
        return ""
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def ask_key(name, secret, ask=input, clipboard=read_clipboard):
    """Get an API key without the Windows hidden-prompt paste trap.

    On Windows: copy the key on the website and press Enter; it is read from
    the clipboard, so nothing needs to be pasted.  Elsewhere, or if the
    clipboard is empty, it can be pasted/typed.  The format is checked, so a
    half-typed key is caught before anything is saved.
    """
    prefixes = KEY_PREFIXES.get(name, ())
    for _ in range(3):
        key = ""
        if os.name == "nt" or clipboard is not read_clipboard:
            ask(f"  Copie a chave de {name} no site e aperte Enter aqui (não precisa colar): ")
            key = clipboard().strip()
        if not key:
            key = secret(f"  Cole a chave de {name} e aperte Enter (ela não aparece): ").strip()
        if not key or not all(ch.isprintable() and not ch.isspace() for ch in key):
            print("  Não recebi uma chave. Copie de novo no site (Ctrl+C ou botão Copiar) e tente outra vez.")
            continue
        if prefixes and not key.startswith(prefixes) or len(key) < 20:
            looks = " ou ".join(prefixes) or "uma sequência longa"
            print(f"  Isso não parece uma chave de {name} (deveria começar com {looks}). Copie de novo no site.")
            continue
        print(f"  Chave recebida: {len(key)} caracteres, termina em ...{key[-4:]}")
        return key
    raise ValueError(f"Chave de {name} não recebida.")


def yes_no(question, ask=input):
    while True:
        answer = ask(question).strip().lower()
        if answer in {"s", "sim", "n", "nao", "não", ""}:
            return answer in {"s", "sim"}
        print("  Responda s (sim) ou n (não).")


def choose_providers(ask=input, secret=getpass.getpass):
    """BYOK menu, one provider at a time, offering a backup after each key."""
    names = list(PRESETS)
    print("\nQual IA vai traduzir? Só o TEXTO das falas é enviado; as imagens ficam no seu PC.")
    print("Depois de configurar uma, você pode acrescentar outra de reserva: quando a primeira")
    print("atinge o limite grátis, a reserva assume sozinha.")
    providers = []
    queue = []
    while True:
        if not queue:
            used = {p["name"] for p in providers}
            print()
            for number, name in enumerate(names, 1):
                mark = "  (já configurado)" if name in used else ""
                print(f"  {number} {PRESETS[name]['label']}{mark}")
            print(f"  {len(names) + 1} Outro provedor compatível com OpenAI (endereço e modelo manuais)")
            default = "1" if not providers else ""
            picked = ask("Número da IA" + (" (Enter = 1 Groq)" if default else "") + ": ").strip() or default
            queue = [part.strip() for part in picked.split(",") if part.strip()]
        part = queue.pop(0)
        if not part.isdigit() or not 1 <= int(part) <= len(names) + 1:
            raise ValueError(f"Opção inválida: {part}")
        index = int(part) - 1
        if index < len(names) and names[index] in {p["name"] for p in providers}:
            print(f"  {names[index]} já está configurado.")
        else:
            providers.append(configure_one(index, names, providers, ask, secret))
        if queue:
            continue
        print("\nOrdem de uso: " + " → ".join(p["name"] for p in providers))
        if len(providers) > len(names) or not yes_no("Tem chave de outra IA para usar como reserva? [s/n]: ", ask):
            return providers


def configure_one(index, names, providers, ask, secret):
    if index == len(names):
        name = f"outro{len(providers) + 1}"
        base = ask("Endereço da API (https://...): ").strip()
        model = ask("Nome do modelo: ").strip()
    else:
        name, preset = names[index], PRESETS[names[index]]
        base = preset["base"]
        print(f"\n{preset['label']}")
        if preset["keys_url"]:
            print(f"  Crie a chave em: {preset['keys_url']}")
        if name == "ollama":
            print("  1) Instale o Ollama: https://ollama.com")
            print("  2) Em outro terminal, baixe UM modelo e deixe o Ollama aberto:")
            print("       16 GB de RAM ou mais:  ollama pull gpt-oss:20b   (14 GB)")
            print("       menos memória:         ollama pull gemma3:4b     (3,4 GB, qualidade menor)")
            print("  3) Digite abaixo o mesmo nome que você baixou.")
        if name == "openrouter":
            print("  Copie o nome de um modelo terminado em :free na lista do site.")
        default = preset["model"]
        hint = f" (Enter = {default})" if default else ""
        model = ""
        for _ in range(3):
            model = ask(f"  Modelo{hint}: ").strip() or default
            if model and model.upper() != "NOME":
                break
            print("  Digite o nome exato do modelo (ex.: gpt-oss:20b).")
            model = ""
        if not model:
            raise ValueError(f"Modelo de {name} não informado.")
    key = "" if name == "ollama" else ask_key(name, secret, ask)
    return {"name": name, "base": base, "model": model, "key": key}


def main():
    print("MANGALATE | instalação guiada")
    print("Servidor + IA: este computador lê, apaga e escreve; só o texto das falas vai para a IA que")
    print("você escolher (Groq e Gemini grátis, ou Ollama no próprio PC). Sem cobrança Mangalate.")
    profile = "byok"
    found = detect()
    print("Sistema:", found["os"], "| arquitetura:", found["architecture"])
    print("CPU atende qualquer fabricante. AMD/Intel no Windows usam CPU neste pacote.")
    print("A aceleração AMD/ROCm é experimental; DirectML/OpenVINO ainda não estão implementados.")
    choice = input("Hardware [1 CPU / 2 NVIDIA-CUDA / 3 AMD-ROCm Linux] (1): ").strip()
    hardware = {"2": "gpu", "3": "amd-rocm"}.get(choice, "cpu")
    if hardware == "amd-rocm" and found["os"] != "Linux":
        raise SystemExit("ROCm Docker neste pacote exige Linux. Escolha CPU; não é suporte DirectML no Windows.")
    if hardware == "amd-rocm" and not Path("/dev/kfd").exists():
        raise SystemExit("/dev/kfd ausente: prepare ROCm compatível no host ou escolha CPU.")
    bind = "0.0.0.0" if input("Celular na mesma rede Wi-Fi? Liberar rede local [s/N]: ").lower() == "s" else "127.0.0.1"
    if bind == "0.0.0.0":
        print("Use somente rede confiável; NÃO abra a porta 5003 no roteador/internet.")
    if (ROOT / ".env").exists() and not yes_no("Já existe configuração. Substituir pela nova? [s/n]: "):
        print("Nada foi alterado.")
        return
    providers = choose_providers() if profile == "byok" else None
    path, hardware = configure(profile, hardware, bind, root=ROOT, providers=providers)
    print("\nArquivo da chave Mangalate:", path)
    print("No app cole o conteúdo desse arquivo em Chave Mangalate, NÃO a chave da API.")
    print("Essa senha é privada. Não compartilhe prints dela.")
    print("Chave Mangalate:", path.read_text().strip())
    print("Endereço no app: http://IP-DO-COMPUTADOR:5003 (use ipconfig no Windows / hostname -I no Linux)")
    print("Para iniciar: docker compose --profile", hardware, "up --build -d")
    print("Prepare modelos e teste UMA página antes de abrir um capítulo: python check.py --warmup")
    if yes_no("Verificar Docker e iniciar agora? [s/n]: "):
        subprocess.run(["docker", "compose", "version"], cwd=ROOT, check=True)
        subprocess.run(["docker", "compose", "--profile", hardware, "up", "--build", "-d", "--force-recreate"], cwd=ROOT, check=True)


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError:
        raise SystemExit("Docker não encontrado. Instale/abra Docker Desktop e confira docker compose version.")
    except subprocess.CalledProcessError:
        raise SystemExit("Docker não terminou a instalação. Confira se está aberto, se há espaço em disco e as mensagens acima. Sua configuração foi preservada.")
    except (ValueError, OSError) as exc:
        raise SystemExit(f"Não foi possível configurar: {exc}")
    except KeyboardInterrupt:
        raise SystemExit("Instalação interrompida. Você pode executar python setup.py novamente.")
