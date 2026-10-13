"""Load BYOK secret inside the worker, never from the phone or command arguments."""
import os
import sys
from pathlib import Path

if os.environ.get("MANGALATE_PROFILE", "basic") == "byok":
    path = Path(os.environ.get("MANGALATE_API_KEY_FILE", "/run/secrets/provider_key"))
    key = path.read_text().strip()
    if not key:
        raise SystemExit("Chave BYOK vazia. Rode novamente python setup.py e escolha byok.")
    os.environ["CUSTOM_OPENAI_API_KEY"] = key
if len(sys.argv) > 1:
    os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
args = [sys.executable, "server/main.py", "--start-instance", "--host=0.0.0.0", "--port=8001"]
if os.environ.get("MANGALATE_USE_GPU", "false").lower() == "true":
    args.append("--use-gpu")
os.execv(sys.executable, args)
