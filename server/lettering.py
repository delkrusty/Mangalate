"""Fit the translated text to the bubble, not to the box of the original text.

The engine lays the translation out inside the box of the ORIGINAL lettering
and then scales the whole block to that box.  Portuguese is longer than
English, so the block gets more lines than the box allows and is shrunk:
in the Grand Blue 87 short test the rendered letters were a median 0.68 of
the original line height, and 0.33 in the narrow bubble of page 3.  The
bubble itself usually had room to spare.

Here, after cleaning, the bubble interior is found by flood fill from the
original text box (the cleaned interior is flat), the largest rectangle that
fits inside it is searched for each candidate font size, and the biggest
font that fits wins, capped at the original lettering size.  Lines get a
little more air than the engine's default.  When the bubble is open or not
found, the box of the original text is used, as before.
"""
import cv2
import numpy as np

FLOOD_TOLERANCE = 12     # per-channel difference accepted inside the cleaned interior
GROW = 1.5               # how far beyond the text box the bubble is searched, in box sizes...
GROW_MIN = 60            # ...plus this many pixels, so short text in a big bubble still finds its outline
MARGIN = 0.10            # inner margin, share of the line height... at least MIN_MARGIN px
MIN_MARGIN = 4
LINE_SPACING = 0.12      # extra space between lines, share of the font size
MAX_SCALE = 1.25         # Portuguese lowercase at this size matches English capitals (Grand Blue 87: caps = 0.73 of the line box)
MIN_INTERIOR = 0.55      # the interior must cover this share of the text box


def _fill(image, box, g):
    h, w = image.shape[:2]
    x0, y0, x1, y1 = box
    wx0, wy0, wx1, wy1 = max(0, x0 - g), max(0, y0 - g), min(w, x1 + g), min(h, y1 + g)
    window = np.ascontiguousarray(image[wy0:wy1, wx0:wx1, :3])
    inner = window[y0 - wy0:y1 - wy0, x0 - wx0:x1 - wx0].reshape(-1, 3).astype(int)
    if inner.size == 0:
        return None
    colour = np.median(inner, axis=0)
    close = (np.abs(window.astype(int) - colour).max(axis=2) <= FLOOD_TOLERANCE).astype(np.uint8)
    # Seed: the pixels of the text box that match the interior colour.
    _, labels = cv2.connectedComponents(close, connectivity=4)
    seeds = labels[y0 - wy0:y1 - wy0, x0 - wx0:x1 - wx0]
    seeds = seeds[seeds > 0]
    if seeds.size == 0:
        return None
    mask = labels == np.bincount(seeds).argmax()
    # Touching the window, or the page edge, means no outline closes that side
    # (text on a blank page or gutter): the text then keeps to its own box there.
    open_sides = {"left": mask[:, 0].any(), "right": mask[:, -1].any(),
                  "top": mask[0, :].any(), "bottom": mask[-1, :].any()}
    return mask, (wx0, wy0, wx1, wy1), open_sides


