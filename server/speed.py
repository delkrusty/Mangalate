"""Page speed: time spent in each step, and cleaning while the AI translates.

The engine runs the steps of a page one after the other: detection, OCR,
grouping, translation, mask, cleaning (inpainting) and lettering.  The
translation is a network call that leaves the CPU idle for seconds, while the
mask and the cleaning do not depend on the translated text.  So, right before
the translation, the mask and the cleaning start in a worker thread; when the
AI answers, the page is usually already clean.

The cleaning is only reused if the translation kept exactly the same regions.
When the engine drops a region after translating (an answer identical to the
original, a number), its text must stay on the page, so the mask and the
cleaning are computed again, as before.

MANGALATE_OVERLAP=false turns the overlap off (for comparison).
"""
import asyncio
import os
import time
from types import SimpleNamespace

STEPS = {
    "_run_detection": "deteccao",
    "_run_ocr": "leitura",
    "_run_textline_merge": "agrupamento",
    "_run_text_translation": "traducao",
    "_run_mask_refinement": "mascara",
    "_run_inpainting": "limpeza",
    "_run_text_rendering": "texto",
}


def overlap_enabled():
    return os.environ.get("MANGALATE_OVERLAP", "true").lower() != "false"


def timed(name, original):
    async def run(self, config, ctx):
        started = time.monotonic()
        try:
            return await original(self, config, ctx)
        finally:
            timings = getattr(ctx, "mangalate_timings", None)
            if timings is None:
                timings = ctx.mangalate_timings = {}
            timings[name] = round(timings.get(name, 0) + time.monotonic() - started, 2)
    return run


def prepare_cleaning(original_translate):
    """Start mask + cleaning in a thread, then translate."""
    async def translate(self, config, ctx):
        regions = list(ctx.text_regions or [])
        task = None
        if regions and overlap_enabled() and getattr(ctx, "mask", None) is None:
            snapshot = SimpleNamespace(text_regions=list(regions), img_rgb=ctx.img_rgb,
                                       mask_raw=ctx.mask_raw, mask=None)

            async def clean():
                started = time.monotonic()
                snapshot.mask = await self._run_mask_refinement(config, snapshot)
                inpainted = await self._run_inpainting(config, snapshot)
                return snapshot.mask, inpainted, time.monotonic() - started

            # A separate event loop in a worker thread: torch releases the GIL, so the
            # network wait of the translation goes on in parallel.
            task = asyncio.ensure_future(asyncio.to_thread(asyncio.run, clean()))
            ctx.mangalate_prepared = (task, [id(r) for r in regions])
        try:
            return await original_translate(self, config, ctx)
        except BaseException:
            if task is not None:
                # Never leave the cleaner running into the next page.
                await asyncio.gather(task, return_exceptions=True)
                ctx.mangalate_prepared = None
            raise
    return translate


def reuse_mask(original_refine):
    async def refine(self, config, ctx):
        prepared = getattr(ctx, "mangalate_prepared", None)
        if not prepared:
            return await original_refine(self, config, ctx)
        task, ids = prepared
        ctx.mangalate_prepared = None
        try:
            mask, inpainted, seconds = await task
        except Exception as exc:
            print(f"Limpeza antecipada falhou ({type(exc).__name__}); refazendo na ordem normal.", flush=True)
            return await original_refine(self, config, ctx)
        if [id(r) for r in ctx.text_regions or []] != ids:
            print("Limpeza antecipada descartada: a tradução removeu regiões.", flush=True)
            return await original_refine(self, config, ctx)
        ctx.mangalate_ready = (mask, inpainted)
        timings = getattr(ctx, "mangalate_timings", None)
        if timings is not None:
            timings["limpeza_antecipada"] = round(seconds, 2)
        return mask
    return refine


def reuse_cleaning(original_inpaint):
    async def inpaint(self, config, ctx):
        ready = getattr(ctx, "mangalate_ready", None)
        ctx.mangalate_ready = None
        if ready is not None and ready[0] is ctx.mask:
            return ready[1]
        return await original_inpaint(self, config, ctx)
    return inpaint


def install(MangaTranslator):
    """Wrap the steps; call after the other Mangalate wrappers."""
    if getattr(MangaTranslator, "_mangalate_speed_applied", False):
        return
    for method, name in STEPS.items():
        setattr(MangaTranslator, method, timed(name, getattr(MangaTranslator, method)))
    MangaTranslator._run_text_translation = prepare_cleaning(MangaTranslator._run_text_translation)
    MangaTranslator._run_mask_refinement = reuse_mask(MangaTranslator._run_mask_refinement)
    MangaTranslator._run_inpainting = reuse_cleaning(MangaTranslator._run_inpainting)
    MangaTranslator._mangalate_speed_applied = True


def summary(timings):
    if not timings:
        return ""
    return " ".join(f"{k}={v}s" for k, v in timings.items())
