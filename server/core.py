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


def graphics_card():
    """True when PyTorch reaches the card; otherwise say so and use the processor."""
    try:
        import torch
        if torch.cuda.is_available():
            print(f"Placa de vídeo em uso: {torch.cuda.get_device_name(0)}", flush=True)
            return True
    except Exception as exc:
        print(f"Placa de vídeo não respondeu ({type(exc).__name__}).", flush=True)
    print("Placa de vídeo não encontrada pelo servidor; usando o processador.", flush=True)
    return False


def create_core(engine=None, config_factory=None):
    @asynccontextmanager
    async def lifespan(app):
        nonlocal engine, config_factory
        if engine is None:
            from engine_compat import apply_compatibility
            apply_compatibility()
            from manga_translator import MangaTranslator, Config
            gpu = os.environ.get("MANGALATE_USE_GPU", "false").lower() == "true"
            if gpu:
                gpu = graphics_card()
            limited = gpu and os.environ.get("MANGALATE_ACCELERATOR") == "amd-rocm"
            engine = MangaTranslator({"use_gpu": gpu and not limited,
                                     "use_gpu_limited": limited, "verbose": False,
                                     "kernel_size": 3})
            config_factory = Config
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    from speed import pages_at_once
    # Two pages at once: one waits for the AI while the other is detected or cleaned.
    lock = asyncio.Semaphore(pages_at_once())

    @app.get("/healthz")
    async def health():
        return {"status": "engine_ready"}

    @app.post("/queue-size")
    async def queue():
        # Gateway adds its own admission lock; no second queue in this engine.
        return 0

    from seams import SeamCache, Strip, finish
    seam_cache = SeamCache()

    @app.post("/translate/with-form/image")
    async def translate(image: UploadFile = File(...), config: str = Form("{}"),
                        above: UploadFile | None = File(None), below: UploadFile | None = File(None),
                        work: str = Form("")):
        if lock.locked():
            raise HTTPException(429, "Engine busy")
        async with lock:
            try:
                data = await image.read(MAX_BODY + 1)
                if len(data) > MAX_BODY:
                    raise ValueError("Page too large")
                original = open_page(data)
                neighbours = []
                for upload in (above, below):
                    extra = await upload.read(MAX_BODY + 1) if upload is not None else b""
                    if len(extra) > MAX_BODY:
                        raise ValueError("Neighbour page too large")
                    neighbours.append(open_page(extra) if extra else None)
                strip = Strip(original, *neighbours)
                requested = json.loads(config)
                if not isinstance(requested, dict):
                    raise ValueError("Config must be an object")
                parsed = config_factory(**requested) if config_factory else requested
            except (ValueError, TypeError, AttributeError):
                raise HTTPException(422, "Invalid page or configuration")
            try:
                from engine_compat import set_page_context, set_page_rows, take_learned_terms
                from memory import default_memory, parse_work, remember
                set_page_rows(strip.top, strip.bottom)
                # Glossary and previous pages of the same work, when the app names it.
                page_work = parse_work(work)
                set_page_context(default_memory().context(page_work["obra"], page_work["capitulo"],
                                                          page_work["pagina"]) if page_work else None)
                ctx = await engine.translate(strip.image, parsed)
                try:
                    remember(default_memory(), page_work, getattr(ctx, "text_regions", None), take_learned_terms())
                except Exception as exc:  # the page is done; memory is a bonus
                    print(f"Memória da obra: {type(exc).__name__}", flush=True)
                result = finish(strip, ctx.result, getattr(ctx, "text_regions", None) if strip.stitched else None,
                                seam_cache, config)
                from speed import summary
                if getattr(ctx, "mangalate_timings", None):
                    print(f"Tempos: {summary(ctx.mangalate_timings)}", flush=True)
                if strip.stitched:
                    print(f"Seams: above={strip.above is not None} below={strip.below is not None}", flush=True)
                output = io.BytesIO()
                result.save(output, "PNG")
                return Response(output.getvalue(), media_type="image/png")
            except Exception as exc:
                if type(exc).__name__ == "AllProvidersResting":
                    print(f"Translation paused: {exc}", flush=True)
                    raise HTTPException(424, str(exc))
                # Never propagate provider bodies, URLs or credentials to logs/phone.
                print(f"Translation failed: {type(exc).__name__}", flush=True)
                for frame in traceback.extract_tb(exc.__traceback__)[-8:]:
                    print(f"  {frame.filename}:{frame.lineno} in {frame.name}", flush=True)
                raise HTTPException(502, "Translation engine failed")

    return app


app = create_core()
