"""Load BYOK secret inside the worker, never from the phone or command arguments."""
import os
import sys
from pathlib import Path
os.environ["PYTHONUNBUFFERED"] = "1"

if os.environ.get("MANGALATE_PROFILE", "basic") == "byok":
    path = Path(os.environ.get("MANGALATE_API_KEY_FILE", "/run/secrets/provider_key"))
    key = path.read_text().strip()
    if not key:
        raise SystemExit("Chave BYOK vazia. Rode novamente python setup.py e escolha byok.")
    if key.startswith("{"):
        # Several providers (setup.py menu): the first one initializes the engine;
        # engine_compat rotates between all of them, reading this same file.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from providers import parse_secret
        try:
            first = parse_secret(key)[0]
        except ValueError as exc:
            raise SystemExit(f"Lista de provedores inválida: {exc} Rode python setup.py de novo.")
        key = first["key"]
        os.environ["CUSTOM_OPENAI_API_BASE"] = first["base"]
        os.environ["CUSTOM_OPENAI_MODEL"] = first["model"]
    os.environ["CUSTOM_OPENAI_API_KEY"] = key
if len(sys.argv) > 1:
    os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
args = [sys.executable, "-m", "uvicorn", "core:app", "--host=0.0.0.0", "--port=8001", "--app-dir=/mangalate"]
os.execv(sys.executable, args)
