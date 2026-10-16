"""Mangalate quality rules applied around the GPL engine (numpy/OpenCV only).

Two defects observed on real pages motivate this module:

1. The engine's mask refinement drops the WHOLE mask of a text block when its
   surroundings contain more than ten coloured pixels (``utils/bubble.py``
   ``check_color``) while the OCR stage keeps and translates that block.  The
   translation is then drawn over the untouched original.  Here a region is
   classified ONCE, before translation, and the same decision drives both the
   mask and the rendering: a region is either cleaned and translated, or left
   completely original and reported for review.

2. ``compact_special_symbols`` removes the space after every punctuation mark,
   a rule meant for CJK text.  In Portuguese it glues words ("Sim,eu"), and the
   line breaker then cuts the oversized word at an arbitrary letter.

3. The detector's pixel mask finds every lettered line, but its line boxes
   sometimes miss one (TBATE 236 p6: "MUST'VE MAL-" in bold italic) or cover
   two lines with one box (Grand Blue 87 p3: "PITS AND / DIE.").  A line
   without its own box is never read, cleaned or translated.  ``repair_lines``
   rebuilds those boxes from the pixel mask before OCR.  A line can also lose
   its box at OCR, which drops lines read with confidence below 0.2 (TBATE 236
   p6 again, bold italic): ``near_lines`` picks the dropped lines that sit in
   a paragraph of kept lines, so they are read again with a lower threshold.
"""
import re

import cv2
import numpy as np

# Background classification -------------------------------------------------

# A pixel belongs to the bubble interior when every channel is within this
# distance of the fitted background (flat colour or linear gradient).
BACKGROUND_TOLERANCE = 22
# Share of sampled background pixels that must match the fitted interior.
MIN_INTERIOR_SHARE = 0.86
MIN_SAMPLES = 40


def _line_mask(shape, quads):
    mask = np.zeros(shape[:2], np.uint8)
    for quad in quads:
        cv2.fillPoly(mask, [np.asarray(quad, np.int32).reshape(-1, 1, 2)], 255)
    return mask


def _fit_background(coords, values):
    """Least-squares plane per channel, refit once on inliers."""
    design = np.column_stack([coords, np.ones(len(coords))])
    keep = np.ones(len(coords), bool)
    for _ in range(2):
        solution, *_ = np.linalg.lstsq(design[keep], values[keep], rcond=None)
        residual = np.abs(values - design @ solution).max(axis=1)
        keep = residual <= BACKGROUND_TOLERANCE
        if keep.sum() < MIN_SAMPLES:
            break
    return residual


def classify_region(image, text_mask, quads, line_height=None):
    """Decide whether a text block sits on a clean interior or on artwork.

    ``image`` is RGB uint8, ``text_mask`` is the detector's raw text mask (same
    height/width, any non-zero value is text) and ``quads`` the block's
    text-line quadrilaterals.  Returns a dict with ``kind`` ("interior" or
    "art"), the measured ``interior_share`` and the sampled pixel count.

    Only the margin immediately around the text lines is sampled, excluding
    text pixels, so the outline of a bubble or the art beyond it barely
    influences a block that is centred in its bubble.  Uniform colours and
    smooth gradients count as interior; texture, drawings and faces do not.
    """
    quads = [np.asarray(q, np.float32).reshape(4, 2) for q in quads]
    if not quads:
        return {"kind": "art", "interior_share": 0.0, "samples": 0}
    h, w = image.shape[:2]
    if line_height is None:
        heights = [max(np.ptp(q[:, 1]), 1.0) for q in quads]
        line_height = float(np.median(heights))
    pad = int(max(4, round(line_height * 0.35)))
    lines = _line_mask(image.shape, quads)
    x0, y0 = np.floor(np.min([q.min(axis=0) for q in quads], axis=0)).astype(int) - pad
    x1, y1 = np.ceil(np.max([q.max(axis=0) for q in quads], axis=0)).astype(int) + pad
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
    if x1 <= x0 or y1 <= y0:
        return {"kind": "art", "interior_share": 0.0, "samples": 0}

    text = (text_mask > 0).astype(np.uint8) if text_mask is not None else np.zeros((h, w), np.uint8)
    # Lettering often carries a white or coloured outline that the detector
    # mask does not include; grow it in proportion to the line height.
    grow = int(max(5, round(line_height * 0.3))) | 1
    text = cv2.dilate(text, np.ones((grow, grow), np.uint8))
    # Glyph pixels the detector missed are removed by colour, below; the
    # quadrilaterals themselves are excluded except for their outer border.
    inner = cv2.erode(lines, np.ones((3, 3), np.uint8))
    sample = np.zeros((h, w), bool)
    sample[y0:y1, x0:x1] = True
    # Only the margin of the lines themselves: a block shaped like a staircase
    # (236 p32) has page or art in the empty corners of its bounding box.
    near = cv2.dilate(lines, np.ones((2 * pad + 1, 2 * pad + 1), np.uint8))
    sample &= (text == 0) & (inner == 0) & (near > 0)
    ys, xs = np.nonzero(sample)
    if len(xs) < MIN_SAMPLES:
        return {"kind": "art", "interior_share": 0.0, "samples": int(len(xs))}
    values = image[ys, xs].astype(np.float64)
    coords = np.column_stack([xs, ys]).astype(np.float64)
    residual = _fit_background(coords, values)
    share = float(np.mean(residual <= BACKGROUND_TOLERANCE))
    kind = "interior" if share >= MIN_INTERIOR_SHARE else "art"
    return {"kind": kind, "interior_share": round(share, 4), "samples": int(len(xs))}


# Text spacing ---------------------------------------------------------------

_CJK = re.compile(r"[　-ヿ㐀-鿿가-힯＀-￯]")
_LETTER = r"[^\W\d_]"


def has_cjk(text):
    return bool(_CJK.search(text or ""))


def normalize_spacing(text):
    """Safe punctuation spacing for alphabetic target languages.

    Adds the missing space after , ; : ! ? and after a sentence period followed
    by a capital letter; removes spaces before those marks; collapses runs of
    spaces.  Numbers ("3,5", "10:30"), ellipses and abbreviations followed by a
    lowercase letter are left alone, and meaning is never changed.
    """
    if not text or has_cjk(text):
        return text
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"(?<!-)--(?!-)", "—", text)  # "Eu--" -> "Eu—" (TBATE 199 p22)
    text = re.sub(r"[,;:]\s*(?=[.!?…—])", "", text)  # "da muralha,." (TBATE new p108)
    text = re.sub(r" +([,;:!?…])", r"\1", text)
    text = re.sub(r"(?<!\.) +\.(?!\.)", ".", text)
    text = re.sub(rf"(?<={_LETTER})([,;:])(?={_LETTER})", r"\1 ", text)
    text = re.sub(rf"([!?…]+)(?={_LETTER})", r"\1 ", text)
    text = re.sub(rf"(?<={_LETTER}{{2}})\.(?=[A-ZÀ-Ý])", ". ", text)
    text = re.sub(rf"^([.…]+) +(?={_LETTER})", r"\1", text.strip())  # "… mas" (TBATE 240 p30)
    return text


