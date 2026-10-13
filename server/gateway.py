"""Small authenticated API. Only this service is exposed, never the model worker."""
import asyncio
import hmac
import io
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import numpy as np
from fastapi import FastAPI, HTTPException, Request, Response
from PIL import Image, ImageChops
from starlette.datastructures import UploadFile

MAX_BODY = 40 * 1024 * 1024
MAX_PIXELS = 32_000_000
TARGETS = {"PTB", "ENG", "ESP", "FRA", "DEU", "ITA", "RUS", "JPN", "KOR", "CHS"}
ROOT = Path(__file__).resolve().parent


def load_key():
    path = os.environ.get("MANGALATE_KEY_FILE", "/run/secrets/mangalate_key")
    try:
        key = Path(path).read_text().strip()
    except OSError as exc:
        raise RuntimeError("Arquivo MANGALATE_KEY_FILE ausente. Rode python setup.py.") from exc
    if len(key) < 24 or key.startswith("troque-"):
        raise RuntimeError("Chave Mangalate vazia ou fraca. Gere uma chave com setup.py.")
    return key


def profile_config(profile, requested):
    if profile not in {"basic", "byok"}:
        raise ValueError("Perfil deve ser basic ou byok.")
    config = json.loads((ROOT / "profiles" / f"{profile}.json").read_text())
    target = requested.get("translator", {}).get("target_lang", "PTB")
    if target not in TARGETS:
        raise ValueError("Idioma de destino não suportado.")
    config["translator"]["target_lang"] = target
    config["render"]["direction"] = "horizontal" if target not in {"JPN", "KOR", "CHS"} else "auto"
    render = requested.get("render", {})
    offset = render.get("font_size_offset", 0)
    if isinstance(offset, int) and not isinstance(offset, bool):
        config["render"]["font_size_offset"] = max(-3, min(3, offset))
    config["render"]["uppercase"] = render.get("uppercase") is True
    # The client cannot change translator/API host, file paths, upscaling or masks.
    if os.environ.get("MANGALATE_ALLOW_ART_TEXT", "false").lower() == "true":
        config["ocr"]["ignore_bubble"] = 0
    return config


def open_page(data):
    try:
        with Image.open(io.BytesIO(data)) as page:
            if page.width * page.height > MAX_PIXELS or page.width < 8 or page.height < 8:
                raise ValueError("Dimensões fora do limite.")
            page.load()
            if page.mode == "RGBA":
                white = Image.new("RGBA", page.size, "white")
                page = Image.alpha_composite(white, page)
            return page.convert("RGB")
    except (OSError, Image.DecompressionBombError, ValueError) as exc:
        raise ValueError("Imagem inválida ou grande demais (limite: 32 megapixels).") from exc


def inspect_result(original, result):
    if original.size != result.size:
        raise ValueError("O servidor mudou o enquadramento/tamanho da página.")
    # Block destructive global edits, not a substitute for bubble-level review.
    # Thumbnails bound memory/CPU for long webtoon pages.
    a, b = original.copy(), result.copy()
    a.thumbnail((1024, 4096))
    b = b.resize(a.size)
    delta = np.asarray(ImageChops.difference(a, b)).max(axis=2)
    changed = float(np.mean(delta > 24))
    if changed > 0.45:
        raise ValueError("Alteração em mais de 45% da página. Resultado retido para evitar apagar arte.")
    return {"changed_fraction": round(changed, 4), "human_review_required": True}


