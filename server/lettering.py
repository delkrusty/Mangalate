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


LEAK_RADII = (3, 6, 10)   # the widest gap in an outline (px) that still closes a bubble


def _close_leak(mask, box, open_sides):
    """The bubble alone when its fill leaked out through a thin gap; else the mask unchanged.

    Grand Blue 87 p45: a bubble that breaks the panel frame joins the white
    gutter through a gap a few pixels wide; the fill then touched every side
    and the text kept to its own small box ("Parece bem simples." at half size).
    """
    x0, y0, x1, y1 = box
    cy, cx = (y0 + y1) // 2, (x0 + x1) // 2
    for r in LEAK_RADII:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
        opened = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, k)
        _, labels = cv2.connectedComponents(opened, connectivity=4)
        label = labels[cy, cx] if 0 <= cy < labels.shape[0] and 0 <= cx < labels.shape[1] else 0
        if not label:
            continue
        part = labels == label
        if part[:, 0].any() or part[:, -1].any() or part[0, :].any() or part[-1, :].any():
            continue
        part = (cv2.dilate(part.astype(np.uint8), k) > 0) & mask
        return part, {side: False for side in open_sides}
    return mask, open_sides


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
    if any(open_sides.values()):
        mask, open_sides = _close_leak(mask, (x0 - wx0, y0 - wy0, x1 - wx0, y1 - wy0), open_sides)
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
DANGLING_COST = 0.8      # a dangling word is accepted when avoiding it shrinks the letters below this share
SENTENCE_COST = 0.9      # likewise for a sentence that ends mid-line
SHAPED_MARGIN = 0.3      # air between the letters and the outline, share of the line height (TBATE 237 p20:
                         # with 0.1 the caption text touched the box on both sides)
CENTRE_ASYMMETRY = 1.0   # the rows are limited only when their middle is this far from the text, in line
                         # heights: a fill leaked into the sky, not a closed bubble around the text
CENTRE_SPARE = 2.0       # rows then kept above and below the original text box, in line heights


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


def wrap(words, widths, measure, strict=True, sentences=False, syllables=False):
    """Greedy wrap into lines of the given widths; None when a word does not fit or lines run out.

    ``strict`` also refuses a layout with a dangling word alone on a line (see dangling);
    ``sentences`` starts a new line after each sentence of two words or more; ``syllables``
    cuts a word wider than its whole line at a syllable ("...transfor-" / "mando").
    """
    lines, current, sentence = [], "", 0
    # A word with its own hyphen may end a line there ("fogo-" / "Blitz!!"), as a letterer does.
    pieces = [(part, k > 0, True) for word in words for k, part in enumerate(hyphen_pieces(word))]
    while pieces:
        word, glued, cuttable = pieces.pop(0)
        trial = (f"{current}{word}" if glued else f"{current} {word}") if current else word
        if sentences and current and sentence >= 2 and SENTENCE_END.search(current):
            trial = None  # "...levarem ela?" ends its line; a one-word "Sim." may share one
        sentence = 1 if SENTENCE_END.search(current or ".") else sentence + 1
        if trial and measure(trial) <= widths[len(lines)]:
            current = trial
            continue
        if current:
            lines.append(current)
            current = ""
            if len(lines) >= len(widths):
                return None
        if measure(word) <= widths[len(lines)]:
            current = word
            continue
        cut = syllable_cut(word, widths[len(lines)], measure) if syllables and cuttable else None
        if cut is None:
            return None  # the word alone is wider than its line
        lines.append(word[:cut] + "-")
        if len(lines) >= len(widths):
            return None
        pieces.insert(0, (word[cut:], False, False))  # one cut a word: "ines-" / "capá-" / "vel" reads as noise
    if current:
        lines.append(current)
    if strict and len(lines) > 1 and any(dangling(line) for line in lines):
        return None  # a lone "um" or "de" on its own line reads as a mistake (Grand Blue p44)
    return lines


