"""Bubbles cut between two webtoon slices.

Webtoon chapters arrive as slices of one long strip, and a speech bubble can
be cut by the slice boundary.  Translating each slice alone splits the
sentence in two and leaves lines on the cut undetected (episode 65: pages
023/024, 061/062, 101/102).

When the caller sends the neighbouring slices, the page is translated inside a
short strip (bottom of the previous slice + page + top of the next one), then
cropped back to its exact size.  Neighbours are only used when the edges are
really continuous and the seam row has content; a blank seam cannot cut a
bubble.

Both pages of a cut bubble see it whole, but they are processed in separate
requests.  So that the two halves match, the first request that renders a
bubble crossing a seam stores the part that belongs to the other page; the
other page pastes that stored part instead of its own rendering.
"""
import hashlib
from collections import OrderedDict

import numpy as np
from PIL import Image

CONTEXT_RATIO = 0.35   # share of the page height borrowed from each neighbour
EDGE_LIMIT = 12.0      # colour jump always accepted across the seam
EDGE_FACTOR = 2.0      # ...or up to this many times the change between rows near it
BUSY_MIN = 12.0        # seam rows flatter than this cannot cut a bubble
MARGIN = 12            # extra pixels kept around a stored half


def page_key(image, salt=""):
    """Page identity plus the translation settings, so a new provider never reuses old halves."""
    array = np.asarray(image.convert("RGB"))
    digest = hashlib.sha256(array.tobytes())
    digest.update(salt.encode())
    return digest.hexdigest()[:32] + f"-{array.shape[1]}x{array.shape[0]}"


def edge_gap(upper, lower):
    """Colour jump across the seam and the usual row-to-row change next to it.

    Lettering cut by the seam changes fast from row to row, so the jump is
    compared with the local change instead of a fixed limit alone (episode 65,
    023/024: jump 16, local change 13).
    """
    a, b = upper.astype(float), lower.astype(float)
    seam = float(np.abs(a[-1] - b[0]).mean())
    inner = float((np.abs(a[-2] - a[-1]).mean() + np.abs(b[0] - b[1]).mean()) / 2)
    return seam, inner


def edge_busy(row):
    return float(row.astype(float).std(axis=0).mean())


def continuous(upper, lower):
    return (upper.shape[1] == lower.shape[1]
            and edge_busy(upper[-1]) >= BUSY_MIN and edge_busy(lower[0]) >= BUSY_MIN
            and _within(*edge_gap(upper, lower)))


def _within(seam, inner):
    return seam <= max(EDGE_LIMIT, EDGE_FACTOR * inner)


class Strip:
    """A page with optional borrowed context above and below."""

    def __init__(self, page, above=None, below=None):
        self.page = page.convert("RGB")
        p = np.asarray(self.page)
        self.height, self.width = p.shape[:2]
        borrow = max(1, int(self.height * CONTEXT_RATIO))
        parts, self.top, self.below_rows = [], 0, 0
        self.above = self.below = None
        if above is not None:
            a = np.asarray(above.convert("RGB"))
            if continuous(a, p):
                self.above, self.top = above.convert("RGB"), min(borrow, a.shape[0])
                parts.append(a[-self.top:])
        parts.append(p)
        if below is not None:
            b = np.asarray(below.convert("RGB"))
            if continuous(p, b):
                self.below, self.below_rows = below.convert("RGB"), min(borrow, b.shape[0])
                parts.append(b[:self.below_rows])
        self.image = Image.fromarray(np.concatenate(parts)) if len(parts) > 1 else self.page

    @property
    def stitched(self):
        return self.above is not None or self.below is not None

    @property
    def bottom(self):
        return self.top + self.height

    def crop(self, result):
        return result.convert("RGB").crop((0, self.top, self.width, self.bottom))


def region_box(region):
    x0, y0, x1, y1 = (int(v) for v in region.xyxy)
    return x0, y0, x1, y1


class SeamCache:
    """Rendered halves of cut bubbles, keyed by the page they belong to."""

    def __init__(self, limit=64):
        self.limit = limit
        self.items = OrderedDict()

    def add(self, key, box, patch):
        self.items.setdefault(key, []).append((box, patch))
        self.items.move_to_end(key)
        while len(self.items) > self.limit:
            self.items.popitem(last=False)

    def take(self, key):
        return self.items.get(key, [])


def finish(strip, result, regions, cache, salt=""):
    """Crop the strip result to the page and keep both halves of cut bubbles consistent."""
    result = result.convert("RGB")
    full = np.asarray(result)
    page = np.array(strip.crop(result))
    own_key = page_key(strip.page, salt)
    for (x0, y0, x1, y1), patch in cache.take(own_key):
        page[y0:y1, x0:x1] = patch
    for region in regions or []:
        rx0, ry0, rx1, ry1 = region_box(region)
        mx = MARGIN + (rx1 - rx0) // 4
        my = MARGIN + (ry1 - ry0) // 4
        x0, x1 = max(0, rx0 - mx), min(strip.width, rx1 + mx)
        if strip.above is not None and ry0 < strip.top < ry1:
            y0 = max(0, ry0 - my)
            above_h = strip.above.height
            cache.add(page_key(strip.above, salt), (x0, above_h - (strip.top - y0), x1, above_h),
                      full[y0:strip.top, x0:x1].copy())
        if strip.below is not None and ry0 < strip.bottom < ry1:
            y1 = min(full.shape[0], ry1 + my)
            cache.add(page_key(strip.below, salt), (x0, 0, x1, y1 - strip.bottom),
                      full[strip.bottom:y1, x0:x1].copy())
    return Image.fromarray(page)