def bubble_mask(image, box, others=(), grow=GROW):
    """Interior of the bubble around ``box`` in the cleaned image, as (mask, x0, y0).

    ``others`` are boxes of other text regions; the space between two regions
    is split in half so they never write over each other.  The search window
    grows while the fill touches it; a side still touching the largest window
    or the page edge is treated as open and limited to the text box.
    """
    x0, y0, x1, y1 = box
    size = max(x1 - x0, y1 - y0)
    g = int(size * grow) + GROW_MIN
    for _ in range(4):
        found = _fill(image, box, g)
        if found is None or not any(found[2].values()):
            break
        g *= 2
    if found is None:
        return None
    mask, (wx0, wy0, wx1, wy1), open_sides = found
    if mask[y0 - wy0:y1 - wy0, x0 - wx0:x1 - wx0].mean() < MIN_INTERIOR:
        return None
    # Close small holes (leftover specks after cleaning) without crossing the outline.
    mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)) > 0
    bx0, by0, bx1, by1 = x0 - wx0, y0 - wy0, x1 - wx0, y1 - wy0
    if open_sides["left"]:
        mask[:, :bx0] = False
    if open_sides["right"]:
        mask[:, bx1:] = False
    if open_sides["top"]:
        mask[:by0, :] = False
    if open_sides["bottom"]:
        mask[by1:, :] = False
    for ox0, oy0, ox1, oy1 in others:
        horizontal_overlap = min(x1, ox1) > max(x0, ox0)
        vertical_overlap = min(y1, oy1) > max(y0, oy0)
        if horizontal_overlap and oy0 >= y1:
            mask[max(0, (y1 + oy0) // 2 - wy0):, :] = False
        elif horizontal_overlap and oy1 <= y0:
            mask[:max(0, (oy1 + y0) // 2 - wy0), :] = False
        elif vertical_overlap and ox0 >= x1:
            mask[:, max(0, (x1 + ox0) // 2 - wx0):] = False
        elif vertical_overlap and ox1 <= x0:
            mask[:, :max(0, (ox1 + x0) // 2 - wx0)] = False
        pad = 4
        mask[max(0, oy0 - wy0 - pad):max(0, oy1 - wy0 + pad), max(0, ox0 - wx0 - pad):max(0, ox1 - wx0 + pad)] = False
    return mask, wx0, wy0


def rectangles(mask, centre, margin, min_height):
    """Candidate (x0, y0, x1, y1) rectangles inside the mask, around ``centre``.

    Rectangles are centred horizontally on the original text and grow up and
    down from it, so the translation stays where the original was.
    """
    if margin > 0:
        mask = cv2.erode(mask.astype(np.uint8), np.ones((2 * margin + 1, 2 * margin + 1), np.uint8)) > 0
    h, w = mask.shape
    cx, cy = int(round(centre[0])), int(round(centre[1]))
    if not (0 <= cy < h and 0 <= cx < w) or not mask[cy].any():
        return []
    # Horizontal span through the centre column, row by row.
    left = np.full(h, -1)
    right = np.full(h, -1)
    for y in range(h):
        row = mask[y]
        if not row[cx]:
            continue
        l = cx
        while l > 0 and row[l - 1]:
            l -= 1
        r = cx
        while r < w - 1 and row[r + 1]:
            r += 1
        # Symmetric around the original text centre, so the text does not drift sideways.
        half = min(cx - l, r + 1 - cx)
        left[y], right[y] = cx - half, cx + half
    if left[cy] < 0:
        return []
    out = []
    top = bottom = cy
    lo, hi = left[cy], right[cy]
    while True:
        height = bottom - top + 1
        if height >= min_height:
            out.append((int(lo), top, int(hi), bottom + 1))
        grow_up = top > 0 and left[top - 1] >= 0
        grow_down = bottom < h - 1 and left[bottom + 1] >= 0
        if not grow_up and not grow_down:
            break
        # Grow towards the side that keeps the rectangle wider.
        up_w = min(hi, right[top - 1]) - max(lo, left[top - 1]) if grow_up else -1
        down_w = min(hi, right[bottom + 1]) - max(lo, left[bottom + 1]) if grow_down else -1
        if up_w >= down_w:
            top -= 1
            lo, hi = max(lo, left[top]), min(hi, right[top])
        else:
            bottom += 1
            lo, hi = max(lo, left[bottom]), min(hi, right[bottom])
        if hi - lo < min_height:
            break
    return out


def block_size(lines, widths, font_size, spacing=LINE_SPACING):
    n = len(lines)
    return (max(widths) if widths else 0), int(font_size * n + font_size * spacing * max(0, n - 1))


def best_layout(text, rects, layout, cap, floor):
    """Biggest font in [floor, cap] whose block fits one of ``rects``.

    ``layout(font_size, width, height)`` returns (lines, widths) as the engine
    would draw them.  Returns (font_size, rect) or None.
    """
    def fits(size, rect):
        x0, y0, x1, y1 = rect
        lines, widths = layout(size, x1 - x0, y1 - y0)
        if not lines:
            return False
        bw, bh = block_size(lines, widths, size)
        return bw <= x1 - x0 and bh <= y1 - y0

    ordered = sorted(rects, key=lambda r: (r[3] - r[1]) * (r[2] - r[0]), reverse=True)

    def any_fit(size):
        return next((rect for rect in ordered if fits(size, rect)), None)

    lo, hi = int(floor), int(cap)
    if lo > hi or any_fit(lo) is None:
        return None
    # Binary search for the biggest size that still fits somewhere.
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if any_fit(mid) is not None:
            lo = mid
        else:
            hi = mid - 1
    return lo, any_fit(lo)


def plan(image, region_box, others, text, layout, original_size, minimum, offset=0):
    """Rectangle and font size for one region; None keeps the engine's behaviour."""
    found = bubble_mask(image, region_box, others)
    x0, y0, x1, y1 = region_box
    margin = max(MIN_MARGIN, int(round(original_size * MARGIN)))
    if found is None:
        return None
    mask, wx0, wy0 = found
    centre = ((x0 + x1) / 2 - wx0, (y0 + y1) / 2 - wy0)
    floor = max(1, int(minimum))
    rects = rectangles(mask, centre, margin, floor)
    # A few heights are enough to find the best shape.
    step = max(1, len(rects) // 24)
    rects = rects[::step] + rects[-1:]
    # The original text box is always a candidate: the text was there, so the
    # result is never worse than the engine's own fit (TBATE p7: a translucent
    # bubble let the art through and left only a sliver of flat interior).
    rects.append((x0 - wx0, y0 - wy0, x1 - wx0, y1 - wy0))
    # The app's font size setting (-3..+3) moves the cap like it moves the engine's size.
    cap = max(floor, int(round(original_size * MAX_SCALE)) + int(offset))
    chosen = best_layout(text, rects, layout, cap, floor)
    if chosen is None:
        return None
    size, (rx0, ry0, rx1, ry1) = chosen
    return size, (rx0 + wx0, ry0 + wy0, rx1 + wx0, ry1 + wy0)


# Shaped lettering --------------------------------------------------------------
#
# Gold standard (scanlation look): the lines follow the bubble.  In an oval the
# middle lines are wider than the first and the last, the block sits in the
# middle of the bubble, and the lines are balanced instead of one long line and
# a stray word (TBATE 199 p13: "É, porque foi só isso" touched the top of the
# oval; 242 p43: "alguma coisa / de que / gostou?" in a thin column).

import os
import re

FONTS = {
    # Comic Neue Bold (SIL Open Font License, server/fonts): the scanlation look.
    "quadrinhos": "/mangalate/fonts/ComicNeue-Bold.ttf",
    # The engine's own Arial, for readers who prefer plain letters.
    "simples": "/app/fonts/Arial-Unicode-Regular.ttf",
}


def font_file():
    """The font of the shaped lettering (MANGALATE_FONT); None = the engine's own layout."""
    choice = os.environ.get("MANGALATE_FONT", "quadrinhos").strip()
    path = FONTS.get(choice.lower(), choice if choice.lower().endswith((".ttf", ".otf")) else None)
    return path if path and os.path.exists(path) else None


# The original lettering is in capitals; mixed-case Portuguese at the same em size
# reads smaller (x-height ~0.5 em against caps ~0.7 em), so the shaped plan may go
# further than the rectangle plan when the bubble has the room.
SHAPED_MAX_SCALE = 1.45
REFERENCE = "ÉÇÃgjpq"   # tallest accents and deepest descenders: the height of a line slot
MAX_LINES = 12
BALANCE_STEPS = 7


def half_widths(mask, cx):
    """Per row, half the width of the interior span symmetric around column ``cx`` (0 = outside)."""
    h, w = mask.shape
    half = np.zeros(h, int)
    if not 0 <= cx < w:
        return half
    for y in np.flatnonzero(mask[:, cx]):
        row = mask[y]
        l = cx
        while l > 0 and row[l - 1]:
            l -= 1
        r = cx
        while r < w - 1 and row[r + 1]:
            r += 1
        half[y] = min(cx - l, r + 1 - cx)
    return half


def wrap(words, widths, measure):
    """Greedy wrap into lines of the given widths; None when a word does not fit or lines run out."""
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}" if current else word
        if measure(trial) <= widths[len(lines)]:
            current = trial
            continue
        if not current:
            return None  # the word alone is wider than its line
        lines.append(current)
        if len(lines) >= len(widths) or measure(word) > widths[len(lines)]:
            return None
        current = word
    if current:
        lines.append(current)
    if len(lines) > 1 and any(re.sub(r"[^\w]", "", line).lower() in DANGLING for line in lines):
        return None  # a lone "um" or "de" on its own line reads as a mistake (Grand Blue p44)
    return lines


# Short words that lean on their neighbour: alone on a line they read as a mistake.
DANGLING = set("a o as os à ao um uma e é de da do das dos em no na nos nas que se me te lhe por pra pro "
               "com sem mas ou nem".split())


def shaped(half, centre_x, rows, text, font, spacing=LINE_SPACING):
    """Fewest balanced lines of ``text`` that follow the interior; (lines, top, slot, advance) or None.

    ``half`` comes from half_widths, ``rows`` = (top, bottom) of the interior
    around the text, ``font(text) -> width`` measures at the size being tried
    and carries ``slot`` (line height) and ``size`` attributes.
    """
    words = text.split()
    if not words:
        return None
    top_row, bottom_row = rows
    slot, advance = font.slot, font.slot + font.size * spacing
    for n in range(1, MAX_LINES + 1):
        height = slot + advance * (n - 1)
        if height > bottom_row - top_row + 1:
            return None
        top = (top_row + bottom_row + 1 - height) / 2
        widths = []
        for i in range(n):
            y0 = int(round(top + i * advance))
            y1 = int(round(top + i * advance + slot))
            span = half[max(0, y0):max(0, y1)]
            widths.append(2 * int(span.min()) if len(span) and span.min() > 0 else 0)
        if min(widths) <= 0 or wrap(words, widths, font) is None:
            continue
        # Balance: the narrowest widths that still hold the text in n lines.
        lo, hi = 0.3, 1.0
        for _ in range(BALANCE_STEPS):
            mid = (lo + hi) / 2
            if wrap(words, [w * mid for w in widths], font) is not None:
                hi = mid
            else:
                lo = mid
        lines = wrap(words, [w * hi for w in widths], font) or wrap(words, widths, font)
        if len(lines) < n:
            continue  # fewer lines would sit elsewhere; the smaller n already failed there
        return lines, top, slot, advance
    return None


class Measure:
    """Width of a line at one size of a font file (PIL), with its line slot."""

    _cache = {}

    def __init__(self, path, size):
        from PIL import ImageFont
        key = (path, size)
        if key not in Measure._cache:
            Measure._cache[key] = ImageFont.truetype(path, size)
        self.font = Measure._cache[key]
        self.size = size
        x0, y0, x1, y1 = self.font.getbbox(REFERENCE)
        self.offset = y0
        self.slot = y1 - y0

    def __call__(self, text):
        return self.font.getlength(text)


def plan_shaped(image, region_box, others, text, font_path, original_size, minimum, offset=0):
    """Font size and lines that follow the bubble; None to use the rectangle plan."""
    found = bubble_mask(image, region_box, others)
    if found is None or not font_path:
        return None
    mask, wx0, wy0 = found
    x0, y0, x1, y1 = region_box
    margin = max(MIN_MARGIN, int(round(original_size * MARGIN)))
    inner = cv2.erode(mask.astype(np.uint8), np.ones((2 * margin + 1, 2 * margin + 1), np.uint8)) > 0
    cx = int(round((x0 + x1) / 2 - wx0))
    cy = int(round((y0 + y1) / 2 - wy0))
    half = half_widths(inner, cx)
    if not 0 <= cy < len(half) or half[cy] <= 0:
        return None
    # The interior rows around the text: the block is centred in them, like a letterer would.
    top = bottom = cy
    while top > 0 and half[top - 1] > 0:
        top -= 1
    while bottom < len(half) - 1 and half[bottom + 1] > 0:
        bottom += 1
    floor = max(1, int(minimum))
    cap = max(floor, int(round(original_size * SHAPED_MAX_SCALE)) + int(offset))

    def attempt(size):
        return shaped(half, cx, (top, bottom), text, Measure(font_path, size))

    if attempt(floor) is None:
        return None
    lo, hi = floor, cap
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if attempt(mid) is not None:
            lo = mid
        else:
            hi = mid - 1
    lines, block_top, slot, advance = attempt(lo)
    width = max(Measure(font_path, lo)(line) for line in lines)
    x, top = cx + wx0, block_top + wy0
    box = (int(x - width / 2), int(top), int(x + width / 2) + 1, int(top + slot + advance * (len(lines) - 1)) + 1)
    return {"size": lo, "lines": lines, "x": x, "top": top, "slot": slot, "advance": advance,
            "font": font_path, "box": box}


def draw_shaped(img, plan, fg, bg):
    """Draw a plan_shaped result on the RGB page (in place)."""
    from PIL import Image, ImageDraw
    measure = Measure(plan["font"], plan["size"])
    h, w = img.shape[:2]
    stroke = max(1, int(round(plan["size"] * 0.07))) if bg is not None else 0
    pad = stroke + 2
    widths = [measure(line) for line in plan["lines"]]
    left = int(plan["x"] - max(widths) / 2) - pad
    top = int(plan["top"]) - pad
    width = int(max(widths)) + 2 * pad + 1
    height = int(plan["slot"] + plan["advance"] * (len(plan["lines"]) - 1)) + 2 * pad + 1
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for i, (line, lw) in enumerate(zip(plan["lines"], widths)):
        x = plan["x"] - lw / 2 - left
        y = plan["top"] + i * plan["advance"] - measure.offset - top
        draw.text((x, y), line, font=measure.font, fill=tuple(int(c) for c in fg) + (255,),
                  stroke_width=stroke, stroke_fill=tuple(int(c) for c in bg) + (255,) if stroke else None)
    box = np.asarray(layer)
    cx0, cy0, cx1, cy1 = max(0, left), max(0, top), min(w, left + width), min(h, top + height)
    if cx1 <= cx0 or cy1 <= cy0:
        return img
    part = box[cy0 - top:cy1 - top, cx0 - left:cx1 - left]
    alpha = part[:, :, 3:4].astype(np.float32) / 255.0
    target = img[cy0:cy1, cx0:cx1].astype(np.float32)
    img[cy0:cy1, cx0:cx1] = np.clip(target * (1 - alpha) + part[:, :, :3] * alpha, 0, 255).astype(np.uint8)
    return img