def _median_line(region):
    """Line height of a region; for stacked lines, no more than the distance between them.

    The detector sometimes draws overlapping, inflated line boxes (Grand Blue
    p27: 36 px boxes 28 px apart, next to a piece of the same bubble with 22 px
    boxes), which made one bubble look like two lettering sizes.
    """
    lines = np.asarray(region.lines, dtype=float)
    heights = [np.linalg.norm(q[3] - q[0]) for q in lines]
    if not heights:
        return 0.0
    height = float(np.median(heights))
    centres = sorted(q[:, 1].mean() for q in lines)
    pitch = [b - a for a, b in zip(centres, centres[1:]) if b - a > 0.5 * height]
    return min(height, float(np.median(pitch))) if pitch else height


def same_block(a, b, inside=None):
    """True when ``b`` is the next line(s) of ``a``'s speech, split off by the detector.

    The two pieces must be stacked (b right below a, at most about one line
    apart), overlap horizontally, have lettering of the same size, and, when
    ``inside`` is given, sit in the same bubble: ``inside(a, b)`` checks that
    on the page (OF 237 p62: "ALRIGHT, LET'S START THE REAL" / "TRAINING.").
    """
    ax0, ay0, ax1, ay1 = (float(v) for v in a.xyxy)
    bx0, by0, bx1, by1 = (float(v) for v in b.xyxy)
    ha, hb = _median_line(a), _median_line(b)
    if min(ha, hb) <= 0 or max(ha, hb) / min(ha, hb) > 1.6:
        return False
    line = min(ha, hb)
    stacked = -0.5 * line <= by0 - ay1 <= 0.9 * line and \
        min(ax1, bx1) - max(ax0, bx0) >= 0.5 * min(ax1 - ax0, bx1 - bx0)
    if not (stacked or same_row(a, b, line)):
        return False
    return inside is None or bool(inside(a, b))


def same_row(a, b, line):
    """``b`` continues ``a``'s last line to the right: "THE REAL" | "TRAINING" (OF 237 p62)."""
    bx0, by0, bx1, by1 = (float(v) for v in b.xyxy)
    last = max(np.asarray(a.lines, dtype=float), key=lambda q: q[:, 1].mean())
    lx0, ly0, lx1, ly1 = last[:, 0].min(), last[:, 1].min(), last[:, 0].max(), last[:, 1].max()
    shared = min(ly1, by1) - max(ly0, by0)
    gap = bx0 - lx1
    return shared >= 0.6 * line and -0.5 * line <= gap <= 1.2 * line


def join_blocks(regions, make, inside=None):
    """Merge stacked pieces of the same speech; ``make(a, b)`` builds the merged region."""
    regions = sorted(regions, key=lambda r: float(r.xyxy[1]))
    out = []
    for region in regions:
        for i, previous in enumerate(out):
            if same_block(previous, region, inside):
                out[i] = make(previous, region)
                break
        else:
            out.append(region)
    return out


def absorb_contained(regions, absorb, inside=None):
    """A small region whose centre lies inside a larger one is a line of that speech.

    Grand Blue p25: the tilted "LIKE" of "LOOKS / LIKE / IORI SCORED..." got its own
    region inside the bubble's region, so the bubble read "LOOKS IORI SCORED..."
    and a second "Tipo..." was written over it.  ``absorb(outer, inner)`` builds
    the merged region; ``inside(outer, inner)``, when given, must confirm they share a bubble.
    """
    out = list(regions)
    changed = True
    while changed:
        changed = False
        for inner in sorted(out, key=_area):
            ix0, iy0, ix1, iy1 = (float(v) for v in inner.xyxy)
            cx, cy = (ix0 + ix1) / 2, (iy0 + iy1) / 2
            for outer in out:
                ox0, oy0, ox1, oy1 = (float(v) for v in outer.xyxy)
                if outer is inner or _area(outer) <= 2 * _area(inner):
                    continue
                if ox0 <= cx <= ox1 and oy0 <= cy <= oy1 and (inside is None or inside(outer, inner)):
                    out = [r for r in out if r is not inner and r is not outer] + [absorb(outer, inner)]
                    changed = True
                    break
            if changed:
                break
    return out


def _area(region):
    x0, y0, x1, y1 = (float(v) for v in region.xyxy)
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def sentence_case(text, names=()):
    """Undo an answer written all in capitals, as the prompt asks for sentence case.

    TBATE new episode p74/p79: one bubble per page came back in capitals
    ("...SUA SUPPOSTA DIETA.") while the rest of the page was in sentence case.
    Sentence starts are capitalized again, and so are the ``names`` (glossary
    and names written with a capital elsewhere on the page).  Short shouts
    ("NÃO!", "PARE!") and text with no letters are left alone; "ISSO FOI..." is fixed.
    """
    letters = [c for c in text or "" if c.isalpha()]
    # A short hesitation ("EU...") is fixed too; a short shout ("NÃO!") is not.
    trailing = re.search(r"(\.\.|…)\W*$", text or "") and "!" not in (text or "")
    if (len(letters) < 6 and not (trailing and len(letters) >= 2)) or has_cjk(text) \
            or any(c.islower() for c in letters):
        return text
    out = text.lower()
    out = re.sub(r"(^|[.!?…]\s+|^[\W_]+)(\w)", lambda m: m.group(1) + m.group(2).upper(), out)
    for name in sorted({n for n in names if n and n[:1].isupper()}, key=len, reverse=True):
        out = re.sub(rf"(?<!\w){re.escape(name.lower())}(?!\w)", name, out)
    return out


# Words English and Portuguese share that are not names (kept lowercase when a caps answer is fixed).
COGNATES = {"real", "normal", "total", "final", "animal", "hotel", "mental", "natural", "legal",
            "general", "capital", "plan", "drama", "mana", "area", "idea", "radio", "virus", "zero",
            "super", "hobby", "show", "status", "chef", "bacon", "game", "online", "sexy", "sofa"}


def source_names(original, translation):
    """Words of the source the translation kept as they are: names ("QUEEN MERIAL!" -> "RAINHA MERIAL!").

    Used only to fix an answer written in capitals, where a name cannot be told
    from the other words by its capital letter (OF 238 p63 became "Rainha merial!").
    """
    words = set(re.findall(r"[A-Za-zÀ-ÿ]{4,}", original or ""))
    kept = (translation or "").lower()
    return {w[:1].upper() + w[1:].lower() for w in words
            if w.lower() not in COGNATES and re.search(rf"(?<![\wÀ-ÿ]){re.escape(w.lower())}(?![\wÀ-ÿ])", kept)}