def create_app(key=None, upstream=None, profile=None, transport=None):
    key = key if key is not None else load_key()
    profile = profile or os.environ.get("MANGALATE_PROFILE", "basic")
    profile_config(profile, {})
    upstream = upstream or os.environ.get("MANGALATE_UPSTREAM", "http://translator:8001")
    lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(
            base_url=upstream, transport=transport,
            timeout=httpx.Timeout(1200, connect=15), trust_env=False,
        ) as client:
            app.state.client = client
            app.state.warmed = False
            yield

    app = FastAPI(title="Mangalate servidor", lifespan=lifespan, docs_url=None, redoc_url=None)

    async def worker_ready():
        if transport is not None:  # Simulated HTTP tests have no model process.
            return
        url = httpx.URL(upstream)
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(url.host, url.port or 80), timeout=3,
            )
            writer.close()
            await writer.wait_closed()
        except (OSError, TimeoutError):
            raise HTTPException(503, "Processo de tradução ainda inicializando ou parado. Aguarde e confira os logs.")

    def authorize(request):
        received = request.headers.get("x-mangalate-key", "")
        if not hmac.compare_digest(received.encode(), key.encode()):
            raise HTTPException(401, "Chave Mangalate inválida. Copie a chave do arquivo indicado no instalador.")

    @app.get("/healthz")
    async def health():
        return {"status": "gateway_running"}  # No credentials/worker internals exposed.

    @app.get("/v1/info")
    async def info(request: Request):
        authorize(request)
        return {"edition": profile, "translator": profile_config(profile, {})["translator"]["translator"],
                "warmed": app.state.warmed, "review_required": True}

    @app.post("/queue-size")
    async def queue(request: Request):
        authorize(request)
        await worker_ready()
        try:
            response = await app.state.client.post("/queue-size", timeout=20)
            response.raise_for_status()
            count = response.json()
            if not isinstance(count, int):
                raise ValueError()
            return count + int(lock.locked())
        except (httpx.HTTPError, ValueError):
            raise HTTPException(503, "Motor ainda inicializando ou parado. Confira docker compose logs.")

    @app.post("/translate/with-form/image")
    async def translate(request: Request):
        authorize(request)
        if lock.locked():
            raise HTTPException(429, "Uma página já está sendo traduzida. Aguarde e tente novamente.",
                                headers={"Retry-After": "5"})
        async with lock:
            return await process(request)

    async def process(request):
        await worker_ready()
        # Bound body before multipart parsing, even if Content-Length is missing.
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_BODY:
                raise HTTPException(413, "Página maior que 40 MB.")
        request._body = bytes(raw)
        try:
            async with request.form(max_files=1, max_fields=1, max_part_size=MAX_BODY) as form:
                upload = form.get("image")
                if not isinstance(upload, UploadFile):
                    raise ValueError("Envie o campo image.")
                data = await upload.read()
                requested = json.loads(str(form.get("config", "{}")))
                if not isinstance(requested, dict):
                    raise ValueError("Configuração deve ser um objeto JSON.")
                config = profile_config(profile, requested)
                original = await asyncio.to_thread(open_page, data)
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(422, str(exc))
        try:
            result = await app.state.client.post(
                "/translate/with-form/image",
                files={"image": ("page.png", data, "application/octet-stream")},
                data={"config": json.dumps(config)},
            )
        except httpx.TimeoutException:
            raise HTTPException(504, "O motor demorou demais. Prepare os modelos com check.py --warmup.")
        except httpx.HTTPError:
            raise HTTPException(503, "Motor indisponível. Confira os logs locais do servidor.")
        if result.status_code != 200:
            # Never echo upstream errors containing provider keys, prompt text or paths.
            raise HTTPException(502, "Motor recusou a tradução. No BYOK, confira chave, modelo, saldo e logs.")
        try:
            translated = await asyncio.to_thread(open_page, result.content)
            metrics = await asyncio.to_thread(inspect_result, original, translated)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        app.state.warmed = True
        png = io.BytesIO()
        translated.save(png, "PNG")
        return Response(png.getvalue(), media_type="image/png", headers={
            "X-Mangalate-Review": "required",
            "X-Mangalate-Changed": str(metrics["changed_fraction"]),
            "Cache-Control": "no-store",
        })

    return app


if __name__ == "__main__":
    import uvicorn
    app = create_app()  # Read root-owned Docker secret before dropping privileges.
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        os.setgid(65532)
        os.setuid(65532)
    uvicorn.run(app, host="0.0.0.0", port=5003, log_level="warning")
