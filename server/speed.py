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

Most text sits in plain bubbles. There the cleaning does not need the
inpainting model: the letters are covered with the bubble's own colour, taken
from the pixels around them. The model runs only for text over art, and only
on the part of the page around it. MANGALATE_FLAT_FILL=false turns this off.

Two pages can be in the engine at once (MANGALATE_PAGES_AT_ONCE, default 2).
Their heavy steps (detection, reading, cleaning, lettering) take turns in a
worker thread, so while one page waits for the AI the other uses the
processor or the card, and the event loop stays free to receive the answer.
"""
import asyncio
import os
import threading
import time
from types import SimpleNamespace

import numpy as np

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


HEAVY_STEPS = ("_run_detection", "_run_ocr", "_run_textline_merge", "_run_mask_refinement",
               "_run_inpainting", "_run_text_rendering")
_HEAVY = threading.Lock()


def pages_at_once():
    try:
        return max(1, min(4, int(os.environ.get("MANGALATE_PAGES_AT_ONCE", "2"))))
    except ValueError:
        return 2


def take_turns(original):
    """Run a heavy step in a worker thread, one page at a time."""
    async def run(self, config, ctx):
        if pages_at_once() == 1:
            return await original(self, config, ctx)

        def work():
            with _HEAVY:
                return asyncio.run(original(self, config, ctx))
        return await asyncio.to_thread(work)
    return run


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
                                       mask_raw=ctx.mask_raw, mask=None,
                                       mangalate_drawn=getattr(ctx, "mangalate_drawn", None))

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


def flat_fill_enabled():
    return os.environ.get("MANGALATE_FLAT_FILL", "true").lower() != "false"


FLAT_SPREAD = 10    # max distance (0-255) of 95% of the ring from its median colour
GROUP = 15          # letters this close (px) belong to the same blob of text
RING = 6            # width (px) of the border read around a blob
EDGE = 2            # width (px) of the ring touching the letters; it must be flat on its own
FLAT_SHARE = 0.8    # min share of the whole ring in the edge colour when the outline crosses the ring
CROP_PADDING = 96   # context (px) given to the model around text over art
MAX_CROP_SHARE = 0.6


def split_flat(image, mask, ignore=None):
    """Fill blobs of text that sit on a flat colour; return (page, mask left for the model).

    ``ignore`` marks pixels left out of the ring that is read around a blob: a drawing kept
    whole next to the text (quality.drawn_marks) does not make the bubble look textured.
    """
    import cv2
    text = mask > 0
    blobs = cv2.dilate(text.astype(np.uint8), np.ones((GROUP, GROUP), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(blobs, connectivity=8)
    page = image.copy()
    left = mask.copy()
    ring_kernel = np.ones((2 * RING + 1, 2 * RING + 1), np.uint8)
    height, width = mask.shape[:2]
    for label in range(1, count):
        x, y, w, h = stats[label, :4]
        x0, y0 = max(0, x - RING - 1), max(0, y - RING - 1)
        x1, y1 = min(width, x + w + RING + 1), min(height, y + h + RING + 1)
        blob = labels[y0:y1, x0:x1] == label
        letters = blob & text[y0:y1, x0:x1]
        ring = cv2.dilate(letters.astype(np.uint8), ring_kernel).astype(bool) & ~text[y0:y1, x0:x1]
        if ignore is not None:
            ring &= ~ignore[y0:y1, x0:x1]
        pixels = image[y0:y1, x0:x1][ring]
        if len(pixels) < 4 * RING:
            continue
        colour = np.median(pixels, axis=0)
        spread = np.percentile(np.abs(pixels.astype(np.int16) - colour).max(axis=1), 95)
        if spread > FLAT_SPREAD:
            # A bubble outline near the text spoils the ring without touching the letters.
            # Still flat if the band next to the letters is flat and holds most of the ring.
            edge = cv2.dilate(letters.astype(np.uint8), np.ones((2 * EDGE + 1, 2 * EDGE + 1), np.uint8)).astype(bool)
            near = image[y0:y1, x0:x1][edge & ring]
            if len(near) < 4 * RING:
                continue
            colour = np.median(near, axis=0)
            if np.percentile(np.abs(near.astype(np.int16) - colour).max(axis=1), 95) > FLAT_SPREAD:
                continue
            if (np.abs(pixels.astype(np.int16) - colour).max(axis=1) <= FLAT_SPREAD).mean() < FLAT_SHARE:
                continue
        page[y0:y1, x0:x1][letters] = colour.round().astype(image.dtype)
        left[y0:y1, x0:x1][letters] = 0
    return page, left


def flat_first(original_inpaint):
    async def inpaint(self, config, ctx):
        image, mask = getattr(ctx, "img_rgb", None), getattr(ctx, "mask", None)
        if (not flat_fill_enabled() or not isinstance(image, np.ndarray) or not isinstance(mask, np.ndarray)
                or image.ndim != 3 or mask.shape[:2] != image.shape[:2]):
            return await original_inpaint(self, config, ctx)
        try:
            ignore = None
            drawn = getattr(ctx, "mangalate_drawn", None)
            if drawn:
                from quality import drawn_marks
                ignore = drawn_marks(image, drawn)
            page, left = split_flat(image, mask, ignore)
        except Exception as exc:
            print(f"Limpeza lisa falhou ({type(exc).__name__}); usando o modelo.", flush=True)
            return await original_inpaint(self, config, ctx)
        ys, xs = np.nonzero(left)
        if not len(ys):
            return page
        height, width = mask.shape[:2]
        x0, x1 = max(0, xs.min() - CROP_PADDING), min(width, xs.max() + 1 + CROP_PADDING)
        y0, y1 = max(0, ys.min() - CROP_PADDING), min(height, ys.max() + 1 + CROP_PADDING)
        if (x1 - x0) * (y1 - y0) > MAX_CROP_SHARE * width * height:
            x0, y0, x1, y1 = 0, 0, width, height
        # The same fields the early cleaning hands to the engine.
        part = SimpleNamespace(text_regions=getattr(ctx, "text_regions", None), mask_raw=getattr(ctx, "mask_raw", None),
                               img_rgb=np.ascontiguousarray(page[y0:y1, x0:x1]),
                               mask=np.ascontiguousarray(left[y0:y1, x0:x1]))
        cleaned = np.asarray(await original_inpaint(self, config, part))
        if cleaned.shape[:2] != part.mask.shape[:2]:
            return await original_inpaint(self, config, ctx)
        area = page[y0:y1, x0:x1]
        area[part.mask > 0] = cleaned[part.mask > 0]
        return page
    return inpaint


def install(MangaTranslator):
    """Wrap the steps; call after the other Mangalate wrappers."""
    if getattr(MangaTranslator, "_mangalate_speed_applied", False):
        return
    MangaTranslator._run_inpainting = flat_first(MangaTranslator._run_inpainting)
    for method, name in STEPS.items():
        setattr(MangaTranslator, method, timed(name, getattr(MangaTranslator, method)))
    for method in HEAVY_STEPS:
        setattr(MangaTranslator, method, take_turns(getattr(MangaTranslator, method)))
    MangaTranslator._run_text_translation = prepare_cleaning(MangaTranslator._run_text_translation)
    MangaTranslator._run_mask_refinement = reuse_mask(MangaTranslator._run_mask_refinement)
    MangaTranslator._run_inpainting = reuse_cleaning(MangaTranslator._run_inpainting)
    MangaTranslator._mangalate_speed_applied = True


def summary(timings):
    if not timings:
        return ""
    return " ".join(f"{k}={v}s" for k, v in timings.items())