def tidy_start(text, original="", names=()):
    """Fix how a translation starts.

    "M-ME LIGA assim que..." (TBATE 236 p30): a run of capitals at the start of
    an otherwise sentence-case answer becomes sentence case.  "...Sendo sonho ou
    não." (236 p34): when the source continues a sentence ("..DREAM OR NO DREAM"),
    the first word after the dots stays lowercase.
    """
    if not text or has_cjk(text):
        return text
    keep = {n for n in names if n and n[:1].isupper()}
    run = re.match(r"^([\W_]*)((?:[A-ZÀ-Ý]{1,3}-)?[A-ZÀ-Ý]{2,}(?:\s+[A-ZÀ-Ý]{2,})*)(?=\s+[a-zà-ÿ])", text)
    if run and any(c.islower() for c in text):
        words = run.group(2).split()
        fixed = [w.title() if w.title() in keep else w.lower() for w in words]
        first = fixed[0]
        fixed[0] = first[:1].upper() + first[1:]
        text = run.group(1) + " ".join(fixed) + text[run.end():]
    # A stutter keeps the word's own case: "E-Eu tô com medo" -> "E-eu" (TBATE 236 p12), "A-Arthur" stays.
    text = re.sub(r"(?<![\wÀ-ÿ])([A-ZÀ-Ý])-([A-ZÀ-Ý])([a-zà-ÿ][\wà-ÿ]*)",
                  lambda m: m.group(0) if (m.group(2) + m.group(3)) in keep or m.group(1).lower() != m.group(2).lower()
                  else f"{m.group(1)}-{m.group(2).lower()}{m.group(3)}", text)
    if re.match(r"^\s*(?:\.{2,}|…)", original or ""):
        cont = re.match(r"^(\s*(?:\.{2,}|…)\s*)([A-ZÀ-Ý])([a-zà-ÿ]+)", text)
        if cont and (cont.group(2) + cont.group(3)) not in keep:
            text = cont.group(1) + cont.group(2).lower() + cont.group(3) + text[cont.end():]
    return text


def page_names(translations):
    """Words written with a capital in the middle of a sentence elsewhere on the page."""
    names = set()
    for text in translations:
        if not text or text == text.upper():
            continue
        for match in re.finditer(r"(?<=[\w,;:] )([A-ZÀ-Ý][\wà-ÿ'-]+)", text):
            names.add(match.group(1))
    return names


def compact_symbols(original):
    """Wrap the engine's compact_special_symbols, keeping it for CJK only."""
    def compact(text):
        if has_cjk(text):
            return original(text)
        text = text.replace("...", "…").replace("..", "…")
        return normalize_spacing(text)
    return compact


def whole_word_breaker(original, string_width):
    """Wrap calc_horizontal so it never splits a word when hyphenation is off.

    The engine cuts any word wider than the box at an arbitrary letter, even
    with no_hyphenation=true.  Widening the measured box to the longest word
    keeps words whole; the rendered block is then scaled uniformly into the
    region, which reduces the font instead of breaking the word.
    """
    def calc_horizontal(font_size, text, max_width, max_height, language="en_US", hyphenate=True):
        if not hyphenate and text and not has_cjk(text):
            words = [word for word in re.split(r"\s+", text) if word]
            if words:
                longest = max(string_width(font_size, word) for word in words)
                max_width = max(max_width, longest)
        return original(font_size, text, max_width, max_height, language, hyphenate)
    return calc_horizontal


def broken_words(text, lines):
    """True when the laid-out lines do not keep every word of ``text`` whole."""
    return " ".join(lines).split() != text.split()


# Letter pixels enclosed by a flat background -----------------------------------

GLYPH_TOLERANCE = 40     # antialiased letter edges still differ this much from the interior
GLYPH_REACH = 1.5        # search window around the text, in line heights
GLYPH_NEAR = 0.8         # letters kept only this close to the text box, in line heights


def bubble_glyphs(image, box, line_height, near=GLYPH_NEAR):
    """Pixels of letters around ``box``: holes in the flat interior that surrounds the text.

    The detector mask misses parts of bold italic lettering (TBATE new episode
    p12: the T of "THIS", the end of "HARD", the whole line "OF US.").  Inside a
    bubble, every letter is a hole in the flat interior, whatever the detector
    saw.  Returns a boolean mask of the image size, empty when the text does not
    sit on a flat background.
    """
    h, w = image.shape[:2]
    out = np.zeros((h, w), bool)
    x0, y0, x1, y1 = (int(v) for v in box)
    lh = max(4.0, float(line_height))
    g = int(lh * GLYPH_REACH) + 4
    wx0, wy0, wx1, wy1 = max(0, x0 - g), max(0, y0 - g), min(w, x1 + g), min(h, y1 + g)
    window = image[wy0:wy1, wx0:wx1, :3].astype(int)
    if window.size == 0:
        return out
    # Interior colour: the most frequent colour around the text (bins of 24 levels).
    quant = window.reshape(-1, 3) // 24
    keys = quant[:, 0] * 10000 + quant[:, 1] * 100 + quant[:, 2]
    values, counts = np.unique(keys, return_counts=True)
    colour = np.median(window.reshape(-1, 3)[keys == values[counts.argmax()]], axis=0)
    flat = (np.abs(window - colour).max(axis=2) <= GLYPH_TOLERANCE).astype(np.uint8)
    # The interior: the largest flat component touching the text box.
    count, labels = cv2.connectedComponents(flat, connectivity=4)
    bx0, by0, bx1, by1 = x0 - wx0, y0 - wy0, x1 - wx0, y1 - wy0
    seeds = labels[by0:by1, bx0:bx1]
    seeds = seeds[seeds > 0]
    if seeds.size == 0:
        return out
    interior = labels == np.bincount(seeds).argmax()
    if interior[by0:by1, bx0:bx1].mean() < 0.35:
        return out
    # Holes: not interior and not reachable from the window border through non-interior pixels.
    outside = (~interior).astype(np.uint8)
    reach = np.zeros((outside.shape[0] + 2, outside.shape[1] + 2), np.uint8)
    reached = outside.copy()
    for y in range(outside.shape[0]):
        for x in (0, outside.shape[1] - 1):
            if reached[y, x] == 1:
                cv2.floodFill(reached, reach, (x, y), 2)
    for x in range(outside.shape[1]):
        for y in (0, outside.shape[0] - 1):
            if reached[y, x] == 1:
                cv2.floodFill(reached, reach, (x, y), 2)
    holes = reached == 1
    # Thin curves (the inner line of a double outline, TBATE new p5/p6) are holes
    # too, but not letters: long and almost empty inside their bounding box.
    # Letters have strokes; a hairline is at most a couple of pixels thick.
    count, labels, stats, _ = cv2.connectedComponentsWithStats(holes.astype(np.uint8), connectivity=8)
    depth = cv2.distanceTransform(holes.astype(np.uint8), cv2.DIST_L2, 3)
    thin = max(1.6, 0.05 * lh)
    for label in range(1, count):
        bw, bh, area = stats[label, 2], stats[label, 3], stats[label, 4]
        part = labels == label
        if depth[part].max() < thin or (max(bw, bh) > 1.5 * lh and area < 0.12 * bw * bh):
            holes[part] = False
    near = int(lh * near)
    keep = np.zeros_like(holes)
    keep[max(0, by0 - near):by1 + near, max(0, bx0 - near):bx1 + near] = True
    out[wy0:wy1, wx0:wx1] = holes & keep
    return out


