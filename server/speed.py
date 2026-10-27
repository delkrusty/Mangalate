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
                                       mangalate_drawn=getattr(ctx, "mangalate_drawn", None),
                                       mangalate_preserved=getattr(ctx, "mangalate_preserved", None))

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
MARK_SIZE = 40      # max size (px) of a small drawing the text mask cut into, inside a plain bubble...
MARK_CUT = 0.25     # ...with at least this share of its ink under the mask...
MARK_CLEAR = 3      # ...and no other ink this close (px) outside the mask...
MARK_SPECK = 8      # ...counting only pieces of ink of at least this many px
DUST_SIZE = 6       # a speck of dust of the scan is at most this many px...
DUST_SHARE = 0.04   # ...and the specks are at most this share of the band beside the letters (screentone has more)
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
        distance = np.abs(pixels.astype(np.int16) - colour).max(axis=1)
        spread = np.percentile(distance, 95)
        marks = None
        if spread > FLAT_SPREAD and (distance <= FLAT_SPREAD).mean() >= FLAT_SHARE:
            # A small drawing the mask cut into (One Piece 1161 p8: an anger vein beside the
            # last line) spoils the ring on its own: the model then painted a ghost of the letters
            # over the bubble.  Without that drawing the ring is flat: the bubble is filled, and
            # the rest of the drawing goes with the letters instead of being left cut in half.
            wx0, wy0 = max(0, x - MARK_SIZE - 1), max(0, y - MARK_SIZE - 1)
            wx1, wy1 = min(width, x + w + MARK_SIZE + 1), min(height, y + h + MARK_SIZE + 1)
            found = cut_marks(image[wy0:wy1, wx0:wx1], text[wy0:wy1, wx0:wx1],
                              (labels[wy0:wy1, wx0:wx1] == label) & text[wy0:wy1, wx0:wx1], colour,
                              None if ignore is None else ignore[wy0:wy1, wx0:wx1])
            if found.any():
                found = cv2.dilate(found.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
                rest = image[y0:y1, x0:x1][ring & ~found[y0 - wy0:y1 - wy0, x0 - wx0:x1 - wx0]]
                if (len(rest) >= 4 * RING
                        and np.percentile(np.abs(rest.astype(np.int16) - colour).max(axis=1), 95) <= FLAT_SPREAD):
                    marks = (wx0, wy0, found)
                    spread = 0
        if spread > FLAT_SPREAD:
            # A bubble outline near the text spoils the ring without touching the letters.
            # Still flat if the band next to the letters is flat and holds most of the ring.
            edge = cv2.dilate(letters.astype(np.uint8), np.ones((2 * EDGE + 1, 2 * EDGE + 1), np.uint8)).astype(bool)
            near = image[y0:y1, x0:x1][edge & ring]
            if len(near) < 4 * RING:
                continue
            colour = np.median(near, axis=0)
            if np.percentile(np.abs(near.astype(np.int16) - colour).max(axis=1), 95) > FLAT_SPREAD:
                # Specks of dust of the scan beside the letters (Grand Blue 106 p22) spoil the band on
                # their own; screentone has many more.
                dust = specks(image[y0:y1, x0:x1], text[y0:y1, x0:x1], colour) & edge & ring
                if dust.sum() > DUST_SHARE * (edge & ring).sum():
                    continue
                near = image[y0:y1, x0:x1][edge & ring & ~dust]
                if np.percentile(np.abs(near.astype(np.int16) - colour).max(axis=1), 95) > FLAT_SPREAD:
                    continue
            if (np.abs(pixels.astype(np.int16) - colour).max(axis=1) <= FLAT_SPREAD).mean() < FLAT_SHARE:
                continue
        page[y0:y1, x0:x1][letters] = colour.round().astype(image.dtype)
        left[y0:y1, x0:x1][letters] = 0
        if marks is not None:
            wx0, wy0, found = marks
            fh, fw = found.shape
            page[wy0:wy0 + fh, wx0:wx0 + fw][found] = colour.round().astype(image.dtype)
    return page, left


def paint_halos(image, mask, regions, raw):
    """Speech over the drawing with a light halo ("sobre_arte"): only its letters and halo go to
    the model (quality.halo_paint), which draws the art back under them; the rest of its mask is
    left out.  Painted flat with the halo, the old block stayed as a white patch much bigger than
    the translation; the new letters get their own halo when drawn (quality.halo_cloud).
    """
    import cv2
    over = [r for r in regions or [] if (getattr(r, "mangalate_background", None) or {}).get("sobre_arte")]
    if not over or raw is None:
        return image, mask
    from quality import HALO_EDGE_PX, halo_paint
    raw = np.asarray(raw)
    if raw.shape[:2] != mask.shape[:2]:
        raw = cv2.resize(raw, (mask.shape[1], mask.shape[0]), interpolation=cv2.INTER_NEAREST)
    page, left = image.copy(), mask.copy()
    for region in over:
        paint, colour = halo_paint(image, raw, region.lines)
        if colour is None:
            continue
        x0, y0, x1, y1 = (int(v) for v in region.xyxy)
        pad = int(max(8, getattr(region, "font_size", 0) or 0))
        zone = np.zeros(mask.shape[:2], bool)
        zone[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad] = True
        for other in regions:  # the cleaning of a bubble next to it stays
            if other is not region:
                ox0, oy0, ox1, oy1 = (int(v) for v in other.xyxy)
                zone[max(0, oy0):oy1, max(0, ox0):ox1] = False
        # Not limited to the engine's mask: the detector cut the tops of a first line off it, and
        # they were left as a ghost of the English.  The paint is letters and halo only.
        paint &= zone
        region.mangalate_halo = tuple(int(c) for c in np.asarray(colour).round())
        region.mangalate_halo_area = paint  # the room of the translation (engine_compat.bubble_layout)
        page[paint] = region.mangalate_halo  # what stays if the model is not run
        left[zone] = 0
        # With the halo's soft rim: left out, its white spread into the art the model drew back.
        edge = np.ones((2 * HALO_EDGE_PX + 1, 2 * HALO_EDGE_PX + 1), np.uint8)
        left[(cv2.dilate(paint.astype(np.uint8), edge) > 0) & zone] = 255
    return page, left


def specks(image, text, colour):
    """Pieces of ink of at most DUST_SIZE px outside ``text``: dust of the scan, or screentone dots."""
    import cv2
    off = (np.abs(image.astype(np.int16) - colour).max(axis=2) > FLAT_SPREAD) & ~text
    count, labels, stats, _ = cv2.connectedComponentsWithStats(off.astype(np.uint8), connectivity=8)
    small = stats[:, cv2.CC_STAT_AREA] <= DUST_SIZE
    small[0] = False
    return small[labels]


def cut_marks(image, text, letters, colour, ignore=None):
    """Small drawings in a plain bubble that the mask of ``letters`` cut into: the part left out.

    All arguments are crops of the same window around one blob of text.  A piece of ink up to
    MARK_SIZE px that stays inside the window and lies at least MARK_CUT under the letters' mask
    counts; the bubble outline, a tail or the art beyond the bubble are larger and reach the
    edge of the window, and a drawing the mask only grazes (a sound effect beside the bubble,
    Grand Blue 102 p34) stays.  The part left out is never larger than the letters being cleaned:
    a speck of mask on a letter of the art does not take the letter.  The same rule takes the
    rest of a letter the mask cut (the top of a word, the stroke of a "!").  A mark with other
    ink within MARK_CLEAR px that is not taken too is a letter of a word kept as drawn (the small
    print of a form, Grand Blue 102 p4): then nothing is taken.
    """
    import cv2
    ink = np.abs(image.astype(np.int16) - colour).max(axis=2) > FLAT_SPREAD
    if ignore is not None:
        ink &= ~ignore
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    if count <= 1:
        return np.zeros(ink.shape, bool)
    height, width = ink.shape
    x, y, w, h, area = stats.T
    under = np.bincount(labels[letters], minlength=count)
    left_out = np.bincount(labels[ink & ~text], minlength=count)
    cut = ((np.maximum(w, h) <= MARK_SIZE) & (x > 0) & (y > 0) & (x + w < width) & (y + h < height)
           & (under >= MARK_CUT * area) & (left_out <= letters.sum()))
    cut[0] = False
    marks = cut[labels] & ~text
    if marks.any():
        size = 2 * MARK_CLEAR + 1
        near = cv2.dilate(marks.astype(np.uint8), np.ones((size, size), np.uint8)) > 0
        # A letter is a piece of ink of a letter's size: not a speck of the scan's noise, not the
        # bubble outline or the art beyond it.
        letter = (area >= MARK_SPECK) & (np.maximum(w, h) <= MARK_SIZE) & ~cut
        letter[0] = False
        if (near & ~text & letter[labels]).any():
            return np.zeros(ink.shape, bool)
    return marks


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
            page, left = paint_halos(image, mask, getattr(ctx, "text_regions", None), getattr(ctx, "mask_raw", None))
            page, left = split_flat(page, left, ignore)
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
