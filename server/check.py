"""Local diagnostic with optional, explicit real translation (BYOK may charge)."""
import argparse
import io
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:5003")
    parser.add_argument("--key-file", type=Path, default=ROOT / "secrets/mangalate_key.txt")
    parser.add_argument("--warmup", action="store_true")
    parser.add_argument("--yes", action="store_true", help="não perguntar antes de usar a API (servidor na nuvem)")
    args = parser.parse_args()
    key = args.key_file.read_text().strip()
    headers = {"X-Mangalate-Key": key}
    def call(path, data=None, more=None):
        req = urllib.request.Request(args.url.rstrip("/") + path, data=data, headers=headers | (more or {}))
        return urllib.request.urlopen(req, timeout=1200)
    with call("/v1/info") as response:
        info = json.load(response)
    print("Perfil:", info["edition"], "| motor:", info["translator"])
    deadline = time.monotonic() + (600 if args.yes else 120)
    while True:
        try:
            with call("/queue-size", b"") as response:
                print("Conexão com o motor:", response.read().decode(), "página(s) na fila")
            break
        except urllib.error.HTTPError as exc:
            if exc.code != 503 or time.monotonic() > deadline:
                raise
            print("Esperando inicialização do motor…")
            time.sleep(3)
    if not args.warmup:
        print("A conexão não prova que os modelos já foram baixados. Execute --warmup para traduzir uma página sintética.")
        return
    if info["edition"] == "byok" and not args.yes and input("O teste envia texto Hello à sua API e pode consumir saldo. Continuar [s/N]? ").lower() != "s":
        return
    from PIL import Image, ImageDraw, ImageFont
    page = Image.new("RGB", (900, 600), "white")
    draw = ImageDraw.Draw(page)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 55)
    except OSError:
        try:
            font = ImageFont.truetype(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/arial.ttf"), 55)
        except OSError:
            font = ImageFont.load_default(size=55)
    draw.ellipse((70, 60, 830, 540), outline="black", width=6)
    draw.text((220, 230), "Hello world!", fill="black", font=font)
    buffer = io.BytesIO()
    page.save(buffer, "PNG")
    boundary = "mangalate-diagnostic"
    folder = ROOT / "review"
    folder.mkdir(exist_ok=True)
    (folder / "teste-original.png").write_bytes(buffer.getvalue())
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"config\"\r\n\r\n{{}}\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"test.png\"\r\nContent-Type: image/png\r\n\r\n"
    ).encode() + buffer.getvalue() + f"\r\n--{boundary}--\r\n".encode()
    print("Preparando modelos e traduzindo. A primeira execução pode ser longa; não feche o terminal.")
    with call("/translate/with-form/image", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}) as response:
        result = response.read()
    (folder / "teste-traduzido.png").write_bytes(result)
    print("Abra review/teste-traduzido.png e confira se Hello world! realmente virou português.")
    print("HTTP 200 não garante tradução correta: essa conferência visual é obrigatória.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, urllib.error.HTTPError, ValueError) as exc:
        raise SystemExit(f"Teste falhou: {exc}. Confira chave, Docker e docker compose logs --tail=80.")
