"""One container for a rented GPU machine (RunPod and similar): engine + app gateway.

Configured only by environment variables, set in the provider's page:
  MANGALATE_KEY       the Mangalate password typed in the app (24+ characters;
                      when missing, one is created and printed in the log)
  GROQ_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY (+ OPENROUTER_MODEL)
                      the user's own AI keys; at least one
Port 5003 is the address the app uses. When /workspace exists (the machine's
persistent disk), models and the work memory live there and survive restarts.
"""
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from providers import PRESETS, dump_secret  # noqa: E402

KEYS = (("groq", "GROQ_API_KEY", ""), ("gemini", "GEMINI_API_KEY", ""),
        ("openrouter", "OPENROUTER_API_KEY", "OPENROUTER_MODEL"))


def providers_from_env(env):
    found = []
    for name, key_var, model_var in KEYS:
        key = env.get(key_var, "").strip()
        if not key:
            continue
        model = (env.get(model_var, "") if model_var else "").strip() or PRESETS[name]["model"]
        if not model:
            raise SystemExit(f"{key_var} definida, mas falta {model_var} (o modelo :free escolhido).")
        found.append({"name": name, "base": PRESETS[name]["base"], "model": model, "key": key})
    if not found:
        raise SystemExit("Defina ao menos uma chave de IA: GROQ_API_KEY, GEMINI_API_KEY ou OPENROUTER_API_KEY.")
    return found


def app_key(env):
    key = env.get("MANGALATE_KEY", "").strip()
    if key and len(key) < 24:
        raise SystemExit("MANGALATE_KEY precisa ter 24 caracteres ou mais.")
    if not key:
        key = secrets.token_urlsafe(32)
        print(f"Senha Mangalate gerada (cole no app): {key}", flush=True)
    return key


def prepare(env, secrets_dir=Path("/run/mangalate"), workspace=Path("/workspace"), models=Path("/app/models")):
    """Write the secret files and return the environment for both processes."""
    secrets_dir.mkdir(parents=True, exist_ok=True)
    key_file, provider_file = secrets_dir / "mangalate_key", secrets_dir / "provider_key"
    key_file.write_text(app_key(env) + "\n")
    provider_file.write_text(dump_secret(providers_from_env(env)) + "\n")
    for path in (key_file, provider_file):
        path.chmod(0o600)
    out = dict(env)
    out.update({
        "MANGALATE_PROFILE": "byok", "MANGALATE_KEY_FILE": str(key_file),
        "MANGALATE_API_KEY_FILE": str(provider_file), "MANGALATE_UPSTREAM": "http://127.0.0.1:8001",
        "MANGALATE_USE_GPU": env.get("MANGALATE_USE_GPU", "true"),
        "MANGALATE_SPEED": env.get("MANGALATE_SPEED", "quality"),
        "MANGALATE_ALLOW_ART_TEXT": env.get("MANGALATE_ALLOW_ART_TEXT", "false"),
    })
    for name in ("MANGALATE_KEY", *(k for _, k, _ in KEYS)):
        out.pop(name, None)  # the processes read the files, not the variables
    if workspace.is_dir():
        out.setdefault("MANGALATE_MEMORY_DIR", str(workspace / "mangalate" / "memoria"))
        kept = workspace / "mangalate" / "models"
        kept.mkdir(parents=True, exist_ok=True)
        if models.is_dir() and not models.is_symlink():
            for item in models.iterdir():  # models baked into the image move once
                if not (kept / item.name).exists():
                    item.rename(kept / item.name)
            if not any(models.iterdir()):
                models.rmdir()
        if not models.exists():
            models.symlink_to(kept, target_is_directory=True)
    return out


def main():
    env = prepare(dict(os.environ))
    worker = subprocess.Popen([sys.executable, str(HERE / "worker.py")], env=env)
    gateway = subprocess.Popen([sys.executable, str(HERE / "gateway.py")], env=env, cwd=HERE)
    print("Mangalate na nuvem: preparando os modelos com uma página de teste. "
          "Use o app quando aparecer \"Pronto para o app\".", flush=True)
    warmup = subprocess.Popen([sys.executable, str(HERE / "check.py"), "--url", "http://127.0.0.1:5003",
                               "--key-file", env["MANGALATE_KEY_FILE"], "--warmup", "--yes"], env=env, cwd=HERE)
    announced = False
    while True:
        for name, process in (("motor", worker), ("gateway", gateway)):
            if process.poll() is not None:
                print(f"O {name} parou (código {process.returncode}); encerrando.", flush=True)
                for other in (worker, gateway):
                    if other.poll() is None:
                        other.terminate()
                raise SystemExit(process.returncode or 1)
        if not announced and warmup.poll() is not None:
            announced = True
            if warmup.returncode == 0:
                print("Pronto para o app: endereço = URL pública da porta 5003; chave = MANGALATE_KEY.", flush=True)
            else:
                print("A página de teste falhou (veja acima); o servidor segue no ar.", flush=True)
        time.sleep(2)


if __name__ == "__main__":
    main()
