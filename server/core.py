"""Private Docker engine: direct calls, no pickle RPC or secondary worker port."""
import asyncio
import io
import json
import os
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from gateway import MAX_BODY, open_page


def create_core(engine=None, config_factory=None):
    @asynccontextmanager
    async def lifespan(app):
        nonlocal engine, config_factory
        if engine is None:
            from manga_translator import MangaTranslator, Config
            gpu = os.environ.get("MANGALATE_USE_GPU", "false").lower() == "true"
            limited = gpu and os.environ.get("MANGALATE_ACCELERATOR") == "amd-rocm"
            engine = MangaTranslator({"use_gpu": gpu and not limited,
                                     "use_gpu_limited": limited, "verbose": False,
                                     "kernel_size": 3})
            config_factory = Config
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    lock = asyncio.Lock()

    @app.get("/healthz")
    async def health():
        return {"status": "engine_ready"}

    @app.post("/queue-size")
    async def queue():
        # Gateway adds its own admission lock; no second queue in this engine.
        return 0

    @app.post("/translate/with-form/image")
    async def translate(image: UploadFile = File(...), config: str = Form("{}")):
        if lock.locked():
            raise HTTPException(429, "Engine busy")
        async with lock:
            try:
                data = await image.read(MAX_BODY + 1)
                if len(data) > MAX_BODY:
                    raise ValueError("Page too large")
                original = open_page(data)
                requested = json.loads(config)
                if not isinstance(requested, dict):
                    raise ValueError("Config must be an object")
                parsed = config_factory(**requested) if config_factory else requested
            except (ValueError, TypeError, AttributeError):
                raise HTTPException(422, "Invalid page or configuration")
            try:
                ctx = await engine.translate(original, parsed)
                result = ctx.result.convert("RGB")
                output = io.BytesIO()
                result.save(output, "PNG")
                return Response(output.getvalue(), media_type="image/png")
            except Exception as exc:
                # Never propagate provider bodies, URLs or credentials to logs/phone.
                print(f"Translation failed: {type(exc).__name__}", flush=True)
                for frame in traceback.extract_tb(exc.__traceback__)[-8:]:
                    print(f"  {frame.filename}:{frame.lineno} in {frame.name}", flush=True)
                raise HTTPException(502, "Translation engine failed")

    return app


app = create_core()