SENTENCE_END = re.compile(r"[.!?…]$")
# After the hyphen of "bem-vindo", never in "--" nor before a pronoun ("salvá-la", "dar-lhes").
HYPHEN_BREAK = re.compile(r"(?<=[^\W\d_]{2}-)(?=[^\W\d_]{4})(?!lhes(?![^\W\d_]))", re.I)


def hyphen_pieces(word):
    """``word`` split after its own hyphens, keeping a stutter whole: "V-você", "Nã-não"."""
    pieces = []
    for part in HYPHEN_BREAK.split(word):
        head = re.sub(r"[\W\d_]", "", pieces[-1]).lower() if pieces else ""
        if head and re.sub(r"[\W\d_]", "", part).lower().startswith(head):
            pieces[-1] += part
        else:
            pieces.append(part)
    return pieces


HYPHEN_SIDE = 3     # letters kept on each side of a syllable cut ("inesca-" / "pável"), as typesetters do
HYPHEN_WORD = 8     # only words this long are cut: "cer-" / "teza" and "ver-" / "dade" read choppy
HYPHEN_GAIN = 1.15  # syllable cuts are used only when they let the letters grow at least this much...
HYPHEN_BELOW = 0.85  # ...from below this share of the original size, and never past the original
_PATTERNS = None


def _patterns():
    """The pt-BR hyphenation patterns (DivSilab, server/words/hyph_pt_BR) as a trie; empty when missing."""
    global _PATTERNS
    if _PATTERNS is None:
        from pathlib import Path
        root = {}
        try:
            text = (Path(__file__).resolve().parent / "words" / "hyph_pt_BR" / "hyph_pt_BR.dic").read_text(encoding="utf-8")
        except OSError:
            text = ""
        for raw in text.splitlines():
            pattern = raw.strip()
            if not pattern or pattern == "UTF-8" or pattern.startswith("%"):
                continue
            letters, weights = "", [0]
            for c in pattern:
                if c.isdigit():
                    weights[-1] = int(c)
                else:
                    letters += c
                    weights.append(0)
            node = root
            for c in letters:
                node = node.setdefault(c, {})
            node[None] = weights
        _PATTERNS = root
    return _PATTERNS


def syllable_breaks(word):
    """Where a Portuguese word may be cut at the end of a line (Liang's patterns), as letter counts.

    Only lower-case words of letters alone: a capital may start a name ("Shakuyaku"), which
    is never cut.
    """
    if len(word) < HYPHEN_WORD or not word.isalpha() or not word.islower():
        return []
    padded = f".{word}."
    weights = [0] * (len(padded) + 1)
    trie = _patterns()
    for start in range(len(padded)):
        node = trie
        for end in range(start, len(padded)):
            node = node.get(padded[end])
            if node is None:
                break
            for i, weight in enumerate(node.get(None, ())):
                weights[start + i] = max(weights[start + i], weight)
    return [k for k in range(HYPHEN_SIDE, len(word) - HYPHEN_SIDE + 1) if weights[k + 1] % 2]


def syllable_cut(word, width, measure):
    """The longest head of ``word`` that, cut at a syllable with its hyphen, fits ``width``; else None."""
    letters = [i for i, c in enumerate(word) if c.isalpha()]
    if not letters:
        return None
    start, end = letters[0], letters[-1] + 1
    fits = [k for k in reversed(syllable_breaks(word[start:end])) if measure(word[:start + k] + "-") <= width]
    core = word[start:end].lower()
    apart = [k for k in fits if not (core[k - 1] in VOWELS and core[k] in VOWELS)]
    return start + (apart or fits)[0] if fits else None


VOWELS = set("aeiouáéíóúâêôãõàü")


def syllable_cuts(lines, words):
    """How many of ``lines`` end in a syllable cut, not in a word's own hyphen ("fogo-")."""
    return sum(line.count("-") for line in lines) - sum(word.count("-") for word in words)


def dangling(line):
    """A line that is one short word leaning on its neighbour: "um", "de", "qual / é.", but not "mas..."."""
    core = re.sub(r"[^\w]", "", line).lower()
    if " " in line.strip() or core not in DANGLING:
        return False
    return len(core) == 1 or not re.search(r"[.,!?…—-]$", line.strip())


