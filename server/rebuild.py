"""Rebuild and restart the Mangalate server after `git pull`: py rebuild.py

Builds the images with plain `docker build` instead of `docker compose
--build`. Recent Docker Desktop versions build Compose projects through
"bake", which can fail with only "failed to execute bake: exit status 1";
Compose then keeps running the OLD images, so updates silently do nothing.
Keys, settings (.env), volumes and downloaded models are kept.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IMAGES = {
    "cpu": ("cpu", "mangalate-translator-cpu:local", "translator-cpu"),
    "gpu": ("gpu", "mangalate-translator-gpu:local", "translator-gpu"),
    "amd-rocm": ("rocm", "mangalate-translator-amd:local", "translator-amd"),
}
MARKER = "translate_with_patience"  # present in batch.py since 0.5.3


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
    check = run(["docker", "compose", "--profile", hardware, "exec", "-T", service,
                 "grep", "-c", MARKER, "/mangalate/batch.py"],
                cwd=ROOT, capture_output=True, text=True)
    if check.returncode != 0 or not check.stdout.strip().isdigit() or int(check.stdout.strip()) == 0:
        raise SystemExit("O servidor reiniciou, mas não está rodando a versão nova. Mande este texto no chat.")
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