# Line boxes from the detector mask -----------------------------------------

INK = 127
ROW_GAP = 2           # blank rows tolerated inside one line of lettering
SPLIT_FACTOR = 1.6    # a box this many times the usual line height may hold two lines
SPLIT_CHECK = 1.3     # boxes from this height up are checked for a second line the box only grazes
SPLIT_REACH = 0.6     # rows read past the box edge, in line heights
SPLIT_INSIDE = 0.25   # a row run must reach this far into the box to be one of its lines
MIN_PART = 0.45       # a split part shorter than this share of a line is noise
ORPHAN_COVERED = 0.2  # mask pixels already under a box above this share are not orphans
NEAR_LINES = 1.6      # an orphan line must sit this many line heights from a known one


def _box(points):
    pts = np.asarray(points, np.float32).reshape(-1, 2)
    x0, y0 = pts.min(axis=0)
    x1, y1 = pts.max(axis=0)
    return int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))


def _runs(flags, gap=ROW_GAP):
    runs, start, blank = [], None, 0
    for i, on in enumerate(flags):
        if on:
            if start is None:
                start = i
            blank = 0
        elif start is not None:
            blank += 1
            if blank > gap:
                runs.append((start, i - blank + 1))
                start, blank = None, 0
    if start is not None:
        runs.append((start, len(flags) - blank))
    return runs


def _line_height(boxes):
    heights = [y1 - y0 for x0, y0, x1, y1 in boxes if (x1 - x0) >= 1.5 * (y1 - y0) > 0]
    return float(np.median(heights)) if heights else None


def _covered(box, others):
    """Share of the box rows already covered by another box overlapping it horizontally."""
    x0, y0, x1, y1 = box
    rows = np.zeros(max(1, y1 - y0), bool)
    for ox0, oy0, ox1, oy1 in others:
        if min(x1, ox1) - max(x0, ox0) > 0.3 * (x1 - x0):
            rows[max(0, oy0 - y0):max(0, min(y1, oy1) - y0)] = True
    return float(rows.mean())


def _near(box, others, height):
    return any(min(box[2], b[2]) - max(box[0], b[0]) > 0.3 * min(box[2] - box[0], b[2] - b[0])
               and max(b[1] - box[3], box[1] - b[3]) <= NEAR_LINES * height for b in others)


def near_lines(lost, kept):
    """Indexes of dropped horizontal lines lying next to a kept line of similar height."""
    height = _line_height(kept) or _line_height(lost)
    if not height or not kept:
        return []
    return [i for i, (x0, y0, x1, y1) in enumerate(lost)
            if 0.5 * height <= y1 - y0 <= SPLIT_FACTOR * height and x1 - x0 > y1 - y0
            and _near((x0, y0, x1, y1), kept, height)]