# Short words that lean on their neighbour: alone on a line they read as a mistake.
DANGLING = set("a o as os à ao um uma e é de da do das dos em no na nos nas que se me te lhe por pra pro "
               "com sem mas ou nem".split())


def shaped(half, centre_x, rows, text, font, spacing=LINE_SPACING, strict=True, sentences=False, syllables=False):
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
        full = wrap(words, widths, font, strict, sentences, syllables) if min(widths) > 0 else None
        if full is None:
            continue
        # Balance: the narrowest widths that still hold the text in n lines (with no more words cut).
        cuts = syllable_cuts(full, words)
        lo, hi = 0.3, 1.0
        for _ in range(BALANCE_STEPS):
            mid = (lo + hi) / 2
            trial = wrap(words, [w * mid for w in widths], font, strict, sentences, syllables)
            if trial is not None and syllable_cuts(trial, words) <= cuts:
                hi = mid
            else:
                lo = mid
        lines = wrap(words, [w * hi for w in widths], font, strict, sentences, syllables) if hi < 1.0 else None
        if lines is None or syllable_cuts(lines, words) > cuts:
            lines = full
        if len(lines) < n:
            continue  # fewer lines would sit elsewhere; the smaller n already failed there
        return lines, top, slot, advance
    return None


# Symbols the comic font lacks ("♡", "★", "♪": One Piece 1161 p5 drew a box for "♡") are
# drawn in the first of these the image has (DejaVu comes with fonts-dejavu-core).
SYMBOL_FONT = next((p for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", FONTS["simples"])
                    if os.path.exists(p)), None)
_GLYPHS = {}


def _has_glyph(font, ch, cache=_GLYPHS):
    """True when ``font`` draws ``ch``, not the box (or blank) it draws for a character it lacks."""
    key = (font.path, ch)
    if key not in cache:
        from PIL import Image, ImageDraw

        def ink(c):
            im = Image.new("L", (2 * font.size, 2 * font.size), 0)
            ImageDraw.Draw(im).text((0, 0), c, font=font, fill=255)
            return np.asarray(im)
        cache[key] = ch.isspace() or not np.array_equal(ink(ch), ink("\uffff"))
    return cache[key]


class Measure:
    """Width of a line at one size of a font file (PIL), with its line slot."""

    _cache = {}

    def __init__(self, path, size):
        self.font = Measure._load(path, size)
        self.size = size
        x0, y0, x1, y1 = self.font.getbbox(REFERENCE)
        self.offset = y0
        self.slot = y1 - y0

    @staticmethod
    def _load(path, size):
        from PIL import ImageFont
        key = (path, size)
        if key not in Measure._cache:
            Measure._cache[key] = ImageFont.truetype(path, size)
        return Measure._cache[key]

    def runs(self, text):
        """``text`` as (piece, font) runs: a symbol the font lacks goes to SYMBOL_FONT when that one has it."""
        out = []
        for ch in text:
            font = self.font
            if ord(ch) > 127 and SYMBOL_FONT and not _has_glyph(font, ch):
                symbols = Measure._load(SYMBOL_FONT, self.size)
                if _has_glyph(symbols, ch):
                    font = symbols
            if out and out[-1][1] is font:
                out[-1][0] += ch
            else:
                out.append([ch, font])
        return [(piece, font) for piece, font in out]

    def __call__(self, text):
        return sum(font.getlength(piece) for piece, font in self.runs(text))


