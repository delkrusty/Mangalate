"""Rebuild and restart the Mangalate server after `git pull`: py rebuild.py

Builds the images with plain `docker build` instead of `docker compose
--build`. Recent Docker Desktop versions build Compose projects through
"bake", which can fail with only "failed to execute bake: exit status 1";
Compose then keeps running the OLD images, so updates silently do nothing.
Keys, settings (.env), volumes and downloaded models are kept.
"""
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IMAGES = {
    "cpu": ("cpu", "mangalate-translator-cpu:local", "translator-cpu"),
    "gpu": ("gpu", "mangalate-translator-gpu:local", "translator-gpu"),
    "amd-rocm": ("rocm", "mangalate-translator-amd:local", "translator-amd"),
}
# Files whose copy inside the running server must equal the one in this folder.
CHECKED = {"colab/batch.py": "/mangalate/batch.py", "engine_compat.py": "/mangalate/engine_compat.py",
           "providers.py": "/mangalate/providers.py", "seams.py": "/mangalate/seams.py",
           "quality.py": "/mangalate/quality.py"}


def hardware_from_env(root=ROOT):
    env = root / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("MANGALATE_HARDWARE="):
                value = line.split("=", 1)[1].strip()
                if value in IMAGES:
                    return value
    return None


def commands(hardware):
    target, image, service = IMAGES[hardware]
    return [
        ["docker", "build", "-f", "Dockerfile.worker", "--target", target, "-t", image, "."],
        ["docker", "build", "-f", "Dockerfile.gateway", "-t", "mangalate-gateway:local", "."],
        ["docker", "compose", "--profile", hardware, "up", "-d", "--no-build", "--force-recreate"],
    ], service


def rebuild(hardware, run=subprocess.run):
    steps, service = commands(hardware)
    for step in steps:
        print("→", " ".join(step), flush=True)
        run(step, cwd=ROOT, check=True)
    local = {inside: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path, inside in CHECKED.items()}
    check = run(["docker", "compose", "--profile", hardware, "exec", "-T", service, "sha256sum", *local],
                cwd=ROOT, capture_output=True, text=True)
    running = {}
    for line in (check.stdout or "").splitlines():
        parts = line.split()
        if len(parts) == 2:
            running[parts[1]] = parts[0]
    stale = [inside for inside, digest in local.items() if running.get(inside) != digest]
    if check.returncode != 0 or stale:
        raise SystemExit("O servidor reiniciou, mas NÃO está com a versão desta pasta (" + ", ".join(stale or ["sem resposta"])
                         + "). Rode git pull e py rebuild.py de novo; se repetir, mande este texto no chat.")
    print("Servidor atualizado e rodando a versão nova.")


def main():
    hardware = hardware_from_env() or ("gpu" if "--gpu" in sys.argv else "cpu")
    rebuild(hardware)


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError:
        raise SystemExit("Docker não encontrado. Abra o Docker Desktop e tente de novo.")
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"Falhou em: {' '.join(exc.cmd)}. Confira se o Docker Desktop está aberto e se há espaço em disco.")