def repair_lines(mask, boxes):
    """Return (boxes, changes) with multi-line boxes split and missed lines added.

    ``boxes`` are axis-aligned (x0, y0, x1, y1) horizontal text lines and
    ``mask`` is the detector pixel mask of the same page.  Each entry of the
    result is (box, source) where source is the index of the original box, or
    None for a line found only in the mask.
    """
    if mask is None or not boxes:
        return [(b, i) for i, b in enumerate(boxes)], []
    ink = np.asarray(mask)
    if ink.ndim == 3:
        ink = ink.max(axis=2)
    ink = ink > INK
    height = _line_height(boxes)
    if not height:
        return [(b, i) for i, b in enumerate(boxes)], []
    h, w = ink.shape
    result, changes = [], []
    for index, (x0, y0, x1, y1) in enumerate(boxes):
        x0, x1, y0, y1 = max(0, x0), min(w, x1), max(0, y0), min(h, y1)
        others = [b for j, b in enumerate(boxes) if j != index]
        # Vertical lettering (Japanese SFX, stacked letters) is never split into rows.
        if y1 - y0 < SPLIT_CHECK * height or x1 - x0 <= y1 - y0:
            result.append(((x0, y0, x1, y1), index))
            continue
        parts = []
        # A line the box cuts in half still counts (Grand Blue p25: one box over
        # "DON'T" and the top of "TELL ME"), so the rows are read a little past the box.
        reach = int(round(SPLIT_REACH * height))
        wy0, wy1 = max(0, y0 - reach), min(h, y1 + reach)
        for r0, r1 in _runs(ink[wy0:wy1, x0:x1].any(axis=1)):
            if r1 - r0 < MIN_PART * height or min(wy0 + r1, y1) - max(wy0 + r0, y0) < SPLIT_INSIDE * height:
                continue
            cols = np.flatnonzero(ink[wy0 + r0:wy0 + r1, x0:x1].any(axis=0))
            part = (x0 + int(cols[0]), wy0 + r0, x0 + int(cols[-1]) + 1, wy0 + r1)
            if _covered(part, others) < 0.5:
                parts.append(part)
        if len(parts) < 2 and y1 - y0 < SPLIT_FACTOR * height:
            result.append(((x0, y0, x1, y1), index))
            continue
        if len(parts) < 2 and y1 - y0 <= STAIR_FACTOR * height:
            # One box over two touching lines of a staircase caption (236 p32);
            # ink of the lines above and below, already boxed, is left out.
            own = ink[y0:y1, x0:x1].copy()
            # Their letters overflow the boxes a little, mostly sideways.
            side, edge = int(round(0.5 * height)), 2
            for ox0, oy0, ox1, oy1 in others:
                own[max(0, oy0 - edge - y0):max(0, oy1 + edge - y0),
                    max(0, ox0 - side - x0):max(0, ox1 + side - x0)] = False
            parts = stair_lines(own, x0, y0, height)
        if len(parts) >= 2:
            result.extend((part, index) for part in parts)
            changes.append(("split", (x0, y0, x1, y1), parts))
        else:
            result.append(((x0, y0, x1, y1), index))
    # Lines of the mask that no box covers.
    known = np.zeros_like(ink)
    for (x0, y0, x1, y1), _ in result:
        known[max(0, y0):y1, max(0, x0):x1] = True
    join = max(3, int(round(height * 0.6))) | 1
    lines = cv2.dilate(ink.astype(np.uint8), np.ones((1, join), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(lines, connectivity=8)
    current = [b for b, _ in result]
    lonely = []  # line-shaped orphans far from any box: kept only as a paragraph (below)
    for label in range(1, count):
        x, y, bw, bh = (int(v) for v in stats[label, :4])
        if not (0.5 * height <= bh <= STAIR_FACTOR * height and bw >= height):
            continue
        pixels = (labels[y:y + bh, x:x + bw] == label) & ink[y:y + bh, x:x + bw]
        if not pixels.any() or known[y:y + bh, x:x + bw][pixels].mean() > ORPHAN_COVERED:
            continue
        if bh > SPLIT_FACTOR * height:
            boxes_here = stair_lines(pixels, x, y, height)
        else:
            cols = np.flatnonzero(pixels.any(axis=0))
            boxes_here = [(x + int(cols[0]), y, x + int(cols[-1]) + 1, y + bh)]
        # The two halves of a staircase stand or fall together.
        if boxes_here and any(_near(b, current, height) for b in boxes_here):
            result.extend((box, None) for box in boxes_here)
            changes.append(("added", None, boxes_here))
        elif len(boxes_here) == 1:
            lonely.extend(boxes_here)
    paragraph = paragraph_lines(lonely, height)
    if paragraph:
        result.extend((box, None) for box in paragraph)
        changes.append(("added", None, paragraph))
    return result, changes


# Two columns of text side by side in one bubble --------------------------------

COLUMN_GAP = 0.3      # blank stripe through every line of a stack, in line heights
COLUMN_ROW_GAP = 0.6  # a line crossing the stripe has this much blank there
COLUMN_WORD_GAP = 2   # and that blank is this many times its widest word gap
INK_LEVEL = 110       # dark lettering on a light bubble


def _stacks(boxes):
    """Groups of line boxes stacked one under the other (overlapping horizontally)."""
    parent = list(range(len(boxes)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i, a in enumerate(boxes):
        for j in range(i + 1, len(boxes)):
            b = boxes[j]
            height = min(a[3] - a[1], b[3] - b[1])
            if max(a[1], b[1]) - min(a[3], b[3]) <= 0.8 * height and min(a[2], b[2]) > max(a[0], b[0]):
                parent[root(i)] = root(j)
    groups = {}
    for i in range(len(boxes)):
        groups.setdefault(root(i), []).append(i)
    return list(groups.values())


def column_cuts(gray, boxes):
    """{line index: (x0, x1)} for line boxes that run across two columns of text.

    Grand Blue p19 ("YOU / GOTTA / RELAX." beside "THERE'S NO POINT / TRYING / TO
    POWER / THROUGH / IT.") and p7 ("BOAT'S / FULL / UP." beside "SORRY / Y'ALL."):
    the detector drew one box over "YOU TO POWER", so the OCR read the two
    speeches interleaved.  A blank vertical stripe through a whole stack of lines,
    with lines on both sides of it, is the gutter between two columns when the
    lines it crosses have a much wider blank there than between their words.
    """
    gray = np.asarray(gray)
    cuts = {}
    for idx in _stacks(boxes):
        if len(idx) < 3:
            continue
        height = float(np.median([boxes[i][3] - boxes[i][1] for i in idx]))
        x0, x1 = min(boxes[i][0] for i in idx), max(boxes[i][2] for i in idx)
        ink = np.zeros((len(idx), x1 - x0), bool)
        for k, i in enumerate(idx):
            bx0, by0, bx1, by1 = boxes[i]
            ink[k, bx0 - x0:bx1 - x0] = (gray[by0:by1, bx0:bx1] < INK_LEVEL).any(axis=0)
        blank = ~ink.any(axis=0)
        best, x = None, 0
        while x < len(blank):
            if not blank[x]:
                x += 1
                continue
            start = x
            while x < len(blank) and blank[x]:
                x += 1
            if start == 0 or x >= len(blank) or x - start < COLUMN_GAP * height:
                continue
            left = {k for k in range(len(idx)) if ink[k, :start].any()}
            right = {k for k in range(len(idx)) if ink[k, x:].any()}
            both = left & right
            if not both or len(left) < 2 or len(right) < 2:
                continue
            ok = True
            for k in both:
                cols = np.flatnonzero(ink[k])
                last = cols[cols < start].max()
                first = cols[cols >= x].min()
                words = [b - a - 1 for a, b in zip(cols, cols[1:]) if b - a > 1 and not (a == last and b == first)]
                gap = first - last - 1
                if gap < COLUMN_ROW_GAP * height or (words and gap < COLUMN_WORD_GAP * max(words)):
                    ok = False
            if ok and (best is None or x - start > best[1] - best[0]):
                best = (start, x)
        if best:
            gx0, gx1 = x0 + best[0], x0 + best[1]
            for i in idx:
                if boxes[i][0] < gx0 and boxes[i][2] > gx1:
                    cuts[i] = (gx0, gx1)
    return cuts


def column_groups(boxes):
    """Line indexes split into columns that share no horizontal span, left to right; one group when not."""
    order = sorted(range(len(boxes)), key=lambda i: boxes[i][0])
    groups, right = [], None
    for i in order:
        if groups and boxes[i][0] < right:
            groups[-1].append(i)
            right = max(right, boxes[i][2])
        else:
            groups.append([i])
            right = boxes[i][2]
    return groups


DUPLICATE_OVERLAP = 0.6  # share of the smaller box inside the other one
DUPLICATE_SIZE = 0.5     # and the smaller box at least this share of the larger one


def duplicate_regions(boxes, texts):
    """Indices of regions that repeat another one over the same letters, worse read.

    Grand Blue 87 p45: the two lines of "GOT IT!" were also read as one box, OCR
    "8E"; both were translated and "Be" was written over "Entendi!".  Of two
    regions whose boxes mostly overlap, the one with fewer letters is dropped.
    """
    def letters(text):
        return len(re.findall(r"[^\W\d_]", text or ""))
    drop = set()
    for i, a in enumerate(boxes):
        for j in range(i + 1, len(boxes)):
            b = boxes[j]
            iw = min(a[2], b[2]) - max(a[0], b[0])
            ih = min(a[3], b[3]) - max(a[1], b[1])
            if iw <= 0 or ih <= 0:
                continue
            areas = ((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
            smaller, larger = min(areas), max(areas)
            # Two readings of the same letters cover about the same space; a small bubble
            # inside a big wrong box is another text (Grand Blue p55 lost "MUSCLE?" and "I SEE.").
            if smaller <= 0 or iw * ih < DUPLICATE_OVERLAP * smaller or smaller < DUPLICATE_SIZE * larger:
                continue
            # The worse reading has fewer letters for the space it covers: "8E" over both
            # lines of "GOT IT!", or "FULL YALL" stretched across two bubbles over "SORRY".
            def density(k):
                x0, y0, x1, y1 = boxes[k]
                return letters(texts[k]) / max(1, (x1 - x0) * (y1 - y0))
            drop.add(i if density(i) < density(j) else j)
    return drop


def paragraph_lines(boxes, height):
    """Orphan lines that stack into a paragraph of two or more lines.

    TBATE 240 p32: the whole "--THOUGH I / MAY OFFER SOME / SUGGESTIONS HERE /
    AND THERE." bubble was in the detector mask but had no line box, and no
    known line was near it.  One stray line far from text may be art; several
    lines of the same height stacked and centred on each other are lettering.
    """
    lines = sorted((b for b in boxes if 0.6 * height <= b[3] - b[1] <= 1.5 * height), key=lambda b: b[1])
    groups, kept = [], []
    for box in lines:
        for group in groups:
            last = group[-1]
            gap = box[1] - last[3]
            centre = abs((box[0] + box[2]) - (last[0] + last[2])) / 2
            if -0.3 * height <= gap <= 0.9 * height and centre <= 0.35 * max(box[2] - box[0], last[2] - last[0]):
                group.append(box)
                break
        else:
            groups.append([box])
    for group in groups:
        if len(group) >= 2:
            kept.extend(group)
    return kept


STAIR_FACTOR = 2.6  # an orphan this tall may be two touching lines


def stair_lines(pixels, x, y, height):
    """Two lines that touch, as in a staircase caption with a struck-out word.

    TBATE 236 p32: "THAT ENOUGH, GREY" (GREY struck out) touches "ARTHUR, AND"
    on the line below, shifted right; the mask joins them in one blob two
    lines tall.  Columns whose ink sits mostly in the top half go to the
    first line, the others to the second.  Returns [] unless each line gets a fair share of the blob.
    """
    rows = np.flatnonzero(pixels.any(axis=1))
    if not len(rows):
        return []
    # Work on the ink itself: a detector box may have a margin around it.
    y += int(rows[0])
    pixels = pixels[rows[0]:rows[-1] + 1]
    h, w = pixels.shape
    if h <= SPLIT_FACTOR * height:
        return []
    band = int(round(height))
    total = pixels.sum(axis=0)
    upper = (total > 0) & (pixels[:h // 2].sum(axis=0) >= 0.5 * total)
    lower = (total > 0) & ~upper
    boxes = []
    for cols, y0, y1 in ((np.flatnonzero(upper), 0, band), (np.flatnonzero(lower), h - band, h)):
        if len(cols) < height:
            return []
        rows = np.flatnonzero(pixels[y0:y1, cols[0]:cols[-1] + 1].any(axis=1))
        boxes.append((x + int(cols[0]), y + y0 + int(rows[0]), x + int(cols[-1]) + 1, y + y0 + int(rows[-1]) + 1))
    if boxes[0][2] - boxes[0][0] > 0.95 * w and boxes[1][2] - boxes[1][0] > 0.95 * w:
        return []  # one tall line or two stacked lines across the whole blob: not a staircase
    return boxes


# White bubbles the detector did not see ------------------------------------------

SCAN_WHITE = 200          # bubble interior is brighter than this
SCAN_INK = 110            # letters are darker than this
SCAN_AREA = (0.0015, 0.08)  # bubble area, as a fraction of the page
SCAN_SOLIDITY = 0.85      # filled outline over its convex hull: round or square, not a jagged burst
SCAN_INK_SHARE = (0.01, 0.25)
SCAN_CENTRE = (0.25, 0.3)  # text block centre within this share of the bubble width / height


def _text_rows(ink):
    """Line boxes when ``ink`` looks like rows of letters, else None.

    Letters are components of about one height, side by side in rows with no
    wide gap, rows stacked one under the other.  A face, hair or a hatched
    shadow fails one of those.
    """
    n, _, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    comps = [tuple(int(v) for v in stats[k]) for k in range(1, n) if stats[k][4] >= 6]
    if len(comps) < 2:
        return None
    med = float(np.median([c[3] for c in comps]))
    letters = [c for c in comps if 0.5 * med <= c[3] <= 1.6 * med and c[2] <= 2.5 * med]
    if sum(c[4] for c in letters) < 0.7 * sum(c[4] for c in comps):
        return None
    rows = []
    for c in sorted(letters, key=lambda c: c[1] + c[3] / 2):
        cy = c[1] + c[3] / 2
        for row in rows:
            if abs(row["cy"] - cy) <= 0.45 * med:
                row["c"].append(c)
                break
        else:
            rows.append({"cy": cy, "c": [c]})
    out, words = [], 0
    for row in rows:
        cs = sorted(row["c"], key=lambda c: c[0])
        gaps = [b[0] - (a[0] + a[2]) for a, b in zip(cs, cs[1:])]
        if gaps and max(gaps) > 1.5 * med:
            continue
        words += len(cs) >= 2
        out.append((min(c[0] for c in cs), min(c[1] for c in cs),
                    max(c[0] + c[2] for c in cs), max(c[1] + c[3] for c in cs)))
    if not words:
        return None
    out.sort(key=lambda b: b[1])
    if any(b[1] - a[3] > 1.2 * med for a, b in zip(out, out[1:])):
        return None
    return out


def bubble_text_lines(image, boxes):
    """Text lines inside white bubbles that no detected box touches.

    Grand Blue pp. 19/27: small bubbles "MUSCLE?", "I SEE.", "HOW'S THAT?" were
    missing from the detector mask, so they stayed in English.  A closed white
    area of bubble size, not touching the page edge and not jagged, whose dark
    pixels form centred rows of letters, is taken as an undetected bubble.
    Returns a list of (bubble box, line boxes, letter pixel mask of the page size).
    """
    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    raw = (gray > SCAN_WHITE).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    opened = cv2.morphologyEx(raw, cv2.MORPH_OPEN, kernel)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(opened, connectivity=4)
    found = []
    for i in range(1, n):
        x, y, bw, bh, area = (int(v) for v in stats[i])
        if not SCAN_AREA[0] * h * w <= area <= SCAN_AREA[1] * h * w:
            continue
        if x == 0 or y == 0 or x + bw >= w or y + bh >= h:
            continue
        # Back to the full white area the opening trimmed (thin strips between letters).
        g = 6
        x0, y0, x1, y1 = max(0, x - g), max(0, y - g), min(w, x + bw + g), min(h, y + bh + g)
        if any(min(x1, b[2]) > max(x0, b[0]) and min(y1, b[3]) > max(y0, b[1]) for b in boxes):
            continue
        comp = cv2.dilate((labels[y0:y1, x0:x1] == i).astype(np.uint8), kernel) & raw[y0:y1, x0:x1]
        contours, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        outline = max(contours, key=cv2.contourArea)
        filled = cv2.drawContours(np.zeros_like(comp), [outline], -1, 1, -1)
        if filled.sum() < SCAN_SOLIDITY * cv2.contourArea(cv2.convexHull(outline)):
            continue
        inner = cv2.erode(filled, np.ones((7, 7), np.uint8)) > 0
        ink = inner & (comp == 0) & (gray[y0:y1, x0:x1] < SCAN_INK)
        if not SCAN_INK_SHARE[0] <= ink.sum() / max(1, filled.sum()) <= SCAN_INK_SHARE[1]:
            continue
        rows = _text_rows(ink)
        if not rows:
            continue
        cw, ch = x1 - x0, y1 - y0
        tx = (min(r[0] for r in rows) + max(r[2] for r in rows)) / 2
        ty = (rows[0][1] + rows[-1][3]) / 2
        if abs(tx - cw / 2) > SCAN_CENTRE[0] * cw or abs(ty - ch / 2) > SCAN_CENTRE[1] * ch:
            continue
        letters = np.zeros((h, w), bool)
        letters[y0:y1, x0:x1] = ink
        found.append(((x0, y0, x1, y1), [(x0 + a, y0 + b, x0 + c, y0 + d) for a, b, c, d in rows], letters))
    return found


def reads_as_speech(text):
    """True when a scanned bubble's OCR text reads as an English line, not a drawn sound.

    A line has a common English word and either two words or end punctuation:
    "MUSCLE?", "I SEE." yes; "GRAB" (a sound in a jagged box) or "REEE" no.
    """
    common, _ = english_words()
    words = re.findall(r"[A-Za-z']+", text or "")
    if not words or not any(len(w) >= 2 and (w.lower() in common or w.lower().replace("'", "") in _contractions(common))
                            for w in words):
        return False
    return len(words) >= 2 or bool(re.search(r"[.!?…]\W*$", text.strip()))


# Words that show a woman or girl is on the page (speaker or listener).
FEMALE_EVIDENCE = re.compile(
    r"\b(?:she|her|hers|herself|girl|girls|woman|women|lady|ladies|queen|princess|sister|sis|mother|mom|"
    r"mommy|mama|miss|ma'?am|madam|daughter|wife|aunt|auntie|grandma|grandmother|niece|empress|"
    r"duchess|madame|mrs|ms|missus|bride|girlfriend|heroine|witch|goddess|nun|maid)\b", re.I)
# Feminine forms a speaker uses about themself or the listener.
FEMININE_SELF = re.compile(
    r"\b(?:mim|eu|você|si|te|me)\s+mesma\b|\bobrigada\b|"
    r"\b(?:estou|tô|sou|estava|fiquei|fico|ando|eu|você|está|tá|ficou|estar|ficar|parece)\s+"
    r"(?:muito\s+|tão\s+|bem\s+|meio\s+|um pouco\s+)?"
    r"(?:sozinha|cansada|preocupada|pronta|ocupada|grata|perdida|assustada|animada|nervosa|confusa|"
    r"orgulhosa|curiosa|ansiosa|interessada|convencida|machucada|ferida|arqueira|guerreira|"
    r"aluna|maga|sozinha)\b", re.I)

# A clear negation in the English line, and any negation in Portuguese.  Questions
# with n't ("isn't it great?", "why don't we") and idioms that lose the "not"
# ("can't wait") are left out.
# "DON'T", "DIDNT", "CAN'T" with or without the apostrophe, but not "WANT" or "EVENT".
NT = r"(?:do|does|did|is|are|was|were|has|have|had|could|would|should|must|might|need|ca|wo|ai|sha)n'?t"
SOURCE_NEGATION = re.compile(
    r"\b(?:not|never|nobody|nothing|none|neither|nor|no one|cannot|without)\b|\b" + NT + r"\b|\bno\s+\w", re.I)
NEGATION_IDIOMS = re.compile(
    r"\b" + NT + r"\b[^.!?]*\?|can'?t\s+wait|"
    r"nothing\s+but|not\s+only|no\s+(?:wonder|doubt|way)", re.I)
TARGET_NEGATION = re.compile(
    r"\b(?:não|nao|nunca|jamais|nem|nada|ninguém|nenhum\w*|sem|tampouco|mal)\b|"
    r"\b(?:desconhe\w*|incapa\w*|impossív\w*|inútil|inúteis|in\w+ável|in\w+ível)\b", re.I)


def added_negation(source, text):
    """True when the translation says "não"/"nunca" to an English line with no negation at all.

    TBATE 238 p42: "I WANT TO FIGHT IN THE WAR!" came back "Eu não quero lutar na
    guerra!", the meaning reversed.  Only a plain "não"/"nunca" before a verb counts;
    "nem", "nada" or "sem" are often how Portuguese says an English positive.
    """
    source = str(source or "")
    if not re.search(r"[A-Za-z]{2}", source) or SOURCE_NEGATION.search(source) or \
            re.search(r"\b(?:un\w+|\w+less|fail\w*|refus\w*|stop\w*|quit|lack\w*|deny|denied|hardly|barely|"
                      r"only|just|too|rather|as if|count me in|left out|miss\w*|lose|lost|forget|forgot\w*)\b",
                      source, re.I):
        return False
    return bool(re.search(r"\b(?:não|nunca|jamais)\b", text or "", re.I))


def lost_negation(source, text):
    """True when the English line says no/not/never and the translation says nothing negative.

    240 p32: "I'M UNFAMILIAR WITH..." read by OCR as "TM LINEAMILIAR" came back
    "Estou familiarizado", the meaning turned around.
    """
    source = re.sub(r"\s+", " ", str(source or "")).strip()
    if not SOURCE_NEGATION.search(source):
        return False
    rest = NEGATION_IDIOMS.sub(" ", source)
    if not SOURCE_NEGATION.search(rest):
        return False
    return not TARGET_NEGATION.search(text or "")


def _has(name, text):
    return re.search(rf"(?<![\wÀ-ÿ]){re.escape(name)}(?![\wÀ-ÿ])", text or "", re.I) is not None


def translation_problems(sources, translations, glossary=(), earlier=""):
    """Notes for a second try: dropped names and negations, feminine forms with no woman in sight.

    238 p64: "ARTHUR. ELEANOR. SYLVIE." came back "Arthur. E Sylvie."; 236 p32:
    "I TOLD MYSELF" became "eu disse a mim mesma" with Arthur narrating.
    ``earlier`` is the text of the previous pages, also evidence of a woman.
    Returns one note per problem, keyed by the 1-based region number.
    """
    from memory import normalize
    page = " ".join(str(s) for s in sources)
    female = bool(FEMALE_EVIDENCE.search(page + " " + earlier)) or any(
        g.get("gender") == "f" and f" {normalize(g['source'])} " in f" {normalize(page)} " for g in glossary)
    notes = []
    for number, (source, text) in enumerate(zip(sources, translations), 1):
        if not isinstance(text, str):
            continue
        here = f" {normalize(source)} "
        for g in glossary:
            target = g.get("target", "")
            key = normalize(g.get("source", ""))
            if key and target[:1].isupper() and f" {key} " in here and not _has(target, text):
                notes.append(f"<|{number}|> must keep the name {target}")
        if lost_negation(source, text):
            notes.append(f"<|{number}|> drops the negation of the original (not/no/never): keep the meaning")
        elif added_negation(source, text):
            notes.append(f"<|{number}|> says \"não\" but the original has no negation: keep the meaning")
        if not female:
            word = FEMININE_SELF.search(text)
            if word:
                notes.append(f"<|{number}|> uses the feminine \"{word.group(0)}\" but nothing shows a woman "
                             "here: rephrase without gender, or use the masculine")
    return notes


# OCR letter mix-ups in comic capitals -------------------------------------------

# What the OCR read -> what the letterer drew.  Only words the list does not know
# are touched, and only when exactly one common word comes out.
OCR_CONFUSIONS = (("LI", "U"), ("LJ", "U"), ("IJ", "U"), ("E", "F"), ("F", "E"), ("O", "D"), ("O", "C"), ("O", "Q"),
                  ("C", "D"), ("I", "D"), ("I", "L"), ("L", "I"), ("0", "O"), ("1", "I"), ("5", "S"),
                  ("7", "T"), ("8", "B"), ("/", "I"), ("|", "I"), ("VV", "W"), ("RN", "M"))
_WORDS = None


def english_words():
    """(common words, names) from the bundled SCOWL list (server/words); empty sets when missing."""
    global _WORDS
    if _WORDS is None:
        import gzip
        from pathlib import Path
        common, names, target = set(), set(), None
        try:
            with gzip.open(Path(__file__).resolve().parent / "words" / "en.txt.gz", "rt", encoding="utf-8") as f:
                target = common
                for line in f:
                    word = line.strip()
                    if word == "#names":
                        target = names
                    elif word:
                        target.add(word)
        except OSError:
            pass
        _WORDS = (common, names)
    return _WORDS


def _known(word, common, names):
    w = word.lower()
    return w in common or w in names or w in _contractions(common)


def _contractions(common, cache={}):
    if "set" not in cache:
        cache["set"] = {w.replace("'", "") for w in common if "'" in w}
    return cache["set"]


def _ocr_candidates(word, depth):
    found, frontier = set(), {word}
    for _ in range(depth):
        nxt = set()
        for w in frontier:
            for wrong, right in OCR_CONFUSIONS:
                start = w.find(wrong)
                while start >= 0:
                    nxt.add(w[:start] + right + w[start + len(wrong):])
                    start = w.find(wrong, start + 1)
        found |= nxt
        frontier = nxt
    return found


def fix_ocr_words(text, keep=()):
    """Undo letter mix-ups the OCR makes in comic capitals, word by word.

    TBATE 240 p32: "I'M UNFAMILIAR" was read "TM LINEAMILIAR" and translated
    "Estou familiarizado", the meaning reversed; Grand Blue p45 "PULLEO",
    TBATE 240 p34 "L/TTLE", "ANC".  A word is changed only when it is not an
    English word or a known name, is not in ``keep`` (the work's glossary), and
    exactly one common word comes out of one mix-up (two for words of 6+ letters).
    Returns (text, number of words changed).
    """
    common, names = english_words()
    if not text or not common:
        return text, 0
    keep = {k.lower() for k in keep}
    changed = 0

    # A word the letterer broke across lines: "ART- ISTRY", "STRAIN- ING", "CONVINC ING".
    parts = re.split(r"(\s+)", text)
    i = 0
    while i + 2 < len(parts):
        head, tail = parts[i], parts[i + 2]
        dash = head.endswith("-") and not head.endswith("--")
        h = head[:-1] if dash else head
        if re.fullmatch(r"[A-Z]{2,}", h) and re.fullmatch(r"[A-Z]{2,}\W*", tail):
            t = re.match(r"[A-Z]+", tail).group(0)
            whole = h + t
            if whole.lower() in common and (dash or t.lower() in SUFFIXES
                                            or not (_known(h, common, names) and _known(t, common, names))):
                parts[i:i + 3] = [whole + tail[len(t):]]
                changed += 1
                continue
            if dash and (t.lower() in HONORIFICS or (_known(h, common, names) and _known(t, common, names))):
                parts[i:i + 3] = [f"{h}-{tail}"]  # "AZUSA- SAN" -> "AZUSA-SAN", "HIGH- SCHOOL" -> "HIGH-SCHOOL"
                changed += 1
                continue
        i += 2
    text = "".join(parts)

    def repl(match):
        nonlocal changed
        word = match.group(0)
        letters = re.sub(r"[^A-Za-z]", "", word)
        noisy = re.search(r"[0-9/|]", word)  # "AC7", "/T": a digit or slash inside a word is the OCR's
        if word != word.upper() or len(letters) < (1 if noisy else 2) or word.lower() in keep:
            return word
        if word == "TM" and re.match(r"\s+[A-Z]", text[match.end():]):
            changed += 1
            return "I'M"
        core = word.strip("'")
        if len(core) < (2 if noisy else 4) or _known(core.replace("'", ""), common, names):
            return word
        for depth in (1, 2) if len(core) >= 6 else (1,):
            hits = {c for c in _ocr_candidates(core, depth) if c.lower() in common}
            if len(hits) == 1:
                changed += 1
                return word.replace(core, hits.pop())
            if hits:
                return word  # more than one word fits: leave it to the translator
        return word

    fixed = re.sub(r"[A-Za-z0-9/|']*[A-Za-z][A-Za-z0-9/|']*", repl, text)
    return fixed, changed


SUFFIXES = {"ing", "ed", "ly", "er", "ers", "est", "tion", "tions", "ness", "ment", "able", "ful", "less", "ous", "ity"}
HONORIFICS = {"san", "kun", "chan", "sama", "senpai", "sensei", "dono", "nim", "ssi", "hyung", "noona", "oppa", "unnie", "sunbae"}

SFX_SHAPE = re.compile(r"(.)\1\1|(?:OOSH|OOM|OOF|ASH|USH|ANG|ONK|ACK|UNK|RRK|SSH|HH|ZZ|WHAM|THUD|THUMP|SPLA\w*|KR\w+)$")


def english_sound_effect(text):
    """One lettered word that is no English word and looks like an onomatopoeia ("VLOOSH", "SPLOOSH").

    Grand Blue p53: "SPLOOSH", drawn across the art and read "VLOOSH", was erased
    and written as "Vluuuf".  Real words ("BOB", "NO!") are left to the translator.
    """
    words = re.findall(r"[A-Za-z]+", text or "")
    # A lone letter that is no word ("R", a piece of the vertical "KRRK" on Grand Blue
    # p19, was written over as "É.") is a piece of a drawn sound.
    if len(words) == 1 and len(words[0]) == 1 and words[0].upper() not in "IAO" \
            and not re.search(r"[?!]", text):
        return True
    if len(words) != 1 or len(words[0]) < 4 or words[0] != words[0].upper():
        return False
    common, names = english_words()
    word = words[0].lower()
    if not common or word in common or word in names:
        return False
    return bool(SFX_SHAPE.search(words[0]))