def plan_shaped(image, region_box, others, text, font_path, original_size, minimum, offset=0, syllables=True,
                scale=SHAPED_MAX_SCALE):
    """Font size and lines that follow the bubble; None to use the rectangle plan.

    ``scale`` caps the letters, in original line heights.

    With ``syllables`` a long word may be cut at a syllable when that lets the letters grow
    by HYPHEN_GAIN (One Piece 1161 p4: "...transformando" whole in a narrow caption column
    left the letters at half the original size).
    """
    found = bubble_mask(image, region_box, others)
    if found is None or not font_path:
        return None
    mask, wx0, wy0 = found
    x0, y0, x1, y1 = region_box
    margin = max(MIN_MARGIN, int(round(original_size * SHAPED_MARGIN)))
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
    # A fill that leaked into the sky of the panel (or text with no bubble) would pull the block
    # several lines away from the text, over the outline of another bubble: the rows are then
    # kept symmetric around the text up to the edge of the interior.  A closed bubble keeps them.
    if abs((top + bottom) / 2 - cy) > CENTRE_ASYMMETRY * original_size:
        reach = max(min(cy - top, bottom - cy), int(round((y1 - y0) / 2 + CENTRE_SPARE * original_size)))
        top, bottom = max(top, cy - reach), min(bottom, cy + reach)
    floor = max(1, int(minimum))
    cap = max(floor, int(round(original_size * scale)) + int(offset))

    def largest(strict, sentences=False, cut=False, cap=cap):
        def attempt(size):
            return shaped(half, cx, (top, bottom), text, Measure(font_path, size), strict=strict, sentences=sentences,
                          syllables=cut)
        if attempt(floor) is None:
            return None
        lo, hi = floor, cap
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if attempt(mid) is not None:
                lo = mid
            else:
                hi = mid - 1
        return lo, attempt(lo)

    # Preferences, each kept while it costs little size or the letters stay as big as
    # the original: a new line for each
    # sentence (TBATE 236 p13: "levarem ela? Por / favor, vem."), then no dangling
    # word (236 p15: "Ela tava / bem, mas..." would otherwise shrink to one tiny line).
    def preferred(cut=False, cap=cap):
        loose = largest(False, cut=cut, cap=cap)
        if loose is None:
            return None
        for (strict, sentences), cost in (((True, True), SENTENCE_COST), ((True, False), DANGLING_COST)):
            found = largest(strict, sentences, cut, cap)
            if found is not None and found[0] >= min(cost * loose[0], original_size):
                return found
        return loose

    best = preferred()
    # Worth a try only with a word that can be cut and room for the letters to grow.
    can_cut = syllables and any(syllable_breaks(re.sub(r"[^\w]", "", word)) for word in text.split())
    limit = max(floor, min(cap, int(round(original_size))))
    small = best is None or best[0] < HYPHEN_BELOW * original_size
    cut = preferred(True, limit) if can_cut and small and (best is None or HYPHEN_GAIN * best[0] <= limit) else None
    if cut is not None and syllable_cuts(cut[1][0], text.split()) and (best is None or cut[0] >= HYPHEN_GAIN * best[0]):
        best = cut
    if best is None:
        return None
    lo, (lines, block_top, slot, advance) = best
    width = max(Measure(font_path, lo)(line) for line in lines)
    x, top = cx + wx0, block_top + wy0
    box = (int(x - width / 2), int(top), int(x + width / 2) + 1, int(top + slot + advance * (len(lines) - 1)) + 1)
    return {"size": lo, "lines": lines, "x": x, "top": top, "slot": slot, "advance": advance,
            "font": font_path, "box": box}


TONE_DARK = 128       # a pixel darker than this is ink (an outline, a stroke); screentone dots are lighter
TONE_CLUTTER = 0.02   # share of ink inside the outline above which the room is a drawn panel, not a bubble
TONE_BELOW = 0.75     # the toned room is tried when the letters came out smaller than this share of the original
TONE_CLOSE = 9        # gap between strokes of a drawing closed to find them inside the fill, px


