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


STACKED = 2.5  # a line box this many times taller than wide holds letters stacked one per row


def stacked(quads):
    """True when every line box is a column of letters stacked one per row ("GUYS!" in a tall bubble)."""
    quads = [np.asarray(q, np.float32).reshape(4, 2) for q in quads]
    return bool(quads) and all(np.ptp(q[:, 1]) > STACKED * max(float(np.ptp(q[:, 0])), 1.0) for q in quads)


def classify_region(image, text_mask, quads, line_height=None):
    """Decide whether a text block sits on a clean interior or on artwork.

    ``image`` is RGB uint8, ``text_mask`` is the detector's raw text mask (same
    height/width, any non-zero value is text) and ``quads`` the block's
    text-line quadrilaterals.  Returns a dict with ``kind`` ("interior", "art",
    "contorno" for outlined lettering over the art, "tracos" for lettering on paper
    crossed by strokes of the drawing), the measured ``interior_share``, the sampled
    pixel count and the number of ``strokes`` crossing the margin.

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
        if stacked(quads):  # letters one per row: the line is as thick as the column is wide
            line_height = float(np.median([max(np.ptp(q[:, 0]), 1.0) for q in quads]))
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
    strokes = 0
    if kind == "interior":
        try:
            strokes = crossing_strokes(ys[residual > BACKGROUND_TOLERANCE], xs[residual > BACKGROUND_TOLERANCE],
                                       text | inner, near, pad, line_height)
        except Exception as exc:  # the decision by the background share stands
            print(f"Stroke check skipped: {type(exc).__name__}", flush=True)
        if strokes >= STROKE_CROSSINGS:
            kind = "tracos"
    # A sound effect is usually one outlined word over the art: it stays art (and goes to review).
    if kind == "art" and len(quads) >= OUTLINE_LINES and outlined_lettering(image, lines, line_height):
        kind = "contorno"
    return {"kind": kind, "interior_share": round(share, 4), "samples": int(len(xs)), "strokes": strokes}


# Lettering written straight on a white part of the drawing (hair, a sky with speed lines) has a
# margin that is mostly paper, but strokes of the drawing run across it into the text: the
# cleaning erased them with the letters (One Piece 1161 p5, Grand Blue 102 p35).  A
# bubble outline runs along the margin, a tail or a panel border crosses it once or twice.
# Such a block ("tracos") is still translated, but only its letters are cleaned (letters_area).
STROKE_CROSSINGS = 4  # strokes running across the margin, from the text to its outer edge, that make it art
STROKE_THIN = 0.3     # a stroke is at most this thick, in line heights (at least 2 px)


def crossing_strokes(ys, xs, text, near, pad, line_height):
    """Count the thin pieces of art that cross the sampled margin from the text to its outer edge.

    ``ys``/``xs`` are the margin pixels that do not match the interior; ``text`` marks the
    letters (grown) and ``near`` the outer limit of the margin.  A piece crosses when it touches
    both, and is thin when its area fits a stroke as long as the margin is wide.
    """
    if not len(xs):
        return 0
    h, w = text.shape[:2]
    y0, y1 = max(0, ys.min() - 1), min(h, ys.max() + 2)
    x0, x1 = max(0, xs.min() - 1), min(w, xs.max() + 2)
    off = np.zeros((y1 - y0, x1 - x0), np.uint8)
    off[ys - y0, xs - x0] = 1
    kernel = np.ones((3, 3), np.uint8)
    inner = cv2.dilate((text[y0:y1, x0:x1] > 0).astype(np.uint8), kernel) > 0
    outer = cv2.dilate((near[y0:y1, x0:x1] == 0).astype(np.uint8), kernel) > 0
    count, labels, stats, _ = cv2.connectedComponentsWithStats(off, connectivity=8)
    widest = pad * (max(2.0, STROKE_THIN * line_height) + 1)
    crossing = 0
    for label in range(1, count):
        if stats[label, cv2.CC_STAT_AREA] > widest:
            continue
        part = labels == label
        if (part & inner).any() and (part & outer).any():
            crossing += 1
    return crossing


def _quads_height(quads):
    """Median line height measured along the sides of the quads: a tilted box is taller than its letters."""
    return float(np.median([max(1.0, (np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2) for q in quads]))


LETTER_GROW = 2     # px around the letters cleaned with them (anti-aliased edges)
LETTER_REACH = 0.3  # letters are taken this far around the line boxes, in line heights (overhangs)
LETTER_SOFT = 0.15  # and their rim this far around them, in line heights...
LETTER_DARK = 100   # ...except pixels this much darker than the paper (0-255 grey): strokes of the drawing


HALO_REACH = 0.3    # an outline around the letters is looked for this far from them, in line heights
HALO_DELTA = 12     # and is this much (0-255 grey) further from the paper, on the side opposite to the letters


LETTER_WHOLE = 1.5  # a piece of ink up to this size (line heights) touching the mask is a letter, taken whole
LETTER_CHAIN = 0.4  # a letter this close beside a taken one, on the same row, is taken too (in line heights)
LETTER_STROKE = 0.6  # if its strokes are at least this share as thick as the letters' (hatching is thinner)


def whole_letters(image, letters, lines, paper, line_height):
    """``letters`` completed: every letter-sized piece of ink the detector mask touches, whole, and
    the letters right beside them on the same row.

    The detector mask is clipped to the line boxes: a tilted line (Grand Blue 106 p16, "IN
    WINTER?") lost the tops of its letters and its question mark, and they were left as an
    English ghost.  Long strokes of the drawing are larger than a letter, and hatching is
    thinner than the letters' strokes, so neither is taken.
    """
    lh = max(4.0, float(line_height))
    pixels = np.asarray(image)[:, :, :3].astype(int)
    window = cv2.dilate(lines.astype(np.uint8), np.ones((2 * int(lh) + 1, 2 * int(lh) + 1), np.uint8)) > 0
    ink = window & (np.abs(pixels - np.asarray(paper, int)).max(axis=2) > GLYPH_TOLERANCE)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    if count <= 1:
        return letters
    size = (stats[:, cv2.CC_STAT_WIDTH] <= LETTER_WHOLE * lh) & (stats[:, cv2.CC_STAT_HEIGHT] <= LETTER_WHOLE * lh)
    size[0] = False
    touched = np.zeros(count, bool)
    touched[np.unique(labels[letters & ink])] = True
    taken = touched & size
    if not taken.any():
        return letters
    depth = cv2.distanceTransform(ink.astype(np.uint8), cv2.DIST_L2, 3)
    thick = np.zeros(count)
    np.maximum.at(thick, labels.ravel(), depth.ravel())
    stroke = float(np.median(thick[taken]))
    gap = LETTER_CHAIN * lh
    grew = True
    while grew:
        grew = False
        for k in np.flatnonzero(size & ~taken & (thick >= LETTER_STROKE * stroke)):
            kx, ky, kw, kh = stats[k, :4]
            for t in np.flatnonzero(taken):
                tx, ty, tw, th = stats[t, :4]
                rows = min(ky + kh, ty + th) - max(ky, ty)
                apart = max(kx - (tx + tw), tx - (kx + kw))
                if rows >= 0.5 * min(kh, th) and apart <= gap:
                    taken[k] = grew = True
                    break
    return letters | taken[labels]


def letters_area(image, text_mask, quads, line_height=None):
    """Pixels of the letters (and their outline), the only part of the page cleaned for a "tracos" block.

    ``text_mask`` is the detector's raw text mask: it marks the letters and leaves out the
    hatching and strokes of the drawing around them (One Piece 1161 p5).  Only the mask near
    the line boxes counts, grown by LETTER_GROW px for the anti-aliased edges.  Dark letters
    with a light outline over a tinted page (cap146 p178) also take the outline: next to the
    letters, lighter than the paper by HALO_DELTA (darker, for light letters).
    """
    quads = [np.asarray(q, np.float32).reshape(4, 2) for q in quads]
    if text_mask is None or not quads:
        return np.zeros(np.asarray(image).shape[:2], bool)
    if line_height is None:
        line_height = _quads_height(quads)
    reach = 2 * int(max(1, round(LETTER_REACH * line_height))) + 1
    lines, paper = paper_under(image, quads, line_height)
    near = cv2.dilate(lines.astype(np.uint8), np.ones((reach, reach), np.uint8)) > 0
    letters = (np.asarray(text_mask) > INK) & near
    if letters.any():
        letters = whole_letters(image, letters, lines, paper, line_height)
        gray = cv2.cvtColor(np.ascontiguousarray(np.asarray(image)[:, :, :3]), cv2.COLOR_RGB2GRAY).astype(int)
        ground = int(cv2.cvtColor(paper.reshape(1, 1, 3).astype(np.uint8), cv2.COLOR_RGB2GRAY)[0, 0])
        ink = np.percentile(gray[letters], 10), np.percentile(gray[letters], 90)
        # The outline is on the other side of the paper from the letters: lighter for dark
        # letters.  Thin letters whose mask is mostly paper give no clear side: no outline.
        side = 1 if ground - ink[0] > 2 * HALO_DELTA else -1 if ink[1] - ground > 2 * HALO_DELTA else 0
        if side:
            halo = 2 * int(max(1, round(HALO_REACH * line_height))) + 1
            around = cv2.dilate(letters.astype(np.uint8), np.ones((halo, halo), np.uint8)) > 0
            letters |= around & (side * (gray - ground) > HALO_DELTA)
    grow = 2 * LETTER_GROW + 1
    area = cv2.dilate(letters.astype(np.uint8), np.ones((grow, grow), np.uint8)) > 0
    if letters.any():
        # The anti-aliased rim is wider than LETTER_GROW on large letters, and the cleaner drew
        # it back as a ghost next to a wall (Grand Blue 106 p16): a little further out, the
        # pixels that are not dark strokes of the drawing are cleaned too.
        soft = 2 * int(max(1, round(LETTER_SOFT * line_height))) + 1
        area |= (cv2.dilate(letters.astype(np.uint8), np.ones((soft, soft), np.uint8)) > 0) & (gray >= ground - LETTER_DARK)
    return area


PAPER_LIGHT = 200   # a light page is brighter than this (0-255 grey)...
PAPER_CLEAN = 2     # ...with no darker pixel this close (px): the white between screentone dots is not paper
PAPER_SHARE = 0.45  # share of the margin around the lines that is clean paper, for a speech over the drawing
PAPER_CONTRAST = 2 * HALO_DELTA  # and the letters are this much darker than the page
PAPER_MASKED = 0.85  # share of the ink on the lines inside the detector mask: only the letters it marks are cleaned
PAPER_INK = 60       # ink on the lines is this much darker than the page (0-255 grey)
PAPER_DOT = 0.2      # specks smaller than this squared (line heights) are screentone, not letters
PAPER_TILT = 3.0     # degrees: tilted lettering (a sheet of paper drawn askew) is written back level, over half-cleaned lines


def speech_on_paper(image, text_mask, quads, line_height=None):
    """True for dark letters on clean paper, crossed by the drawing.

    Such a speech (One Piece 1161 p5, "WELL, CONSIDERING...": hair and hatching between the
    lines) is classified as art by its margin, but cleaning only its letters (letters_area)
    keeps the drawing.  Letters with a white outline over screentone (Grand Blue 102 p7) look
    light around the lines, but the white between the dots is not paper: cleaning them left a
    smudge on the tone.  Those, a dark or mid-tone background and light letters stay as drawn.
    So do letters the detector mask misses (a tilted line, Grand Blue 106 p16: an English ghost
    was left under the translation) and two speeches side by side in one block (Grand Blue 102
    p33: their lines interleave and one of them sits on the hair), and tilted lettering (Grand
    Blue 102 p4, a form drawn askew: the boxes missed part of it and English was left), and
    letters stacked one per row in a tall bubble (Grand Blue 102 p20).
    """
    quads = [np.asarray(q, np.float32).reshape(4, 2) for q in quads]
    if text_mask is None or not quads:
        return False
    if line_height is None:
        line_height = _quads_height(quads)
    lines, paper = paper_under(image, quads, line_height)
    pad = int(max(4, round(line_height * 0.35)))
    margin = (cv2.dilate(lines.astype(np.uint8), np.ones((2 * pad + 1, 2 * pad + 1), np.uint8)) > 0) & ~lines
    letters = (np.asarray(text_mask) > INK) & lines
    if not margin.any() or not letters.any():
        return False
    gray = cv2.cvtColor(np.ascontiguousarray(np.asarray(image)[:, :, :3]), cv2.COLOR_RGB2GRAY).astype(int)
    ground = int(cv2.cvtColor(paper.reshape(1, 1, 3).astype(np.uint8), cv2.COLOR_RGB2GRAY)[0, 0])
    size = 2 * PAPER_CLEAN + 1
    clean = cv2.erode(gray.astype(np.uint8), np.ones((size, size), np.uint8)) > PAPER_LIGHT
    if clean[margin].mean() < PAPER_SHARE or ground - np.median(gray[letters]) <= PAPER_CONTRAST:
        return False
    ink = lines & (gray < ground - PAPER_INK)
    # Screentone dots of a wall the line box runs onto (Grand Blue 106 p16) are not missed letters.
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    dots = stats[:, cv2.CC_STAT_AREA] < (PAPER_DOT * line_height) ** 2
    dots[0] = False
    ink &= ~dots[labels]
    marked = whole_letters(image, np.asarray(text_mask) > INK, lines, paper, line_height)
    marked = cv2.dilate(marked.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    if ink.any() and marked[ink].mean() < PAPER_MASKED:
        return False
    tilt = np.median([abs(np.degrees(np.arctan2(q[1, 1] - q[0, 1], q[1, 0] - q[0, 0]))) for q in quads])
    if tilt > PAPER_TILT:
        return False
    if any(np.ptp(q[:, 1]) > np.ptp(q[:, 0]) for q in quads):
        return False  # letters stacked one per row (Grand Blue 102 p20 "GUYS!"): the lettering would be tiny
    boxes = [(q[:, 0].min(), q[:, 1].min(), q[:, 0].max(), q[:, 1].max()) for q in quads]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            rows = min(a[3], b[3]) - max(a[1], b[1])
            if rows > 0.5 * min(a[3] - a[1], b[3] - b[1]) and min(a[2], b[2]) <= max(a[0], b[0]):
                return False  # two lines side by side: two speeches in one block
    return True


def paper_under(image, quads, line_height=None):
    """(line boxes, paper colour around them) of a "tracos" block.

    The strokes of the drawing that crossed the old letters stay on the cleaned page and cut
    the space the new lettering looks for; the block painted with the paper colour gives it
    back (only on a copy used to plan the lettering).
    """
    quads = [np.asarray(q, np.float32).reshape(4, 2) for q in quads]
    if line_height is None:
        line_height = _quads_height(quads)
    pad = int(max(4, round(line_height * 0.35)))
    lines = _line_mask(image.shape, quads) > 0
    margin = (cv2.dilate(lines.astype(np.uint8), np.ones((2 * pad + 1, 2 * pad + 1), np.uint8)) > 0) & ~lines
    pixels = np.asarray(image)[:, :, :3]
    colour = np.median(pixels[margin], axis=0) if margin.any() else np.array([255, 255, 255])
    return lines, colour.round().astype(pixels.dtype)


OUTLINE_LIGHT = 190    # letter fill of outlined lettering is lighter than this
OUTLINE_DARK = 130     # and its outline darker than this (black, or black over a screentone)
OUTLINE_RING = 0.85    # share of the ring around a letter that is outline
OUTLINE_WIDTH = 0.06   # outline thickness checked, in line heights (at least 2 px)
OUTLINE_REACH = 0.6    # the letters and their outline are looked for this far around the lines, in line heights
OUTLINE_SHARE = 0.6    # share of the light pixels on the lines that are outlined letters
OUTLINE_AROUND = 0.5   # at most this share of the page around them is light
OUTLINE_LINES = 2      # outlined lettering is translated only as a sentence of this many lines or more


def outlined_colours(image, quads):
    """(letter colour, outline colour) of outlined lettering, measured on the page."""
    quads = [np.asarray(q, np.float32).reshape(4, 2) for q in quads]
    lines = _line_mask(image.shape, quads) > 0
    gray = cv2.cvtColor(np.asarray(image)[:, :, :3], cv2.COLOR_RGB2GRAY)
    near = cv2.dilate(lines.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    fill, edge = lines & (gray > OUTLINE_LIGHT), near & (gray < OUTLINE_DARK)
    if not fill.any() or not edge.any():
        return (255, 255, 255), (0, 0, 0)
    return (tuple(int(v) for v in np.median(image[fill][:, :3], axis=0)),
            tuple(int(v) for v in np.median(image[edge][:, :3], axis=0)))


def outlined_area(image, quads, line_height=None):
    """Pixels of outlined lettering and its outline, the only part of the page cleaned for it."""
    quads = [np.asarray(q, np.float32).reshape(4, 2) for q in quads]
    if line_height is None:
        line_height = float(np.median([max(np.ptp(q[:, 1]), 1.0) for q in quads]))
    found = outlined_lettering(image, _line_mask(image.shape, quads), line_height, area_only=True)
    return found if found is not None else np.zeros(image.shape[:2], bool)


def outlined_lettering(image, lines, line_height, area_only=False):
    """True for light letters wrapped in their own dark outline (a shout lettered over the art).

    Grand Blue 102 p31: white letters with a thick black outline over a dark, toned
    background.  Every letter, with its outline, is its own interior: cleaning the
    letter and the outline only leaves the art around them as drawn.  Dark letters
    drawn straight on the art have no such outline and stay art.
    """
    gray = cv2.cvtColor(np.asarray(image)[:, :, :3], cv2.COLOR_RGB2GRAY) if image.ndim == 3 else np.asarray(image)
    on_lines = lines > 0
    if not on_lines.any():
        return None if area_only else False
    lh = max(4.0, float(line_height))
    width = max(2, int(round(OUTLINE_WIDTH * lh)))
    reach = max(width + 2, int(round(OUTLINE_REACH * lh)))
    area = cv2.dilate(lines, np.ones((2 * reach + 1, 2 * reach + 1), np.uint8)) > 0
    edge = area & ~(cv2.erode(area.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0)
    light = gray > OUTLINE_LIGHT
    count, labels, stats, _ = cv2.connectedComponentsWithStats((light & area).astype(np.uint8), connectivity=8)
    # The page between dark letters, or a light background, runs out to the edge of the area.
    open_labels = set(np.unique(labels[edge & light]).tolist())
    kernel = np.ones((2 * width + 1, 2 * width + 1), np.uint8)
    letters = np.zeros_like(light)
    for k in range(1, count):
        if k in open_labels or stats[k, 4] < (0.1 * lh) ** 2:
            continue
        x, y, w, h = (int(v) for v in stats[k, :4])
        x0, y0 = max(0, x - width - 1), max(0, y - width - 1)
        piece = labels[y0:y + h + width + 1, x0:x + w + width + 1] == k
        ring = (cv2.dilate(piece.astype(np.uint8), kernel) > 0) & ~light[y0:y + h + width + 1, x0:x + w + width + 1]
        if ring.any() and np.mean(gray[y0:y + h + width + 1, x0:x + w + width + 1][ring] < OUTLINE_DARK) >= OUTLINE_RING:
            letters[y0:y + h + width + 1, x0:x + w + width + 1] |= piece
    if area_only:  # the letters and their outline, grown like the outline itself
        return cv2.dilate(letters.astype(np.uint8), np.ones((4 * width + 1, 4 * width + 1), np.uint8)) > 0
    lit = (light & on_lines).sum()
    if not lit or (letters & on_lines).sum() < OUTLINE_SHARE * lit:
        return False
    # Light letters over a light page are the holes of dark letters in a white bubble, not outlined lettering.
    around = area & ~(cv2.dilate(letters.astype(np.uint8), np.ones((4 * width + 1, 4 * width + 1), np.uint8)) > 0)
    return bool(around.any()) and float(light[around].mean()) < OUTLINE_AROUND


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
    text = text.replace("\u2011", "-")  # no glyph in the lettering font
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
CLEAN_MARK = 0.4         # a punctuation dot is smaller than this, in line heights (a lower-case letter is not)


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


def glyphs_to_clean(image, box, line_height):
    """Letters around a text box to add to the cleaning mask, grown like the detector's own mask.

    Grown by about a quarter of the line height: with a thin margin the cleaner left a
    grey ghost of the anti-aliased letter edges (TBATE new episode p12, "OF US.").  The
    growth stays near the text box, never reaching the bubble outline, but a letter of the
    box (its centre inside) that the margin cuts is taken whole, and so are the dots of
    punctuation that follow the line or sit on the row under it: the dots of "..." past the box stayed as a grey
    smudge (Grand Blue 102 p42/p20).  A word past the box, or another line, is never
    taken: it was not read, and erasing it would lose the speech.
    """
    h, w = image.shape[:2]
    lh = max(4.0, float(line_height))
    glyphs = bubble_glyphs(image, box, lh, near=NEAR_LINES)
    if not glyphs.any():
        return glyphs
    size = max(5, int(round(lh * 0.25)) | 1)
    x0, y0, x1, y1 = (int(v) for v in box)
    limit = np.zeros((h, w), bool)
    limit[max(0, y0 - size):min(h, y1 + size), max(0, x0 - size):min(w, x1 + size)] = True
    count, labels, stats, _ = cv2.connectedComponentsWithStats(glyphs.astype(np.uint8), connectivity=8)
    def belongs(label, near_taken, grow=False):
        gx, gy, gw, gh = (int(v) for v in stats[label, :4])
        mark = gh < CLEAN_MARK * lh and gw < CLEAN_MARK * lh
        if near_taken and y0 <= gy + gh / 2 <= y1 and (mark or (not grow and x0 <= gx + gw / 2 <= x1)):
            return True  # a letter of the box the margin cuts, or a dot of punctuation within a letter gap
        # A dot of punctuation on the row just under the line ("SORRY / ...").
        return mark and 0 <= gy - y1 <= lh and x0 <= gx and gx + gw <= x1
    box_limit = limit.copy()
    queue = [k for k in set(np.unique(labels[limit & glyphs]).tolist()) - {0} if belongs(k, True)]
    below = [k for k in range(1, count) if k not in queue and belongs(k, False)]
    if below:
        # Only a row of dots alone: a letter on the same row makes it a line of text that was not read.
        r0, r1 = min(stats[k, 1] for k in below), max(stats[k, 1] + stats[k, 3] for k in below)
        if any(stats[k, 1] < r1 and stats[k, 1] + stats[k, 3] > r0 and k not in below and k not in queue
               for k in range(1, count)):
            below = []
    queue += below
    taken = set(queue)
    while queue:
        k = queue.pop()
        gx, gy, gw, gh = (int(v) for v in stats[k, :4])
        limit[max(0, gy - size):min(h, gy + gh + size), max(0, gx - size):min(w, gx + gw + size)] = True
        for label in set(np.unique(labels[limit & glyphs]).tolist()) - taken - {0}:
            if belongs(label, True, grow=True):
                taken.add(label)
                queue.append(label)
    kernel = np.ones((size, size), np.uint8)
    whole = cv2.dilate(np.isin(labels, list(taken)).astype(np.uint8), kernel) > 0
    # Letters of the lines above and below: only what reaches into the box margin, as before.
    return (whole & limit) | ((cv2.dilate(glyphs.astype(np.uint8), kernel) > 0) & box_limit)


def drawn_marks(image, boxes):
    """Pixels of the drawings inside ``boxes``, line boxes the OCR read as one letter repeated.

    A symbol drawn under the speech (an anger vein, a broken heart: One Piece 1161 p16) gets
    a line box from the detector mask, and the OCR reads it as "JJJJ".  It is not text: the
    mask of the line above still covered its top, and the cleaner smeared the rest over the
    bubble.  Returns the ink inside the bubble whose centre falls in one of the boxes, grown
    by a pixel, to be left out of the cleaning mask whole.
    """
    h, w = image.shape[:2]
    keep = np.zeros((h, w), bool)
    for x0, y0, x1, y1 in boxes:
        glyphs = bubble_glyphs(image, (x0, y0, x1, y1), max(4.0, float(y1 - y0)))
        count, labels, stats, centres = cv2.connectedComponentsWithStats(glyphs.astype(np.uint8), connectivity=8)
        for label in range(1, count):
            cx, cy = centres[label]
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                keep |= labels == label
    if keep.any():
        keep = cv2.dilate(keep.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    return keep


THROUGH_DARK = 135    # line art is darker than this (0-255; thin anti-aliased lines reach ~130)
THROUGH_REACH = 1.5   # a line is followed this far outside the mask, in line heights
THROUGH_RUN = 1.0     # and must continue at least this far on each side of the text, in line heights
THROUGH_THIN = 0.3    # at most this thick, in line heights (a panel border)
THROUGH_AIM = 0.15    # each side, carried straight across the text, meets the other within this, in line heights


def through_lines(image, mask, box, line_height):
    """Straight art lines, like a panel border, that the cleaning mask cuts where they cross the text.

    Text written on the page often runs over the border of a panel; the detector marks the
    bits of line between the letters, and the cleaning erased the border and joined the two
    panels (Grand Blue 102 p3).  A thin dark line that leaves the mask on two opposite sides,
    both sides on one straight line, is art.  Returns ``[((xa, ya), (xb, yb), thickness, grey)]``
    in page coordinates, to draw back with ``redraw_lines`` after the lettering.  A stroke
    that ends among the letters may be part of them, and a curved line (a bubble outline)
    is not rebuilt under the letters.
    """
    lh = max(4.0, float(line_height))
    h, w = mask.shape[:2]
    reach = int(round(THROUGH_REACH * lh)) + 2
    x0, y0, x1, y1 = (int(v) for v in box)
    wx0, wy0, wx1, wy1 = max(0, x0 - reach), max(0, y0 - reach), min(w, x1 + reach), min(h, y1 + reach)
    if wx1 <= wx0 or wy1 <= wy0:
        return []
    m = np.asarray(mask)[wy0:wy1, wx0:wx1] > 0
    if not m.any():
        return []
    gray = cv2.cvtColor(np.ascontiguousarray(np.asarray(image)[wy0:wy1, wx0:wx1, :3]), cv2.COLOR_RGB2GRAY)
    near = cv2.dilate(m.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    dist = cv2.distanceTransform((~m).astype(np.uint8), cv2.DIST_L2, 3)
    outside = (gray < THROUGH_DARK) & ~m & (dist <= reach)
    count, labels = cv2.connectedComponents(outside.astype(np.uint8), connectivity=8)
    ends = []
    for k in range(1, count):
        ys, xs = np.nonzero(labels == k)
        touch = near[ys, xs]
        if not touch.any() or len(xs) < 3:
            continue
        pts = np.stack([xs, ys], 1).astype(np.float64)
        axis = np.linalg.svd(pts - pts.mean(0), full_matrices=False)[2][0]
        along = (pts - pts.mean(0)) @ axis
        length = float(along.max() - along.min() + 1)
        thick = len(pts) / length
        if length >= THROUGH_RUN * lh and thick <= THROUGH_THIN * lh:
            ends.append((pts, axis, pts[touch].mean(0), thick, float(np.median(gray[ys, xs]))))
    def miss(end, point):
        # Distance from ``point`` to the end's own line, carried straight on.
        offset = point - end[0].mean(0)
        return abs(offset[0] * end[1][1] - offset[1] * end[1][0])
    pairs = []
    for i in range(len(ends)):
        for j in range(i + 1, len(ends)):
            a, b = ends[i][2], ends[j][2]
            chord = b - a
            if np.linalg.norm(chord) < lh:
                continue
            steps = np.linspace(0, 1, max(2, int(np.linalg.norm(chord))))
            xs, ys = np.round(a[None] + steps[:, None] * chord[None]).astype(int).T
            if m[ys, xs].mean() < 0.5:
                continue  # both ends on the same side of the text
            err = max(miss(ends[i], b), miss(ends[j], a))
            if err <= THROUGH_AIM * lh:
                pairs.append((err, i, j))
    lines, used = [], set()
    for _, i, j in sorted(pairs):  # the straightest first
        if i in used or j in used:
            continue
        used |= {i, j}
        pts = np.concatenate([ends[i][0], ends[j][0]])
        centre = pts.mean(0)
        axis = np.linalg.svd(pts - centre, full_matrices=False)[2][0]
        # From one contact to the other, on the line fitted to both sides, overlapping them a little.
        ta, tb = sorted(float((ends[k][2] - centre) @ axis) for k in (i, j))
        pa, pb = centre + (ta - 2) * axis, centre + (tb + 2) * axis
        lines.append(((pa[0] + wx0, pa[1] + wy0), (pb[0] + wx0, pb[1] + wy0),
                      (ends[i][3] + ends[j][3]) / 2, (ends[i][4] + ends[j][4]) / 2))
    return lines


REDRAW_GAP = 2        # px of paper left between a line drawn back and the new letters, as around the original ones


def redraw_lines(rendered, clean, mask, lines):
    """Draw ``through_lines`` back on the finished page, inside the cleaned area and a little apart from the new letters."""
    if not lines:
        return rendered
    draw = np.zeros(rendered.shape[:2], bool)
    shade = np.zeros(rendered.shape[:2], np.uint8)
    for (xa, ya), (xb, yb), thick, grey in lines:
        axis = np.zeros(rendered.shape[:2], np.uint8)
        cv2.line(axis, (int(round(xa)), int(round(ya))), (int(round(xb)), int(round(yb))), 255, 1)
        # As wide as measured: cv2's own thickness draws wider than asked.
        band = cv2.distanceTransform((axis == 0).astype(np.uint8), cv2.DIST_L2, 3) <= (max(1, round(thick)) - 1) / 2
        shade[band] = int(round(grey))
        draw |= band
    lettered = np.any(rendered[:, :, :3] != clean[:, :, :3], axis=2).astype(np.uint8)
    gap = 2 * REDRAW_GAP + 1
    draw &= (np.asarray(mask) > 0) & (cv2.dilate(lettered, np.ones((gap, gap), np.uint8)) == 0)
    out = rendered.copy()
    out[draw, :3] = shade[draw][:, None]
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
ORPHAN_MIN = 0.5      # an orphan line is at least this many line heights tall
SMALL_LINE = 0.3      # smaller orphans, from this many line heights, may still be a paragraph of small lettering
SMALL_LINE_PX = 8     # never below this height in pixels
SMALL_LINE_WIDTH = 1.5  # and their ink is this many times wider than tall: a lone letter is not a line
FIT_SIDE = 0.3        # ink running past the box end this far (line heights) widens the box
FIT_OVERLAP = 0.5     # boxes sharing this many line heights of rows are cut again line by line
FIT_TALL = 2.0       # boxes are cut again only when one of them is this many line heights tall
FIT_VALLEY = 0.12     # a row with less ink than this share of a line's usual row is a gap between lines
FIT_GAP = 0.3         # a box grows over letters at most this far (line heights) from its own


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


def repair_lines(mask, boxes, gray=None):
    """Return (boxes, changes) with multi-line boxes split and missed lines added.

    ``boxes`` are axis-aligned (x0, y0, x1, y1) horizontal text lines and
    ``mask`` is the detector pixel mask of the same page.  Each entry of the
    result is (box, source) where source is the index of the original box, or
    None for a line found only in the mask.  ``gray``, the page in grey levels,
    lets a line box grow over letters the mask missed.
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
    result = fit_lines(ink, result, height, changes, gray)
    # Lines of the mask that no box covers.
    known = np.zeros_like(ink)
    for (x0, y0, x1, y1), _ in result:
        known[max(0, y0):y1, max(0, x0):x1] = True
    join = max(3, int(round(height * 0.6))) | 1
    lines = cv2.dilate(ink.astype(np.uint8), np.ones((1, join), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(lines, connectivity=8)
    current = [b for b, _ in result]
    lonely = []  # line-shaped orphans far from any box: kept only as a paragraph (below)
    small = []   # lines in smaller letters than the page's (a quiet bubble beside a shout): same rule
    for label in range(1, count):
        x, y, bw, bh = (int(v) for v in stats[label, :4])
        if max(SMALL_LINE_PX, SMALL_LINE * height) <= bh < ORPHAN_MIN * height:
            # The component was widened to join the letters; the line shape is read on the ink itself.
            pixels = (labels[y:y + bh, x:x + bw] == label) & ink[y:y + bh, x:x + bw]
            cols = np.flatnonzero(pixels.any(axis=0))
            if len(cols) and cols[-1] - cols[0] + 1 >= SMALL_LINE_WIDTH * bh \
                    and known[y:y + bh, x:x + bw][pixels].mean() <= ORPHAN_COVERED:
                small.append((x + int(cols[0]), y, x + int(cols[-1]) + 1, y + bh))
            continue
        if not (ORPHAN_MIN * height <= bh <= STAIR_FACTOR * height and bw >= height):
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
    # Grand Blue 102 p39: the page height came from big shouting, so small lines are
    # measured on their own height, each size in turn.
    for size in sorted({b[3] - b[1] for b in small}):
        paragraph += [b for b in paragraph_lines(small, float(size)) if b not in paragraph]
    if paragraph:
        result.extend((box, None) for box in paragraph)
        changes.append(("added", None, paragraph))
    return result, changes


def _line_runs(ink, box, height):
    """Row runs of ink a box takes part in, read a little past its top and bottom."""
    h = ink.shape[0]
    x0, y0, x1, y1 = box
    reach = int(round(SPLIT_REACH * height))
    wy0, wy1 = max(0, y0 - reach), min(h, y1 + reach)
    runs = []
    for r0, r1 in _runs(ink[wy0:wy1, x0:x1].any(axis=1)):
        if r1 - r0 >= MIN_PART * height and min(wy0 + r1, y1) - max(wy0 + r0, y0) >= SPLIT_INSIDE * height:
            runs.append((wy0 + r0, wy0 + r1))
    return runs


def _ink_span(ink, x0, x1, y0, y1, height, others):
    """Columns of the lettering in rows y0..y1 that reach the box x0..x1, stopping at other boxes."""
    w = ink.shape[1]
    lo, hi = 0, w
    for ox0, oy0, ox1, oy1 in others:  # a neighbour on the same row bounds the line
        if min(y1, oy1) - max(y0, oy0) > 0.5 * (y1 - y0):
            if ox1 <= x0:
                lo = max(lo, ox1)
            elif ox0 >= x1:
                hi = min(hi, ox0)
    cols = ink[y0:y1, lo:hi].any(axis=0)
    # Letter spacing only: a mark beyond a word gap (a sound effect on the bubble outline) stays out.
    gap = max(3, int(round(height * FIT_GAP)))
    on = np.flatnonzero(cols)
    if not len(on):
        return x0, x1
    # Runs of letters, words joined across gaps up to ``gap``; every run that meets the box
    # is the line (a box ending inside the last word, "ISN'T IT?", still holds that word).
    runs = []
    for c in on + lo:
        if not runs or c - runs[-1][1] > gap:
            runs.append([c, c + 1])
        runs[-1][1] = c + 1
    meeting = [(a, b) for a, b in runs if b >= x0 and a <= x1]
    if not meeting:
        return x0, x1
    return min(x0, int(meeting[0][0])), max(x1, int(meeting[-1][1]))


def _glyph_span(gray, x0, x1, r0, r1, height, lo, hi):
    """Widen x0..x1 over dark glyphs of the image that sit inside the row band r0..r1.

    The detector mask can miss the first letter of a bold italic word (the "A" of
    "AMOUNT", read "MOUN").  A letter stays inside its line; a bubble outline or
    the art runs above or below it and is never taken.
    """
    h, w = gray.shape
    margin = max(2, int(round(0.15 * height)))
    reach = int(round(2 * height))
    wx0, wx1 = max(lo, x0 - reach), min(hi, x1 + reach)
    wy0, wy1 = max(0, r0 - margin - 1), min(h, r1 + margin + 1)
    if wx1 <= wx0 or wy1 <= wy0:
        return x0, x1
    dark = (gray[wy0:wy1, wx0:wx1] < INK_LEVEL).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(dark, connectivity=8)
    glyphs = [(wx0 + int(sx), wx0 + int(sx + sw)) for sx, sy, sw, sh, _ in stats[1:]
              if sy > 0 and sy + sh < wy1 - wy0 and sh >= 0.3 * (r1 - r0)]
    gap = max(3, int(round(height * FIT_GAP)))
    changed = True
    while changed:
        changed = False
        for g0, g1 in glyphs:
            if g0 < x0 and x0 - g1 <= gap:
                x0, changed = g0, True
            if g1 > x1 and g0 - x1 <= gap:
                x1, changed = g1, True
    return x0, x1


def fit_lines(ink, items, height, changes, gray=None):
    """Fit line boxes to the lettering of the detector mask before OCR.

    Grand Blue 102 pp. 27/42/47: a box 13 px tall over letters 17 px tall, or one
    that started after the first letter ("MOUN" for "AMOUNT"), made the OCR drop
    the line or misread it, and the speech came out split or wrong.  Boxes that
    share whole rows (one box over "NOW," and half of the next line, another over
    the next two lines) are cut again, one box per row of letters.  A box that
    already holds its line is left exactly as it is.
    """
    boxes = [b for b, _ in items]
    n = len(items)
    parent = list(range(n))
    def root(i):
        while parent[i] != i:
            i = parent[i]
        return i
    for i in range(n):
        for j in range(i + 1, n):
            a, b = boxes[i], boxes[j]
            rows = min(a[3], b[3]) - max(a[1], b[1])
            cols = min(a[2], b[2]) - max(a[0], b[0])
            if rows >= FIT_OVERLAP * height and cols > 0.3 * min(a[2] - a[0], b[2] - b[0]) \
                    and a[2] - a[0] > a[3] - a[1] and b[2] - b[0] > b[3] - b[1]:
                parent[root(i)] = root(j)
    groups = {}
    for i in range(n):
        groups.setdefault(root(i), []).append(i)
    out = []
    for members in groups.values():
        # Only when a box holds two lines or more: boxes of a tilted paragraph overlap a little anyway.
        if len(members) >= 2 and max(boxes[i][3] - boxes[i][1] for i in members) >= FIT_TALL * height:
            union = (min(boxes[i][0] for i in members), min(boxes[i][1] for i in members),
                     max(boxes[i][2] for i in members), max(boxes[i][3] for i in members))
            x0, y0, x1, y1 = union
            parts = []
            counts = ink[y0:y1, x0:x1].sum(axis=1)
            rows = counts > 0
            runs = []
            for r0, r1 in _runs(rows):
                if r1 - r0 <= SPLIT_FACTOR * height:
                    runs.append((r0, r1))
                    continue
                # Lines that touch (outlined lettering, tight leading) are cut where the
                # ink nearly stops: a row or two with only a few pixels between them.
                body = counts[r0:r1]
                valley = body > FIT_VALLEY * float(np.median(body[body > 0]))
                runs.extend((r0 + a, r0 + b) for a, b in _runs(valley, gap=0))
            for r0, r1 in runs:
                if r1 - r0 < MIN_PART * height:
                    continue
                cols = np.flatnonzero(ink[y0 + r0:y0 + r1, x0:x1].any(axis=0))
                # The row keeps its letters past the boxes ("ISN'T IT?" lost "IT?").
                px0, px1 = _ink_span(ink, x0 + int(cols[0]), x0 + int(cols[-1]) + 1, y0 + r0, y0 + r1, height,
                                     [b for j, b in enumerate(boxes) if j not in members])
                part = (px0, y0 + r0, px1, y0 + r1)
                # The source is the box holding most of the row.
                best = max(members, key=lambda i: min(part[3], boxes[i][3]) - max(part[1], boxes[i][1]))
                parts.append((part, items[best][1]))
            if len(parts) >= 2:
                out.extend(parts)
                changes.append(("refit", union, [b for b, _ in parts]))
                continue
        for i in members:
            box, source = items[i]
            x0, y0, x1, y1 = box
            runs = _line_runs(ink, box, height) if x1 - x0 > y1 - y0 else []
            # Only a run one line tall: a taller one is several lines, left to the split above.
            if len(runs) != 1 or runs[0][1] - runs[0][0] > SPLIT_CHECK * height:
                out.append(items[i])
                continue
            r0, r1 = runs[0]
            others = [b for j, b in enumerate(boxes) if j != i]
            # Even a row of the letters left outside the box makes the OCR drop the line.
            tall = r0 < y0 or r1 > y1
            nx0, nx1 = _ink_span(ink, x0, x1, r0, r1, height, others)
            if gray is not None:
                lo = max([b[2] for b in others if min(r1, b[3]) - max(r0, b[1]) > 0.5 * (r1 - r0) and b[2] <= x0] + [0])
                hi = min([b[0] for b in others if min(r1, b[3]) - max(r0, b[1]) > 0.5 * (r1 - r0) and b[0] >= x1]
                         + [ink.shape[1]])
                nx0, nx1 = _glyph_span(gray, nx0, nx1, r0, r1, height, lo, hi)
            wide = x0 - nx0 >= FIT_SIDE * height or nx1 - x1 >= FIT_SIDE * height
            if not (tall or wide):
                out.append(items[i])
                continue
            # A pixel of margin: the OCR misreads a line whose box clips the letters.
            fitted = (max(0, nx0 - 1), max(0, (r0 if tall else min(y0, r0)) - 1),
                      min(ink.shape[1], nx1 + 1), min(ink.shape[0], (r1 if tall else max(y1, r1)) + 1))
            out.append((fitted, source))
            changes.append(("fit", box, [fitted]))
    return out


# Two columns of text side by side in one bubble --------------------------------

COLUMN_GAP = 0.3      # blank stripe through every line of a stack, in line heights
COLUMN_ROW_GAP = 0.6  # a line crossing the stripe has this much blank there
COLUMN_WORD_GAP = 2   # and that blank is this many times its widest word gap
COLUMN_PAIRS = 2      # unless this many lines wholly on each side share their rows: two columns side by side
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


def _side_by_side(left, right):
    """Pairs of line boxes, one from each list, that share most of their rows."""
    pairs = 0
    for a in left:
        for b in right:
            rows = min(a[3], b[3]) - max(a[1], b[1])
            if rows > 0.5 * min(a[3] - a[1], b[3] - b[1]):
                pairs += 1
    return pairs


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
            # Lines wholly on each side at the same height: two columns read side by side, even
            # when the gutter is narrow (Grand Blue 102 p33: a white outline runs into the bubble
            # beside it).  One speech never has two of its lines next to each other.
            side = _side_by_side([boxes[idx[k]] for k in left - right], [boxes[idx[k]] for k in right - left]) >= COLUMN_PAIRS
            ok = True
            for k in ([] if side else both):
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


# Two paragraphs side by side that the detector boxed together --------------------

BLOCK_GAP_X = 0.3   # letters closer than twice this (line heights) sideways are one paragraph
BLOCK_GAP_Y = 0.5   # and lines closer than twice this (line heights) one under the other
BLOCK_SHARE = 0.15  # a paragraph holds at least this share of a box's ink to cut the box


def text_blocks(mask, boxes):
    """Labels of the paragraphs of the detector mask: letters joined across word and line gaps."""
    mask = np.asarray(mask) > 127
    heights = [b[3] - b[1] for b in boxes if b[2] - b[0] > b[3] - b[1]]
    if not heights:
        return mask, None
    height = float(np.median(heights))
    gx, gy = max(1, int(round(BLOCK_GAP_X * height))), max(1, int(round(BLOCK_GAP_Y * height)))
    grown = cv2.dilate(mask.astype(np.uint8), np.ones((2 * gy + 1, 2 * gx + 1), np.uint8))
    return mask, cv2.connectedComponents(grown, connectivity=8)[1]


def _box_blocks(mask, labels, box):
    """{paragraph label: ink pixels} of the paragraphs a box holds a real share of."""
    x0, y0, x1, y1 = (int(v) for v in box)
    ink = labels[y0:y1, x0:x1][mask[y0:y1, x0:x1]]
    if not ink.size:
        return {}
    ids, counts = np.unique(ink, return_counts=True)
    return {int(i): int(c) for i, c in zip(ids, counts) if c >= BLOCK_SHARE * ink.size}


def _paragraphs(mask, labels, boxes):
    """Paragraph labels that hold the main ink of two line boxes or more."""
    count = {}
    for box in boxes:
        blocks = _box_blocks(mask, labels, box)
        if blocks:
            main = max(blocks, key=blocks.get)
            count[main] = count.get(main, 0) + 1
        for label in blocks:  # a box across two paragraphs is a line of each
            if len(blocks) >= 2:
                count[label] = count.get(label, 0) + 1
    return {label for label, n in count.items() if n >= 2}


def block_cuts(mask, boxes):
    """{line index: [(x0, x1), ...]} for line boxes across two paragraphs side by side.

    Grand Blue 102 p3: "LET'S / JUST DO / AS HE / SAYS." in a bubble open to the page,
    and "I JUST / KNOW IT'LL / COME BACK..." written on the page beside it, with no
    outline between them; the detector drew one box over "I JUST  AS HE" and another
    over "KNOW IT'LL  SAYS.", and the two speeches were read as one.  The letters of
    each paragraph are joined across word and line gaps; a box whose ink falls in two
    such paragraphs, each of two lines or more, is cut between them.  Spaced-out words
    of one speech, or a lone word beside it, are never cut off.
    """
    mask, labels = text_blocks(mask, boxes)
    if labels is None:
        return {}
    paragraphs = _paragraphs(mask, labels, boxes)
    cuts = {}
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        if x1 - x0 <= y1 - y0:
            continue
        blocks = _box_blocks(mask, labels, (x0, y0, x1, y1))
        if len(blocks) < 2 or not set(blocks) <= paragraphs:
            continue
        spans = []
        for label in blocks:
            cols = np.flatnonzero(((labels[y0:y1, x0:x1] == label) & mask[y0:y1, x0:x1]).any(axis=0))
            spans.append((x0 + int(cols[0]), x0 + int(cols[-1]) + 1))
        spans.sort()
        if all(a[1] < b[0] for a, b in zip(spans, spans[1:])):  # side by side, never interleaved
            cuts[i] = spans
    return cuts


def paragraph_of(blocks, boxes):
    """The paragraph label (of ``text_blocks``) holding most of the ink of ``boxes``, or None."""
    mask, labels = blocks
    if labels is None:
        return None
    total = {}
    for box in boxes:
        for label, count in _box_blocks(mask, labels, box).items():
            total[label] = total.get(label, 0) + count
    return max(total, key=total.get) if total else None


def block_groups(mask, boxes):
    """Line indexes grouped by paragraph; one group unless two paragraphs of two lines or more."""
    mask, labels = text_blocks(mask, boxes)
    if labels is None:
        return [list(range(len(boxes)))]
    groups = {}
    for i, box in enumerate(boxes):
        blocks = _box_blocks(mask, labels, box)
        key = max(blocks, key=blocks.get) if blocks else None
        groups.setdefault(key, []).append(i)
    if None in groups or len(groups) < 2 or min(len(g) for g in groups.values()) < 2:
        return [list(range(len(boxes)))]
    return list(groups.values())


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
STAIR_SHARED = 0.8  # the two lines of a staircase overlap sideways less than this share


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
    shared = min(boxes[0][2], boxes[1][2]) - max(boxes[0][0], boxes[1][0])
    if shared >= STAIR_SHARED * min(boxes[0][2] - boxes[0][0], boxes[1][2] - boxes[1][0]):
        return []  # one half inside the other: one line of big letters (Grand Blue 102 p31), not two offset lines
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
    letters = [c for c in comps if 0.5 * med <= c[3] <= 1.6 * med and 0.2 * med <= c[2] <= 2.5 * med]
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
        out.append(((min(c[0] for c in cs), min(c[1] for c in cs),
                     max(c[0] + c[2] for c in cs), max(c[1] + c[3] for c in cs)), len(cs)))
    if not words:
        return None
    out.sort(key=lambda r: r[0][1])
    blocks = [[out[0]]]
    for row in out[1:]:
        if row[0][1] - blocks[-1][-1][0][3] > 1.2 * med:
            blocks.append([])
        blocks[-1].append(row)
    # A lone mark far from the text (one piece on its own row: a stutter letter half
    # outside the bubble, a stroke of the art) does not make the rest less of a speech.
    kept = [b for b in blocks if len(b) > 1 or b[0][1] >= 2]
    # With a mark left out, the rest has to hold a word of three letters or more.
    if len(kept) != 1 or (len(kept) < len(blocks) and max(n for _, n in kept[0]) < 3):
        return None
    blocks = kept
    out = [box for box, _ in blocks[0]]
    # Punctuation under the last row ("SORRY / ...") is a row of its own: lettering, not a drawn sound.
    x0, _, x1, y1 = out[-1]
    dots = [c for c in comps if c[3] < 0.5 * med and x0 <= c[0] and c[0] + c[2] <= x1 and 0 <= c[1] - y1 <= 1.2 * med]
    if len(dots) >= 2:
        out.append((min(c[0] for c in dots), min(c[1] for c in dots),
                    max(c[0] + c[2] for c in dots), max(c[1] + c[3] for c in dots)))
    return out


SCAN_SPLIT = 15           # disc (px) that cuts a bubble off a light background it leaks into
SCAN_SEEN = 0.5           # share of a box inside a cut-off bubble that means the detector saw it
SCAN_GRAZE = 0.02         # a box with less of itself inside a bubble that leaks out only grazes it


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
        bubble, reason = _scan_bubble(gray, raw, labels, i, stats[i], kernel, boxes, None)
        if bubble:
            found.append(bubble)
        elif reason == "open":
            pieces = _split_bubble(gray, raw, labels, i, stats[i], boxes)
            if not pieces:
                # The white leaks out to the page and only grazes the boxes of the bubble next
                # door (Grand Blue 102 p20, "SORRY..."): those boxes do not mean this one was seen.
                bubble, _ = _scan_bubble(gray, raw, labels, i, stats[i], kernel, boxes, SCAN_GRAZE)
                pieces = [bubble] if bubble else []
            found.extend(pieces)
    return found


def _split_bubble(gray, raw, labels, label, stats, boxes):
    """Bubbles cut off a white area that was rejected as jagged or as touching a box.

    A sound effect lettered across the outline left gaps, the bubble white ran into
    the light sky of the panel and the whole area touched the sound effect box.  A bigger opening cuts the bubble off at the gaps; each piece goes
    through the same checks, and only a box mostly inside a piece counts as seen.
    """
    x, y, bw, bh = (int(v) for v in stats[:4])
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (SCAN_SPLIT, SCAN_SPLIT))
    pieces = cv2.morphologyEx((labels[y:y + bh, x:x + bw] == label).astype(np.uint8), cv2.MORPH_OPEN, kernel)
    n, cut, cut_stats, _ = cv2.connectedComponentsWithStats(pieces, connectivity=4)
    if n <= 2:  # nothing was cut off: the area really is jagged or seen
        return []
    page = np.zeros_like(labels)
    page[y:y + bh, x:x + bw] = cut
    found = []
    for i in range(1, n):
        piece = cut_stats[i].copy()
        piece[0] += x
        piece[1] += y
        bubble, _ = _scan_bubble(gray, raw, page, i, piece, kernel, boxes, SCAN_SEEN)
        if bubble:
            found.append(bubble)
    return found


def _scan_bubble(gray, raw, labels, i, stats, kernel, boxes, seen):
    """(bubble, None) when component ``i`` is an undetected bubble with text, else (None, reason).

    ``seen`` None: any box touching the area means the detector saw it.  A share:
    only a box with at least that much of itself inside the area does.  Reason
    "open" marks an area that may be a bubble joined to a light background.
    """
    h, w = gray.shape
    x, y, bw, bh, area = (int(v) for v in stats)
    if not SCAN_AREA[0] * h * w <= area <= SCAN_AREA[1] * h * w:
        return None, "area"
    if x == 0 or y == 0 or x + bw >= w or y + bh >= h:
        return None, "edge"
    # Back to the full white area the opening trimmed (thin strips between letters).
    g = 6
    x0, y0, x1, y1 = max(0, x - g), max(0, y - g), min(w, x + bw + g), min(h, y + bh + g)
    touching = [b for b in boxes if min(x1, b[2]) > max(x0, b[0]) and min(y1, b[3]) > max(y0, b[1])]
    if touching and seen is None:
        return None, "open"
    comp = cv2.dilate((labels[y0:y1, x0:x1] == i).astype(np.uint8), kernel) & raw[y0:y1, x0:x1]
    contours, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    outline = max(contours, key=cv2.contourArea)
    filled = cv2.drawContours(np.zeros_like(comp), [outline], -1, 1, -1)
    for b in touching:
        bx0, by0, bx1, by1 = max(b[0], x0) - x0, max(b[1], y0) - y0, min(b[2], x1) - x0, min(b[3], y1) - y0
        if filled[by0:by1, bx0:bx1].sum() >= seen * max(1, (b[2] - b[0]) * (b[3] - b[1])):
            return None, "seen"
    if filled.sum() < SCAN_SOLIDITY * cv2.contourArea(cv2.convexHull(outline)):
        return None, "open"
    inner = cv2.erode(filled, np.ones((7, 7), np.uint8)) > 0
    ink = inner & (comp == 0) & (gray[y0:y1, x0:x1] < SCAN_INK)
    if not SCAN_INK_SHARE[0] <= ink.sum() / max(1, filled.sum()) <= SCAN_INK_SHARE[1]:
        return None, "ink"
    rows = _text_rows(ink)
    if not rows:
        return None, "rows"
    cw, ch = x1 - x0, y1 - y0
    tx = (min(r[0] for r in rows) + max(r[2] for r in rows)) / 2
    ty = (rows[0][1] + rows[-1][3]) / 2
    if abs(tx - cw / 2) > SCAN_CENTRE[0] * cw or abs(ty - ch / 2) > SCAN_CENTRE[1] * ch:
        return None, "centre"
    letters = np.zeros((h, w), bool)
    for a, b, c, d in rows:  # only the ink of the rows: never a stroke of the art beside them
        letters[y0 + max(0, b - 2):y0 + d + 2, x0 + max(0, a - 2):x0 + c + 2] = ink[max(0, b - 2):d + 2, max(0, a - 2):c + 2]
    rows = [(x0 + a, y0 + b, x0 + c, y0 + d) for a, b, c, d in rows]
    rows, y1 = _rows_below(gray, rows, letters, (x0, x1), y1)
    return ((x0, y0, x1, y1), rows, letters), None


def _rows_below(gray, rows, letters, span, bottom):
    """Rows of letters right under the last one, cut off from the bubble by the white-area opening.

    Grand Blue p23: the letters of "HOLE..." closed the white strip under "ASS-", so the
    bubble found by the scan ended at that row and only "ASS" was read.
    """
    h = gray.shape[0]
    med = float(np.median([r[3] - r[1] for r in rows]))
    x0, x1 = span[0] + 4, span[1] - 4
    while x1 - x0 > med:
        top = rows[-1][3]
        band_bottom = min(h, int(top + 2.4 * med))
        if band_bottom - top < med:
            break
        ink = gray[top:band_bottom, x0:x1] < SCAN_INK
        n, labels, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
        for k in range(1, n):  # the bubble outline and the art outside it touch the band's sides
            if stats[k][0] == 0 or stats[k][0] + stats[k][2] >= x1 - x0:
                ink[labels == k] = False
        found = _text_rows(ink)
        if not found:
            break
        a, b, c, d = found[0]
        if b > 1.2 * med or not 0.6 * med <= d - b <= 1.5 * med:
            break
        row = (x0 + a, top + b, x0 + c, top + d)
        rows.append(row)
        letters[row[1]:row[3], row[0]:row[2]] |= ink[b:d, a:c]
        bottom = max(bottom, row[3] + 6)
    return rows, bottom


def reads_as_speech(text, several_rows=False):
    """True when a scanned bubble's OCR text reads as an English line, not a drawn sound.

    A line has a common English word and either two words or end punctuation:
    "MUSCLE?", "I SEE." yes; "GRAB" (a sound in a jagged box) or "REEE" no.
    """
    common, _ = english_words()
    words = re.findall(r"[A-Za-z']+", text or "")
    if not words or not any(len(w) >= 2 and (w.lower() in common or w.lower().replace("'", "") in _contractions(common))
                            for w in words):
        return False
    return several_rows or len(words) >= 2 or bool(re.search(r"[.!?…-]\W*$", text.strip()))


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


# Spanish words that are never Portuguese (op1153-6a: a weaker model wrote "Gracias" and
# "nuestra reina" in Brazilian dialogue).  A word the original also has is a name and stays.
SPANISH_WORDS = re.compile(
    r"(?<![\wÀ-ÿ])(?:gracias|usted|ustedes|señora?|señorita|hola|muy|buen[oa]s?|ahora|entonces|también|"
    r"nosotros|nuestr[oa]s?|ellos|ellas|aquí|allí|hacer|tengo|tienes|puedo|quiero|mism[oa]s?|cuando|"
    r"verdad|dinero|mierda|perdón|siempre|hij[oa]s?|mujer|hombre|niñ[oa]s?|corazón|ciudad|"
    r"[\wÀ-ÿ]*ñ[\wÀ-ÿ]*|[a-zà-ÿ]{2,}ió)(?![\wÀ-ÿ])|[¡¿]", re.I)  # "-ió": Spanish past ("desenvolvió")
# "O mais triste de todas": the article and "de todos/todas" disagree in gender.
# Only "o ... de todas": a woman in a mixed group is rightly "a mais forte de todos".
SUPERLATIVE_GENDER = re.compile(r"(?<![\wÀ-ÿ])(?:o|um)\s+mais\s+[\wÀ-ÿ]+\s+de\s+todas(?![\wÀ-ÿ])", re.I)
# The same word twice in a row ("vocês tão tão distraídos"); a hyphen marks a stutter and a
# word without a vowel is a sound ("Bzz bzz", "Hmm hmm").
DOUBLED_WORD = re.compile(r"(?<![\wÀ-ÿ-])((?=[\wÀ-ÿ]*[aeiouáéíóúâêôãõà])[\wÀ-ÿ]{2,})\s+\1(?![\wÀ-ÿ-])",
                          re.I)
# Portuguese says these twice on purpose ("já já", "tchau tchau", "o que que", "bem bem
# longe", "quase quase", "pega pega"), and laughs and interjections are written apart even
# when the original glues them ("HAHAHA", "UH-OH").
REDUPLICATIONS = {"já", "logo", "que", "tchau", "bem", "quase", "pisca", "corre", "pega",
                  "ha", "há", "rá", "he", "hi", "ho", "hu", "ah", "oh", "eh", "ai", "ei", "ui", "hum"}
# Interjections a Brazilian scan writes as the English lettering does ("AH..", "HMM", "HAHA", "OK!").
SAME_INTERJECTIONS = {"ah", "oh", "eh", "uh", "hm", "hmm", "hum", "ha", "ho", "ok"}  # not "he": a pronoun
LAUGH = re.compile(r"(?:h[aeio]){2,}h?")
# Grand Blue 106 p23: asked to read an OCR mistake "as intended", the AI shrank a vertical buzz to "V";
# p24: without the exception spelled out, the prompt's "isolated sound effects" rule won twice.
UNCHANGED_NOTE = ("came back unchanged, but it is lettered in a bubble or caption, so the rule about isolated "
                  "sound effects does not apply to it: write what a Brazilian scanlation prints there, "
                  "an interjection, scream or sound effect in its Portuguese form, "
                  "as long and as loud as the original (\"GRR\" -> \"Grrr\", \"SNIFF\" -> \"Snif\"), never a "
                  "lone letter; only names stay as written")


def same_text(source, text):
    """The engine's test for an untranslated answer (it drops the region)."""
    return str(source or "").strip().lower() == str(text or "").strip().lower()


def unchanged_english(source, names=()):
    """Words that keep an answer equal to its source from being Portuguese already.

    op1161 p16: "AH.." and a scream came back unchanged and the engine dropped them,
    leaving the English lettering; Grand Blue 106 p23 the same with the OCR of a
    vertical phone buzz ("V BVVVV BVVV").  An interjection, a scream, a sound or a
    name reads the same in Portuguese; a common English word, a lone letter or a word
    with digits (an OCR mistake) does not.  ``names`` are names of the page or glossary.
    """
    common, _ = english_words()
    tokens = re.findall(r"[^\W_]+", str(source or ""))
    if not common:  # no word list: nothing is known to read the same
        return tokens
    named = {word.lower() for name in names for word in re.findall(r"[^\W_]+", str(name))}  # "Lily Steel"
    found = []
    for token in tokens:
        word = token.lower()
        if word.isdigit() or word in named:
            continue
        if any(c.isdigit() for c in word) or (len(word) == 1 and word not in "aeo"):
            found.append(token)
            continue
        # A held vowel or consonant is the same word: "AAAH" is "ah", "NOOO" is "no", "GOOOD" is
        # "good"; a plain double letter stays ("SHAKKY" is no "shaky").
        forms = {word} | {f for f in (re.sub(r"(.)\1{2,}", r"\1", word), re.sub(r"(.)\1{2,}", r"\1\1", word))
                          if len(f) > 1}
        if any(f in SAME_INTERJECTIONS or LAUGH.fullmatch(f) for f in forms):
            continue
        if len(word) > 1 and any(f in common for f in forms):
            found.append(token)
    return found


def portuguese_problems(source, text):
    """Notes for Spanish words, a superlative with the wrong gender and a word written twice."""
    notes = []
    for match in SPANISH_WORDS.finditer(text or ""):
        # A name of the original, with its tilde or without it when the OCR dropped it ("MUNOZ").
        word = match.group(0)
        if word in "¡¿" or not (_has(word, source) or _has(word.replace("ñ", "n").replace("Ñ", "N"), source)):
            notes.append(f"has the Spanish \"{match.group(0)}\": write correct Brazilian Portuguese")
            break
    match = SUPERLATIVE_GENDER.search(text or "")
    if match:
        notes.append(f"\"{match.group(0)}\" mixes masculine and feminine: make the gender agree")
    if not DOUBLED_WORD.search(str(source or "")):
        for match in DOUBLED_WORD.finditer(text or ""):
            if match.group(1).lower() not in REDUPLICATIONS:
                notes.append(f"writes \"{match.group(0)}\", the same word twice: write it once")
                break
    return notes


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
    names = page_names([t for t in translations if isinstance(t, str)]) | {g.get("target", "") for g in glossary}
    notes = []
    for number, (source, text) in enumerate(zip(sources, translations), 1):
        if not isinstance(text, str):
            continue
        if same_text(source, text) and re.search(r"[^\W\d_]", text) and unchanged_english(source, names):
            # The prompt leaves "isolated sound effects" alone, but a region here sits in a bubble
            # or caption: unchanged, the engine drops it and the English stays on the page.
            notes.append(f"<|{number}|> {UNCHANGED_NOTE}")
            continue
        letters = re.findall(r"[^\W\d_]", text)
        if len(letters) == 1 and letters[0].lower() not in "aeoéóô" and len(re.findall(r"[^\W\d_]", str(source))) > 2:
            notes.append(f"<|{number}|> is a lone letter; write the whole line, interjection or sound effect")
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
        notes += [f"<|{number}|> {note}" for note in portuguese_problems(source, text)]
    return notes


# OCR letter mix-ups in comic capitals -------------------------------------------

# What the OCR read -> what the letterer drew.  Only words the list does not know
# are touched, and only when exactly one common word comes out.
OCR_CONFUSIONS = (("LI", "U"), ("LJ", "U"), ("IJ", "U"), ("E", "F"), ("F", "E"), ("O", "D"), ("O", "C"), ("O", "Q"),
                  ("C", "D"), ("I", "D"), ("I", "L"), ("I", "T"), ("L", "I"), ("0", "O"), ("1", "I"), ("5", "S"),
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


# Comic speech the dictionary does not list; never "fixed" into another word ("LIL" -> "LII").
SLANG = {"lil", "gonna", "wanna", "gotta", "ya", "yall", "kinda", "sorta", "dunno", "nah", "yup", "nope",
         "cmon", "em", "outta", "lotta", "gimme", "lemme", "whatcha", "gotcha", "betcha", "dude", "bro", "sis",
         "goin", "doin", "nothin", "somethin", "huh", "heh", "hmph", "tch", "ugh", "oi", "eh", "uh", "um", "hm"}


def _known(word, common, names):
    w = word.lower()
    return w in common or w in names or w in SLANG or w in _contractions(common)


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
        if len(core) < (2 if noisy else 3) or _known(core.replace("'", ""), common, names):
            return word
        for depth in (1, 2) if len(core) >= 6 else (1,):
            hits = {c for c in _ocr_candidates(core, depth)
                    if c.lower() in common and not re.fullmatch(r"[IVXLCDM]+", c)}
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