def toned_page(image, box, hull):
    """The page with all but the ink made white, when that shows a clean bubble around ``box``; else None.

    Manga teste p10: speech in a bubble of light screentone, cleaned letter by letter, so only
    the patch around the letters was flat and the room for the translation stopped at the dots
    of the tone (14 px letters for 22).  Ink closes the bubble; ``hull`` (the original lines) is
    white whatever is left in it.  A fill that reaches the edge of the search window (no outline
    around) or that holds strokes of ink (a panel of the drawing) is no bubble.
    """
    gray = cv2.cvtColor(np.ascontiguousarray(image[..., :3]), cv2.COLOR_RGB2GRAY)
    ink = gray < TONE_DARK
    inside = np.zeros(gray.shape, np.uint8)
    cv2.fillPoly(inside, [np.asarray(hull, np.int32).reshape(-1, 1, 2)], 1)
    ink &= inside == 0
    page = np.dstack([np.where(ink, 0, 255).astype(np.uint8)] * 3)
    x0, y0, x1, y1 = box
    found = _fill(page, box, int(max(x1 - x0, y1 - y0) * GROW) + GROW_MIN)
    if found is None or any(found[2].values()):
        return None
    mask, (wx0, wy0, wx1, wy1), _ = found
    # Strokes of a drawing split the fill into strips; closing the gaps between them puts the
    # strokes inside, where the outline of a bubble stays out.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (TONE_CLOSE, TONE_CLOSE))
    closed = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    outline = np.zeros(mask.shape, np.uint8)
    cv2.drawContours(outline, contours, -1, 1, -1)
    if (ink[wy0:wy1, wx0:wx1] & (outline > 0)).sum() > TONE_CLUTTER * outline.sum():
        return None
    return page


STACK_ADVANCE = 1.3   # rows of stacked letters, in cap heights
STACK_ROOM = 1.1      # the stacked letters may take this share of the original column's height...
STACK_WIDTH = 1.6     # ...and be this many times as wide as it


def plan_stacked(region_box, text, font_path, minimum):
    """Capitals stacked one per row in the column of the original ("GUYS!" in a tall bubble).

    A plan for draw_shaped, or None when the letters do not fit at ``minimum`` size.
    Spaces between words become an empty row.
    """
    if not font_path:
        return None
    chars = list(" ".join(text.split()).upper())
    if not chars:
        return None
    x0, y0, x1, y1 = region_box
    room, wide = (y1 - y0) * STACK_ROOM, max(1, x1 - x0) * STACK_WIDTH
    best = None
    for size in range(int(minimum), 400):
        measure = Measure(font_path, size)
        _, top, _, bottom = measure.font.getbbox("H")
        cap = bottom - top
        advance = cap * STACK_ADVANCE
        if cap + advance * (len(chars) - 1) > room or max(measure(c) for c in chars) > wide:
            break
        best = (size, cap, advance, top)
    if best is None:
        return None
    size, cap, advance, offset = best
    height = cap + advance * (len(chars) - 1)
    x, top = (x0 + x1) / 2, (y0 + y1) / 2 - height / 2
    width = max(Measure(font_path, size)(c) for c in chars)
    box = (int(x - width / 2), int(top), int(x + width / 2) + 1, int(top + height) + 1)
    return {"size": size, "lines": chars, "x": x, "top": top, "slot": cap, "advance": advance,
            "font": font_path, "box": box, "offset": offset}


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
        y = plan["top"] + i * plan["advance"] - plan.get("offset", measure.offset) - top
        base = y + measure.font.getmetrics()[0]
        for piece, font in measure.runs(line):  # on one baseline when a symbol comes from SYMBOL_FONT
            draw.text((x, base), piece, font=font, anchor="ls", fill=tuple(int(c) for c in fg) + (255,),
                      stroke_width=stroke, stroke_fill=tuple(int(c) for c in bg) + (255,) if stroke else None)
            x += font.getlength(piece)
    box = np.asarray(layer)
    cx0, cy0, cx1, cy1 = max(0, left), max(0, top), min(w, left + width), min(h, top + height)
    if cx1 <= cx0 or cy1 <= cy0:
        return img
    part = box[cy0 - top:cy1 - top, cx0 - left:cx1 - left]
    alpha = part[:, :, 3:4].astype(np.float32) / 255.0
    target = img[cy0:cy1, cx0:cx1].astype(np.float32)
    img[cy0:cy1, cx0:cx1] = np.clip(target * (1 - alpha) + part[:, :, :3] * alpha, 0, 255).astype(np.uint8)
    return img
