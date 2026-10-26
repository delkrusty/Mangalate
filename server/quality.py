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
import string

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


# A logo or a title drawn as a graphic (One Piece 1161 p2: the series logo on a blank page)
# also reads as lettering on paper crossed by strokes, its own outlines and ornaments.  Its
# letters are several times as tall as any speech written over the drawing: those measured at
# most 0.039 of the shorter side of the page (0.033 for 95% of them), the logo 0.14.  Such a
# block stays as drawn unless its text reads as a line of English (engine_compat).
LOGO_LINE = 0.12  # line height, in shares of the shorter side of the page, of lettering drawn as a logo


def drawn_title(shape, quads):
    """True when the lines of a block are as tall as a logo's, not a speech's."""
    quads = [np.asarray(q, np.float32).reshape(4, 2) for q in quads]
    if not quads:
        return False
    if stacked(quads):  # letters one per row: the letters are as tall as the column is wide
        line = float(np.median([max(np.ptp(q[:, 0]), 1.0) for q in quads]))
    else:
        line = _quads_height(quads)
    return line >= LOGO_LINE * min(shape[:2])


KEEP_DUPLICATE = 0.5  # share of overlap that makes a kept line and a translated block two boxes of the same text
KEEP_RING = 0.5       # around a kept line, in the shorter side of its box, the mask of a translated block leaves too...
KEEP_RING_MAX = 8     # ...at most this many px (a tall column of a sound effect is not a line height)
KEEP_REACH = 0.4      # and never within this many line heights of a translated line (overhanging letters)
KEEP_REACH_MAX = 12   # px: the reach of a huge title line (108 px) is not 43 px of overhang
KEEP_RIM = 3          # px around such a stroke that go with it (its anti-aliased rim)
KEEP_INK = 128        # strokes darker than this (0-255 grey) are split between crossing kept and translated boxes


def kept_lines(shape, preserved, kept, gray=None):
    """Pixels the mask of a translated block must leave: the lines of blocks kept as drawn, with a ring.

    ``preserved`` and ``kept`` are regions with ``lines`` (quadrilaterals).  The mask of a
    translated title whose box ran onto the small print of a form under it erased words of
    that print, kept as drawn (Grand Blue 102 p4); a ring of KEEP_RING line heights around the
    print is left too (at most KEEP_RING_MAX px), or the cleaning model draws letters there from
    the print beside it.  The ring stays KEEP_REACH line heights away from translated lines, whose
    letters often overhang their boxes (a tall sound effect beside a bubble, Grand Blue 106 p38).  A kept
    line and a translated block that mostly overlap, either way (a duplicate box of the same
    speech, or a box read as a sound effect around a whole speech), are the same text: the
    translated block is cleaned as usual.  The ring never reaches into translated lines.
    """
    h, w = shape[:2]
    blocks = []
    for region in kept or []:
        lines = getattr(region, "lines", None)
        own = np.zeros((h, w), np.uint8)
        for line in lines if lines is not None else []:
            cv2.fillPoly(own, [np.asarray(line, np.int32).reshape(-1, 1, 2)], 1)
        if own.any():
            blocks.append(own > 0)
    translated = np.zeros((h, w), bool)
    boxed = np.zeros((h, w), bool)  # the translated lines themselves, without the reach around them
    boxed_size = np.zeros((h, w), np.float32)  # and the height of their letters
    for region in kept or []:
        lines = getattr(region, "lines", None)
        for line in lines if lines is not None else []:
            quad = np.asarray(line, np.float32).reshape(4, 2)
            own = np.zeros((h, w), np.uint8)
            cv2.fillPoly(own, [quad.astype(np.int32).reshape(-1, 1, 2)], 1)
            boxed |= own > 0
            boxed_size[own > 0] = _letter_size(quad)
            reach = 2 * int(min(KEEP_REACH_MAX, round(KEEP_REACH * _quads_height([quad])))) + 1
            translated |= cv2.dilate(own, np.ones((reach, reach), np.uint8)) > 0
    keep = np.zeros((h, w), bool)
    lines_kept = np.zeros((h, w), bool)
    ring = np.zeros((h, w), bool)
    ring_size = np.zeros((h, w), np.float32)
    for region in preserved or []:
        lines = getattr(region, "lines", None)
        for line in lines if lines is not None else []:
            quad = np.asarray(line, np.float32).reshape(4, 2)
            own = np.zeros((h, w), np.uint8)
            cv2.fillPoly(own, [quad.astype(np.int32).reshape(-1, 1, 2)], 1)
            inside = own > 0
            if not inside.any():
                continue
            if any((inside & block).sum() >= KEEP_DUPLICATE * min(inside.sum(), block.sum()) for block in blocks):
                continue
            keep |= inside
            lines_kept |= inside
            # The box often ends before the last letter: the ring follows the size of the letters.
            short = min(_quads_height([quad]), float(np.ptp(quad[:, 0])))
            size = 2 * int(min(KEEP_RING_MAX, round(KEEP_RING * short))) + 1
            around = cv2.dilate(own, np.ones((size, size), np.uint8)) > 0
            ring |= around
            ring_size[around] = _letter_size(quad)
    keep |= ring & ~translated
    if gray is not None and (keep & boxed).any():
        # Where the boxes cross, each stroke touching a translated line goes with the block whose
        # letters are its size: the foot of "SMILE" (15 px) with its line, not with the column of
        # a sound effect beside it, so no English is left; the "y" of small print (18 px) with the
        # print, not with the 108 px title box over it.
        dark = (np.asarray(gray) < KEEP_INK).astype(np.uint8)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(dark, connectivity=8)
        touched = np.unique(labels[boxed & (dark > 0)])
        for k in touched[touched > 0]:
            x, y, cw, ch = stats[k, :4]
            part = labels[y:y + ch, x:x + cw] == k
            if not keep[y:y + ch, x:x + cw][part].any() and not ring[y:y + ch, x:x + cw][part].any():
                continue
            mine, theirs = boxed_size[y:y + ch, x:x + cw][part], ring_size[y:y + ch, x:x + cw][part]
            height = float(max(ch, 1))
            closer = not (theirs > 0).any() or (
                abs(np.log(height / np.median(mine[mine > 0]))) <= abs(np.log(height / np.median(theirs[theirs > 0]))))
            # The stroke with its anti-aliased rim: a lighter rim left out of the mask is a ghost.
            x0, y0, x1, y1 = max(0, x - KEEP_RIM), max(0, y - KEEP_RIM), min(w, x + cw + KEEP_RIM), min(h, y + ch + KEEP_RIM)
            whole = labels[y0:y1, x0:x1] == k
            grown = cv2.dilate(whole.astype(np.uint8), np.ones((2 * KEEP_RIM + 1, 2 * KEEP_RIM + 1), np.uint8)) > 0
            if closer:
                keep[y0:y1, x0:x1][grown] = False
                continue
            # A stroke of the kept text past its box gets the ring too, or the model draws from it.
            size = int(min(KEEP_RING_MAX, round(KEEP_RING * float(np.median(theirs[theirs > 0])))))
            x0, y0, x1, y1 = max(0, x - size), max(0, y - size), min(w, x + cw + size), min(h, y + ch + size)
            whole = labels[y0:y1, x0:x1] == k
            around = cv2.dilate(whole.astype(np.uint8), np.ones((2 * size + 1, 2 * size + 1), np.uint8)) > 0
            keep[y0:y1, x0:x1] |= around & ~(boxed[y0:y1, x0:x1] & ~whole & (labels[y0:y1, x0:x1] > 0))
    return keep


def _letter_size(quad):
    """Height of the letters a line box holds: the shorter side (a column of stacked letters is as wide as one)."""
    return max(1.0, min(_quads_height([quad]), float(np.linalg.norm(quad[1] - quad[0]))))


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
PAPER_LINE_MASKED = 0.75  # and in each line on its own
PAPER_INK = 60       # ink on the lines is this much darker than the page (0-255 grey)
PAPER_DOT = 0.2      # specks smaller than this squared (line heights) are screentone, not letters
PAPER_TILT = 3.0     # degrees: tilted lettering (a sheet of paper drawn askew) is written back level, over half-cleaned lines


def speech_on_paper(image, text_mask, quads, line_height=None, paper_share=PAPER_SHARE, masked_share=PAPER_MASKED):
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

    paper_share 0 is the reader's "translate everything" choice: the margin may be all
    drawing (dark letters with a white halo over the art), the other checks still apply.
    There, masked_share 0 leaves the letters the detector missed to halo_missed: the ink it
    left out was mostly the drawing touching the halo, not letters.
    """
    quads = [np.asarray(q, np.float32).reshape(4, 2) for q in quads]
    if text_mask is None or not quads:
        return False
    if line_height is None:
        line_height = _quads_height(quads)
    lines, paper = paper_under(image, quads, line_height)
    if paper_share == 0:
        # The letters' ground is their halo: a halo a few pixels wide over a black ground left
        # the margin black once the line boxes fitted the letters (2 px taller), and the dark
        # letters looked lighter than their "paper".
        _, halo = halo_paint(image, text_mask, quads, line_height)
        if halo is not None and np.mean(halo) >= PAPER_LIGHT:
            paper = np.asarray(halo).round().astype(paper.dtype)
    pad = int(max(4, round(line_height * 0.35)))
    margin = (cv2.dilate(lines.astype(np.uint8), np.ones((2 * pad + 1, 2 * pad + 1), np.uint8)) > 0) & ~lines
    letters = (np.asarray(text_mask) > INK) & lines
    if not margin.any() or not letters.any():
        return False
    gray = cv2.cvtColor(np.ascontiguousarray(np.asarray(image)[:, :, :3]), cv2.COLOR_RGB2GRAY).astype(int)
    ground = int(cv2.cvtColor(paper.reshape(1, 1, 3).astype(np.uint8), cv2.COLOR_RGB2GRAY)[0, 0])
    size = 2 * PAPER_CLEAN + 1
    clean = cv2.erode(gray.astype(np.uint8), np.ones((size, size), np.uint8)) > PAPER_LIGHT
    if clean[margin].mean() < paper_share or ground - np.median(gray[letters]) <= PAPER_CONTRAST:
        return False
    ink = lines & (gray < ground - PAPER_INK)
    # Screentone dots of a wall the line box runs onto (Grand Blue 106 p16) are not missed letters.
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    dots = stats[:, cv2.CC_STAT_AREA] < (PAPER_DOT * line_height) ** 2
    dots[0] = False
    ink &= ~dots[labels]
    marked = whole_letters(image, np.asarray(text_mask) > INK, lines, paper, line_height)
    marked = cv2.dilate(marked.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    if ink.any() and marked[ink].mean() < masked_share:
        return False
    if masked_share > 0:
        # Each line, too: a last line the mask holds only by a strip along its top ("HAPPEN!"
        # over the hair, 61% marked) passed with the block at 86%, and half of it stayed in
        # English under the translation.  The other lines of these speeches: 87% and up.
        for quad in quads:
            own = ink & (_line_mask(ink.shape, [quad]) > 0)
            if own.any() and marked[own].mean() < PAPER_LINE_MASKED:
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


HALO_EDGE_PX = 3     # px around the halo cleaned with it (its soft rim)
HALO_SNUG = 15       # a word the detector missed is enclosed by pixels this close (0-255 grey) to the halo
HALO_ENCLOSED = 0.7  # share of the border of a piece of ink that is halo, for it to be a letter (not a stroke)
HALO_EVEN = 40       # a pixel this close (0-255 grey) to the halo's colour is halo; light grey drawing is not


def halo_paint(image, text_mask, quads, line_height=None):
    """(pixels, colour) to paint over a speech written over the drawing with a light halo.

    The halo is already the colour of the paper: painting the letters with it cleans them, and
    the drawing around stays as it is.  Cleaned by the model, the whole block came back smeared
    (bars, bricks, hair).  A letter is ink the detector marked, or a piece of ink touching its
    marks and enclosed by the halo (the detector mask cut the top of a line); pieces of the
    drawing the halo cuts to the size of a letter reach the drawing and stay.  Light pixels right
    around the letters (the halo) are painted too, so it comes out even.
    """
    quads = [np.asarray(q, np.float32).reshape(4, 2) for q in quads]
    shape = np.asarray(image).shape[:2]
    if text_mask is None or not quads:
        return np.zeros(shape, bool), None
    if line_height is None:
        line_height = _quads_height(quads)
    allowed = letters_area(image, text_mask, quads, line_height)
    marks = (np.asarray(text_mask) > INK) & allowed
    grow = np.ones((2 * LETTER_GROW + 1, 2 * LETTER_GROW + 1), np.uint8)
    marked = cv2.dilate(marks.astype(np.uint8), grow) > 0
    # The halo's colour: the lightest quarter of the ring just outside the letters' rim (around
    # the lines is the drawing, and on a dark page the ring also catches it).
    ring = (cv2.dilate(marked.astype(np.uint8), grow) > 0) & ~marked
    if not ring.any():
        return np.zeros(shape, bool), None
    pixels = np.asarray(image)[:, :, :3]
    gray = cv2.cvtColor(np.ascontiguousarray(pixels), cv2.COLOR_RGB2GRAY).astype(int)
    light_side = ring & (gray >= np.percentile(gray[ring], 75))
    halo = np.median(pixels[light_side], axis=0)
    ground = int(cv2.cvtColor(halo.reshape(1, 1, 3).astype(np.uint8), cv2.COLOR_RGB2GRAY)[0, 0])
    light = np.abs(gray - ground) <= HALO_EVEN
    # A word the detector missed whole ("PONG PERIL..." under a marked "PING-") is outside the
    # allowed area but on the lines, letter-sized and in the halo.
    reach = 2 * int(max(1, round(LETTER_REACH * line_height))) + 1
    lines = cv2.dilate(_line_mask(shape, quads), np.ones((reach, reach), np.uint8)) > 0
    ink = (allowed | lines) & ~light
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    if count > 1:
        touched = np.zeros(count, bool)
        touched[np.unique(labels[ink & marks])] = True
        border = (cv2.dilate(ink.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0) & ~ink
        near = cv2.dilate(labels.astype(np.float32), np.ones((3, 3), np.uint8)).astype(int)  # owner of each border pixel
        halo_border = np.bincount(near[border], weights=light[border].astype(float), minlength=count)
        all_border = np.bincount(near[border], minlength=count)
        on_lines = np.bincount(labels[lines], minlength=count) >= 0.5 * stats[:, cv2.CC_STAT_AREA]
        # Only in a real halo: light, and the very colour of it all around (hatching over a light
        # tone, or over the grey a missing halo leaves, is not a word).
        snug = (np.abs(gray - ground) <= HALO_SNUG)[border]
        snug_border = np.bincount(near[border], weights=snug.astype(float), minlength=count)
        lettered = (on_lines & (stats[:, cv2.CC_STAT_AREA] >= (PAPER_DOT * line_height) ** 2)
                    & (snug_border >= HALO_ENCLOSED * np.maximum(all_border, 1)) & (ground >= PAPER_LIGHT))
        enclosed = halo_border >= HALO_ENCLOSED * np.maximum(all_border, 1)
        enclosed[0] = False
        # A piece touching the marks is taken inside the allowed area, as before; a missed word
        # whole, with its halo.
        marked |= cv2.dilate(((touched & enclosed)[labels] & allowed).astype(np.uint8), grow) > 0
        found = cv2.dilate((lettered & enclosed & ~touched)[labels].astype(np.uint8), grow) > 0
        if found.any():
            marked |= found
            halo_reach = 2 * int(max(1, round(HALO_REACH * line_height))) + 1
            allowed = allowed | (cv2.dilate(found.astype(np.uint8), np.ones((halo_reach, halo_reach), np.uint8)) > 0)
    # Light pixels count as halo only right around the letters: a light screentone or the grey of
    # hair inside the line boxes came out as a white rectangle.
    reach = 2 * int(max(1, round(HALO_REACH * line_height))) + 1
    around = cv2.dilate(marked.astype(np.uint8), np.ones((reach, reach), np.uint8)) > 0
    return allowed & (marked | (light & around)), halo


HALO_COVER = 0.85  # share of the ink on the lines that halo_paint cleans, for a speech over the drawing


def halo_cover(image, text_mask, quads, line_height=None):
    """Share of the ink on the lines that halo_paint cleans (with HALO_EDGE_PX around it).

    For the reader's "translate everything": the detector mask can miss whole words, but the
    halo shows the letters.  The ink it still leaves out is a piece of the drawing on the lines
    (hair, the shorts) or letters that would stay in English under the translation.
    """
    quads = [np.asarray(q, np.float32).reshape(4, 2) for q in quads]
    if line_height is None:
        line_height = _quads_height(quads)
    paint, halo = halo_paint(image, text_mask, quads, line_height)
    if halo is None or np.mean(halo) < PAPER_LIGHT:
        return 0.0  # no light halo: the letters sink into the drawing
    lines, _ = paper_under(image, quads, line_height)
    gray = cv2.cvtColor(np.ascontiguousarray(np.asarray(image)[:, :, :3]), cv2.COLOR_RGB2GRAY).astype(int)
    # The ink is what is darker than the halo (the margin around the lines can be the drawing).
    ground = int(cv2.cvtColor(np.asarray(halo).round().astype(np.uint8).reshape(1, 1, 3), cv2.COLOR_RGB2GRAY)[0, 0])
    ink = lines & (gray < ground - PAPER_INK)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    dots = stats[:, cv2.CC_STAT_AREA] < (PAPER_DOT * line_height) ** 2
    dots[0] = False
    ink &= ~dots[labels]
    if not ink.any():
        return 1.0
    edge = 2 * HALO_EDGE_PX + 1
    cleaned = cv2.dilate(paint.astype(np.uint8), np.ones((edge, edge), np.uint8)) > 0
    return float(cleaned[ink].mean())


HALO_CLOSE = 0.7   # gaps between the new letters and lines filled by their halo, in font sizes
HALO_RIM = 0.15    # and its rim around them, in font sizes


def halo_cloud(letters, size):
    """The light halo drawn under a translation written over the drawing.

    ``letters`` is where the new text is drawn and ``size`` its font size.  The halo hugs the
    new text, like the original's around its letters: over the drawing, the letters alone were
    hard to read, and the old block painted white was much bigger than the translation.
    """
    letters = np.asarray(letters).astype(np.uint8)
    if not letters.any():
        return letters.astype(bool)
    close = 2 * int(max(1, round(HALO_CLOSE * size / 2))) + 1
    rim = 2 * int(max(1, round(HALO_RIM * size))) + 1
    cloud = cv2.morphologyEx(letters, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close, close)))
    cloud = cv2.dilate(cloud, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (rim, rim))) > 0
    # Holes between lines of small letters showed the drawing as dark specks inside the halo.
    count, labels, stats, _ = cv2.connectedComponentsWithStats((~cloud).astype(np.uint8), connectivity=4)
    h, w = cloud.shape
    inside = ((stats[:, cv2.CC_STAT_LEFT] > 0) & (stats[:, cv2.CC_STAT_TOP] > 0)
              & (stats[:, cv2.CC_STAT_LEFT] + stats[:, cv2.CC_STAT_WIDTH] < w)
              & (stats[:, cv2.CC_STAT_TOP] + stats[:, cv2.CC_STAT_HEIGHT] < h))
    inside[0] = False  # the halo itself
    return cloud | inside[labels]


SPEECH_REACH = 1.5   # line heights above and below a block where the same speech could go on
SPEECH_LOOSE = 0.05  # share of that band (block width x one line) of detector ink outside every block


def speech_goes_on(text_mask, quads, all_quads, line_height=None):
    """True when detector ink right above or below the block lies outside every block's lines.

    The OCR lost a line of the speech ("IF I WIN," over the rest of it, "SCISSORS" under
    "ROCK, PAPER-"): translated, the rest came out with the sense inverted or cut, and the lost
    line was left in English next to it.
    """
    quads = [np.asarray(q, np.float32).reshape(4, 2) for q in quads]
    if text_mask is None or not quads:
        return False
    if line_height is None:
        line_height = _quads_height(quads)
    ink = np.asarray(text_mask) > INK
    ink &= _line_mask(ink.shape, [np.asarray(q, np.float32).reshape(4, 2) for q in all_quads]) == 0
    points = np.concatenate(quads)
    x0, y0 = np.floor(points.min(axis=0)).astype(int)
    x1, y1 = np.ceil(points.max(axis=0)).astype(int)
    x0, x1 = max(0, x0), min(ink.shape[1], x1)
    reach = int(round(SPEECH_REACH * line_height))
    area = max(1.0, (x1 - x0) * line_height)
    for top, bottom in ((y0 - reach, y0), (y1, y1 + reach)):
        band = ink[max(0, top):max(0, min(ink.shape[0], bottom)), x0:x1]
        if band.sum() / area > SPEECH_LOOSE:
            return True
    return False


LINE_READ = 0.5  # letters read per line height of width, below which a line was not really read...
LINE_WIDE = 3.0  # ...on a line at least this many heights wide ("LIKE" read "L" in a narrow column is a weak sign)


def lines_unread(quads, texts):
    """True when a line of the block came back from the OCR empty or as a scrap ("DP" for
    "OPPONENT'S IS WIDE OPEN."): its letters are cleaned, but the translation lacks them.

    Over 1,498 lines of two test chapters only four read under LINE_READ, all scraps.
    """
    texts = list(texts or [])
    if len(texts) != len(quads):
        return False
    for quad, text in zip(quads, texts):
        q = np.asarray(quad, np.float32).reshape(4, 2)
        width, height = np.ptp(q[:, 0]), max(1.0, float(np.ptp(q[:, 1])))
        if width >= LINE_WIDE * height and sum(ch.isalnum() for ch in str(text or "")) < LINE_READ * width / height:
            return True
    return False


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
    text = re.sub(r"</?(?:i|b|u|em|strong)>", "", text, flags=re.I)  # "<I>Tá</I>": the AI's emphasis, not text
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
    """``b`` continues ``a``'s last line to the right: "THE REAL" | "TRAINING" (OF 237 p62).

    A block that starts higher than that last line is a column beside it (One Piece 1161 p4,
    a caption box with columns side by side), not its last word.
    """
    bx0, by0, bx1, by1 = (float(v) for v in b.xyxy)
    last = max(np.asarray(a.lines, dtype=float), key=lambda q: q[:, 1].mean())
    lx0, ly0, lx1, ly1 = last[:, 0].min(), last[:, 1].min(), last[:, 0].max(), last[:, 1].max()
    shared = min(ly1, by1) - max(ly0, by0)
    gap = bx0 - lx1
    return shared >= 0.6 * line and -0.5 * line <= gap <= 1.2 * line and by0 >= ly0 - 0.5 * line


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
DOT_ASPECT = 2           # and at most this much longer than wide (a hairline is longer)
DOT_SIZE = 5             # a dot thinner than a stroke is at most this big (px): small print is not punctuation
DOT_INK = 128            # and has ink darker than this (0-255): light screentone specks are not
ELLIPSIS_ALIKE = 2.0     # the dots of "..." differ in size by less than this factor
DOT_FILL = 0.5           # and fills this share of its box: a short diagonal stroke of hatching does not
DOT_CLEAR = 2            # and has no other dark ink this close (px), unlike a fragment of hatching
DOT_ROW = 0.6            # and another dot on its row this close, in line heights (the dots of "...")
DOT_CROWD = 4            # but at most this many dots that close: more is a field of screentone specks


def bubble_glyphs(image, box, line_height, near=GLYPH_NEAR, dots=False):
    """Pixels of letters around ``box``: holes in the flat interior that surrounds the text.

    The detector mask misses parts of bold italic lettering (TBATE new episode
    p12: the T of "THIS", the end of "HARD", the whole line "OF US.").  Inside a
    bubble, every letter is a hole in the flat interior, whatever the detector
    saw.  Returns a boolean mask of the image size, empty when the text does not
    sit on a flat background.  With ``dots``, small dots of punctuation are kept too
    (for the cleaning only: the line repair would stretch a line box to them).
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
    shape_ok = np.zeros(count, bool)  # small, compact, filled and dark: shaped like a dot
    if dots:
        for label in range(1, count):
            bw, bh, area = stats[label, 2], stats[label, 3], stats[label, 4]
            shape_ok[label] = (max(bw, bh) < min(CLEAN_MARK * lh, DOT_SIZE + 1) and max(bw, bh) <= DOT_ASPECT * min(bw, bh)
                               and area >= DOT_FILL * bw * bh)
        # Ink that does not count against a dot: the letters (thick holes) and the other dots.
        thick = np.zeros(count, bool)
        thick[np.unique(labels[depth >= thin])] = True
        stray = (window.min(axis=2) < DOT_INK) & ~(thick | shape_ok)[labels]
        inked = np.zeros(count, bool)
        inked[np.unique(labels[window.min(axis=2) < DOT_INK])] = True
        marks = [k for k in range(1, count) if shape_ok[k] and inked[k]]
        centres = {k: (stats[k, 0] + stats[k, 2] / 2, stats[k, 1] + stats[k, 3] / 2) for k in marks}
        reach = DOT_ROW * lh

    def in_a_row(label):
        # The dots of "..." sit side by side on one row; a lone speck, a dot of a dashed line of
        # the drawing (in a column) or a field of screentone specks around the text is not one.
        cx, cy = centres[label]
        near = [k for k in marks if k != label and abs(centres[k][0] - cx) <= reach and abs(centres[k][1] - cy) <= reach]
        row = [k for k in near if abs(centres[k][1] - cy) <= DOT_SIZE / 2]
        column = [k for k in near if abs(centres[k][0] - cx) <= DOT_SIZE / 2 and k not in row]
        return bool(row) and not column and len(near) <= DOT_CROWD

    def alone(label):
        # A dot sits alone on the flat interior, beside letters or other dots; a fragment of
        # hatching or the end of a speed line has more ink of the drawing right next to it.
        x, y, bw, bh = (int(v) for v in stats[label, :4])
        ya, yb, xa, xb = max(0, y - DOT_CLEAR), y + bh + DOT_CLEAR + 1, max(0, x - DOT_CLEAR), x + bw + DOT_CLEAR + 1
        return not stray[ya:yb, xa:xb].any()

    for label in range(1, count):
        bw, bh, area = stats[label, 2], stats[label, 3], stats[label, 4]
        part = labels == label
        # A dot of punctuation is as thin, but compact: the dots of "..." stayed on the page (One Piece 1161 p4).
        dot = shape_ok[label] and window[part].min() < DOT_INK and alone(label) and in_a_row(label)
        if (depth[part].max() < thin and not dot) or (max(bw, bh) > 1.5 * lh and area < 0.12 * bw * bh):
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
    glyphs = bubble_glyphs(image, box, lh, near=NEAR_LINES, dots=True)
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
        # A dot of punctuation on the row just under or over the text ("SORRY / ...", "... / FIELD / ...").
        return mark and (0 <= gy - y1 <= lh or 0 <= y0 - gy - gh <= lh) and x0 <= gx and gx + gw <= x1
    box_limit = limit.copy()
    queue = [k for k in set(np.unique(labels[limit & glyphs]).tolist()) - {0} if belongs(k, True)]
    rows = [k for k in range(1, count) if k not in queue and belongs(k, False)]
    for side in ([k for k in rows if stats[k, 1] >= y1], [k for k in rows if stats[k, 1] < y1]):
        if not side:
            continue
        # Only a row of dots alone: a letter on the same row makes it a line of text that was not read.
        # For a true "..." (three or more alike dots in a row) a letter farther than a line height
        # is another block (the next column of a caption, One Piece 1161 p4), not a word of its row.
        r0, r1 = min(stats[k, 1] for k in side), max(stats[k, 1] + stats[k, 3] for k in side)
        c0, c1 = min(stats[k, 0] for k in side), max(stats[k, 0] + stats[k, 2] for k in side)
        sizes = [max(stats[k, 2], stats[k, 3]) for k in side]
        middles = [stats[k, 1] + stats[k, 3] / 2 for k in side]
        ellipsis = len(side) >= 3 and max(sizes) <= ELLIPSIS_ALIKE * min(sizes) and np.ptp(middles) <= max(sizes)
        reach = lh if ellipsis else float("inf")
        if not any(stats[k, 1] < r1 and stats[k, 1] + stats[k, 3] > r0 and k not in side and k not in queue
                   and stats[k, 0] < c1 + reach and stats[k, 0] + stats[k, 2] > c0 - reach
                   for k in range(1, count)):
            queue += side
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


SYMBOL_GAP = 0.8    # blank between a drawn symbol and the first letter of its line, in letter heights
SYMBOL_TALL = 0.8   # the symbol is at least this many letter heights tall (dots and commas are not)
SYMBOL_FILL = 0.5   # each of its strokes fills less than this share of its box: curves, not a letter's bar
SYMBOL_DOT = 0.3    # and none is a dot this small (letter heights): "...?" is punctuation
SYMBOL_INK = 110    # ink darker than this (0-255 grey)
SYMBOL_TALLEST = 0.75  # the letter height is read from pieces at least this share of the second tallest
SYMBOL_LETTER = 0.3  # the line's letters are within this share of the usual letter height
SYMBOL_BAND = 0.25  # a letter starts and ends within this many letter heights of the line's row; a symbol's strokes do not
SYMBOL_JOIN = 0.3   # a stroke this close to the symbol (letter heights) and outside every line box joins it


def line_symbols(image, lines):
    """Pixels of a symbol drawn at the end of a line of speech, to be left out of the cleaning.

    One Piece 1161 p8 and 1153 p6: an anger vein beside "HIM?!" and "GO" got into the
    detector's line box and was cleaned with the letters.  A group of two or more curved
    strokes at one end of a line, apart from its letters by a blank of ``SYMBOL_GAP``
    letter heights and at least ``SYMBOL_TALL`` of them tall, is a drawing.  Returns the
    pixels of those strokes, grown by two pixels.
    """
    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY) if np.asarray(image).ndim == 3 else np.asarray(image)
    h, w = gray.shape[:2]
    keep = np.zeros((h, w), bool)
    count, labels, stats, centres = cv2.connectedComponentsWithStats((gray < SYMBOL_INK).astype(np.uint8), connectivity=8)
    boxes = [_box(quad) for quad in ([] if lines is None else lines)]
    for quad in [] if lines is None else lines:
        x0, y0, x1, y1 = _box(quad)
        inside = [k for k in range(1, count) if stats[k, cv2.CC_STAT_AREA] >= 4
                  and x0 <= centres[k][0] <= x1 and y0 <= centres[k][1] <= y1
                  and stats[k, cv2.CC_STAT_WIDTH] < x1 - x0 + 1]  # not the bubble outline running past the line
        if len(inside) < 3:
            continue
        tall = sorted(stats[k, cv2.CC_STAT_HEIGHT] for k in inside)[-2]  # one tall stroke of a drawing does not set it
        height = float(np.median([stats[k, cv2.CC_STAT_HEIGHT] for k in inside
                                  if stats[k, cv2.CC_STAT_HEIGHT] >= SYMBOL_TALLEST * tall]))  # dots do not set it
        inside.sort(key=lambda k: stats[k, cv2.CC_STAT_LEFT])
        found = []
        for end in (inside, inside[::-1]):
            group, rest = [end[0]], end[1:]
            while rest and _x_gap(stats, group, rest[0]) < SYMBOL_GAP * height:
                group.append(rest.pop(0))
            if not rest or len(group) < 2 or len(group) > len(rest):
                continue
            if _x_gap(stats, group, rest[0]) < SYMBOL_GAP * height:
                continue
            top = min(stats[k, cv2.CC_STAT_TOP] for k in group)
            bottom = max(stats[k, cv2.CC_STAT_TOP] + stats[k, cv2.CC_STAT_HEIGHT] for k in group)
            strokes = [(stats[k, cv2.CC_STAT_WIDTH], stats[k, cv2.CC_STAT_HEIGHT], stats[k, cv2.CC_STAT_AREA]) for k in group]
            letters = [k for k in rest if abs(stats[k, cv2.CC_STAT_HEIGHT] - height) <= SYMBOL_LETTER * height]
            if len(letters) < 2:  # the rest is dots or strokes: no row of letters to tell a drawing from
                continue
            band_top = np.median([stats[k, cv2.CC_STAT_TOP] for k in letters])
            band_bottom = np.median([stats[k, cv2.CC_STAT_TOP] + stats[k, cv2.CC_STAT_HEIGHT] for k in letters])

            def in_row(k):
                return (abs(stats[k, cv2.CC_STAT_TOP] - band_top) <= SYMBOL_BAND * height
                        and abs(stats[k, cv2.CC_STAT_TOP] + stats[k, cv2.CC_STAT_HEIGHT] - band_bottom) <= SYMBOL_BAND * height)

            if sum(map(in_row, letters)) < max(2, len(letters) / 2):  # strokes of a drawing are no row to measure by
                continue
            lettered = [k for k in group if in_row(k)]
            if (bottom - top >= SYMBOL_TALL * height and len(lettered) <= 1
                    and all(a / float(sw * sh) < SYMBOL_FILL for sw, sh, a in strokes)
                    and not any(sw <= SYMBOL_DOT * height and sh <= SYMBOL_DOT * height for sw, sh, a in strokes)):
                found.append(group)
        if len(found) == 1:  # both ends alike (a short word beside a drawing): not sure which is which
            group = list(found[0])
            # A stroke of the symbol that pokes out of the line box (its centre outside every line
            # box, so it is no letter that was read) and touches the group is part of it.
            gx0 = min(stats[k, cv2.CC_STAT_LEFT] for k in group) - SYMBOL_JOIN * height
            gx1 = max(stats[k, cv2.CC_STAT_LEFT] + stats[k, cv2.CC_STAT_WIDTH] for k in group) + SYMBOL_JOIN * height
            gy0 = min(stats[k, cv2.CC_STAT_TOP] for k in group) - SYMBOL_JOIN * height
            gy1 = max(stats[k, cv2.CC_STAT_TOP] + stats[k, cv2.CC_STAT_HEIGHT] for k in group) + SYMBOL_JOIN * height
            for k in range(1, count):
                sx, sy, sw, sh = (int(v) for v in stats[k, :4])
                if (k not in group and sx < gx1 and sx + sw > gx0 and sy < gy1 and sy + sh > gy0
                        and max(sw, sh) <= height
                        and not any(bx0 <= centres[k][0] <= bx1 and by0 <= centres[k][1] <= by1 for bx0, by0, bx1, by1 in boxes)):
                    group.append(k)
            for k in group:
                keep |= labels == k
    if keep.any():  # with the anti-aliased rim: grown by a pixel, the cleaner smeared it grey around the strokes
        keep = cv2.dilate(keep.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    return keep


DRAWING_SIZE = 3.0   # an ink piece this many line heights tall or wide is part of the drawing, not a letter
DRAWING_REACH = 1.5  # looked for this far around the lines, in line heights


def drawing_around(image, lines, line_height=None):
    """Pixels of large drawn strokes near ``lines`` that lie outside the line boxes.

    One Piece 1161 p11: a label under a face on a map; the detector mask took the bottom
    of the face, and the bubble was cleaned over it.  Ink joined into a piece much larger
    than a letter is the drawing (or the bubble outline); outside the line boxes it is
    left out of the cleaning, while letters touching it are still cleaned inside them.
    """
    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY) if np.asarray(image).ndim == 3 else np.asarray(image)
    h, w = gray.shape[:2]
    keep = np.zeros((h, w), bool)
    if lines is None or not len(lines):
        return keep
    boxes = [_box(q) for q in lines]
    lh = float(line_height or np.median([b[3] - b[1] for b in boxes]))
    reach = int(round(DRAWING_REACH * lh))
    x0 = max(0, min(b[0] for b in boxes) - reach); y0 = max(0, min(b[1] for b in boxes) - reach)
    x1 = min(w, max(b[2] for b in boxes) + reach + 1); y1 = min(h, max(b[3] for b in boxes) + reach + 1)
    if np.median(gray[y0:y1, x0:x1]) < PAPER_LIGHT:  # light letters on a dark bubble: the dark is what is cleaned
        return keep
    ink = gray < SYMBOL_INK
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    window = labels[y0:y1, x0:x1]
    big = [k for k in np.unique(window) if k and max(stats[k, cv2.CC_STAT_WIDTH], stats[k, cv2.CC_STAT_HEIGHT]) >= DRAWING_SIZE * lh]
    if not big:
        return keep
    part = np.isin(window, big)
    for bx0, by0, bx1, by1 in boxes:
        part[max(0, by0 - y0):max(0, by1 - y0 + 1), max(0, bx0 - x0):max(0, bx1 - x0 + 1)] = False
    keep[y0:y1, x0:x1] = part
    if keep.any():
        keep = cv2.dilate(keep.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    return keep


def _x_gap(stats, group, k):
    """Blank columns between the strokes of ``group`` and stroke ``k`` (either side)."""
    gx0 = min(stats[g, cv2.CC_STAT_LEFT] for g in group)
    gx1 = max(stats[g, cv2.CC_STAT_LEFT] + stats[g, cv2.CC_STAT_WIDTH] for g in group)
    kx0, kx1 = stats[k, cv2.CC_STAT_LEFT], stats[k, cv2.CC_STAT_LEFT] + stats[k, cv2.CC_STAT_WIDTH]
    return max(kx0 - gx1, gx0 - kx1)


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
STACK_WIDE = 2.0      # in a box as tall as wide, rows this many times wider than tall are lines, not stacked letters
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


SAME_BOX = 0.8  # two line boxes overlapping this much (intersection over union) hold the same line


def _same_box(a, b):
    ix = min(a[2], b[2]) - max(a[0], b[0])
    iy = min(a[3], b[3]) - max(a[1], b[1])
    if ix <= 0 or iy <= 0:
        return False
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter >= SAME_BOX * union


TRIM_EDGE = 0.5  # a dropped box is trimmed only over at most this share of the kept line it runs onto


def trim_lost(box, kept):
    """A dropped line box without the rows a kept line box above or below already holds.

    One Piece 1161 p8: the box of "HIM?!" also covered the bottom of "TO FIGHT" above it and a
    drawn vein beside it; too tall for a line, it was never read again and stayed out of the
    speech.  Only rows at the top or bottom edge are cut, never the middle.
    """
    x0, y0, x1, y1 = box
    for kx0, ky0, kx1, ky1 in kept:
        if min(x1, kx1) - max(x0, kx0) <= OVERLAP_SIDE * min(x1 - x0, kx1 - kx0):
            continue
        # Only a box that runs onto the edge of the kept line (its last rows), not half of it:
        # two lines of a logo or a shout overlapping by half are one block, not a lost line.
        if ky0 <= y0 < ky1 < y1 and ky1 - y0 <= TRIM_EDGE * (ky1 - ky0):
            y0 = ky1
        elif y0 < ky0 < y1 <= ky1 and y1 - ky0 <= TRIM_EDGE * (ky1 - ky0):
            y1 = ky0
    return x0, y0, x1, y1


PUNCT_REACH = 1.0  # a line of only punctuation joins a speech line this many line heights above it (or beside it)
PUNCT_SIDE = 0.5   # share of their heights two boxes share to be on the same row
OVERLAP_SIDE = 0.3  # share of the narrower box two boxes share sideways to be in the same column


def punctuation_owners(boxes, texts):
    """{index of a line of only punctuation: index of the speech line it ends}.

    One Piece 1161 p5: "URGH" over "...!!" in one bubble.  The punctuation line, taller than the
    word, was not joined to it and was then dropped as text with no letters: the dots and "!!"
    stayed in English under "Urgh".  It joins the nearest line above it (or below, for a
    leading "...") that overlaps it sideways and is close.
    """
    owners = {}
    for i, (box, text) in enumerate(zip(boxes, texts)):
        if not text or any(ch.isalnum() for ch in str(text)) or not re.search(r"[.!?…‼⁇⁈⁉]", str(text)):
            continue
        x0, y0, x1, y1 = box
        best = None
        for j, (other, words) in enumerate(zip(boxes, texts)):
            if j == i or not any(ch.isalnum() for ch in str(words or "")):
                continue
            ox0, oy0, ox1, oy1 = other
            if min(y1, oy1) - max(y0, oy0) >= PUNCT_SIDE * min(y1 - y0, oy1 - oy0):
                if x0 < ox0:
                    continue  # punctuation on the same row ends the word on its left, not the one after it
                gap = x0 - ox1  # on the same row, right after the word ("WHAT ?!")
            elif min(x1, ox1) - max(x0, ox0) <= OVERLAP_SIDE * min(x1 - x0, ox1 - ox0):
                continue
            else:
                gap = y0 - oy1 if oy1 <= y0 + 0.5 * (y1 - y0) else oy0 - y1
            if gap > PUNCT_REACH * (oy1 - oy0):
                continue
            if best is None or gap < best[0]:
                best = (gap, j)
        if best is not None:
            owners[i] = best[1]
    return owners


def near_lines(lost, kept):
    """Indexes of dropped horizontal lines lying next to a kept line of similar height."""
    height = _line_height(kept) or _line_height(lost)
    if not height or not kept:
        return []
    return [i for i, (x0, y0, x1, y1) in enumerate(lost)
            if 0.5 * height <= y1 - y0 <= SPLIT_FACTOR * height and x1 - x0 > y1 - y0
            and _near((x0, y0, x1, y1), kept, height)]


def repair_lines(mask, boxes, gray=None, rebuild=False):
    """Return (boxes, changes) with multi-line boxes split and missed lines added.

    ``boxes`` are axis-aligned (x0, y0, x1, y1) horizontal text lines and
    ``mask`` is the detector pixel mask of the same page.  Each entry of the
    result is (box, source) where source is the index of the original box, or
    None for a line found only in the mask.  ``gray``, the page in grey levels,
    lets a line box grow over letters the mask missed.  ``rebuild`` adds the lines
    rebuilt to read a speech over the drawing (edge lines, boxes cut at a valley),
    which only "translate everything" translates.
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
        if y1 - y0 < SPLIT_CHECK * height:
            result.append(((x0, y0, x1, y1), index))
            continue
        tall = x1 - x0 <= y1 - y0
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
        rows = float(np.median([p[3] - p[1] for p in parts])) if parts else 0.0
        if tall and (len(parts) < 2 or max(p[2] - p[0] for p in parts) < STACK_WIDE * rows
                     or rows > SPLIT_FACTOR * height):
            # Vertical lettering (Japanese SFX, letters stacked one per row, a giant "DOOM") is never
            # split into rows.  A short block of wide lines of the page's size in a box as tall as it
            # is wide is (One Piece 1153 p6 "YES, / MAJESTY / !!", Grand Blue 106 p22 "CON- / DOMS /
            # ?!": the OCR dropped it).
            result.append(((x0, y0, x1, y1), index))
            continue
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
            # A row of one letter ("I" over "KNEW IT.", Grand Blue 106 p40) is taller than wide and
            # was read as vertical text, then lost: it stays a horizontal line, a little wider.
            parts = [(max(x0, a - (d - b - (c - a)) // 2 - 1), b, min(x1, c + (d - b - (c - a)) // 2 + 1), d)
                     if c - a < d - b <= SPLIT_FACTOR * height else (a, b, c, d) for a, b, c, d in parts]
            result.extend((part, index) for part in parts)
            changes.append(("split", (x0, y0, x1, y1), parts))
        else:
            result.append(((x0, y0, x1, y1), index))
    result = fit_lines(ink, result, height, changes, gray, valley=rebuild)
    # Two detector boxes over the same line (a small one inside a large one) fit to the same
    # letters: one is enough, or the line is read twice ("PIRATES PIRATES", One Piece 1161 p4).
    unique = []
    for box, source in result:
        for k, (other, kept_source) in enumerate(unique):
            if _same_box(box, other):
                # Both boxes together: the fitted one may have lost the end of the line (a
                # title read as "Mayuts", Grand Blue 102 p4).
                unique[k] = ((min(box[0], other[0]), min(box[1], other[1]), max(box[2], other[2]),
                              max(box[3], other[3])), kept_source)
                changes.append(("same", box, [other]))
                break
        else:
            unique.append((box, source))
    result = unique
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
    if gray is not None and rebuild:
        edges = []
        for box in edge_lines(ink, gray, [b for b, _ in result], height):
            # The rest of a line that already has a box ("ONE" after "I'LL GET", past a word gap)
            # widens that box: in two boxes side by side, the line would be read as two speeches.
            same = [k for k, (b, _) in enumerate(result)
                    if max(box[0], b[0]) - min(box[2], b[2]) <= min(box[3] - box[1], b[3] - b[1])
                    and min(box[3], b[3]) - max(box[1], b[1]) >= 0.5 * min(box[3] - box[1], b[3] - b[1])]
            if len(same) == 1:
                b, source = result[same[0]]
                union = (min(b[0], box[0]), min(b[1], box[1]), max(b[2], box[2]), max(b[3], box[3]))
                result[same[0]] = (union, source)
                changes.append(("edge", b, [union]))
            elif not same:
                edges.append(box)
        if edges:
            result.extend((box, None) for box in edges)
            changes.append(("edge", None, edges))
    return result, changes


EDGE_MIN = 0.25  # a strip of mask this many line heights tall, right above or below a line...
EDGE_WIDE = 2.0  # ...and this many line heights wide may be a line the mask holds only in part
EDGE_GAP = 0.5   # at most this many line heights from that line
EDGE_TALL = 1.3  # a strip taller than this many line heights is more than one line


def edge_lines(ink, gray, boxes, height):
    """Lines at the top or bottom of a block that the detector mask holds only in part.

    The mask covered the bottom third of a first line and the top half of a last one, too
    little to be a line: they had no box, the OCR never read them, and the speech stayed in
    English.  Such a strip, as wide as words and right against a known line, grows over the
    dark letters of the page it touches to a box of that line's height.  The letters of a flat
    background added to the mask can make the strip a whole line, joined to the line below by a
    few pixels: neither an orphan line (it touches a box) nor a part of that box.
    """
    known = np.zeros_like(ink)
    for x0, y0, x1, y1 in boxes:
        known[max(0, y0):y1, max(0, x0):x1] = True
    loose = ink & ~known
    # The pieces of one row of words are joined across their spacing.
    join = max(3, int(round(height * 0.6))) | 1
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        cv2.dilate(loose.astype(np.uint8), np.ones((1, join), np.uint8)), connectivity=8)
    found = []
    for label in range(1, count):
        x, y, bw, bh = (int(v) for v in stats[label, :4])
        pixels = (labels[y:y + bh, x:x + bw] == label) & loose[y:y + bh, x:x + bw]
        rows, cols = np.flatnonzero(pixels.any(axis=1)), np.flatnonzero(pixels.any(axis=0))
        if not len(rows):
            continue
        strip = (x + int(cols[0]), y + int(rows[0]), x + int(cols[-1]) + 1, y + int(rows[-1]) + 1)
        sw, sh = strip[2] - strip[0], strip[3] - strip[1]
        for line in boxes:
            lh = line[3] - line[1]
            # Beyond the line's top or bottom (its letters may overhang the box by a row or two).
            middle = (strip[1] + strip[3]) / 2
            gap = max(strip[1] - line[3], line[1] - strip[3])
            if not (lh > 0 and (middle > line[3] or middle < line[1]) and gap <= EDGE_GAP * lh
                    and EDGE_MIN * lh <= sh <= EDGE_TALL * lh):
                continue
            if min(strip[2], line[2]) - max(strip[0], line[0]) <= 0.3 * min(sw, line[2] - line[0]):
                continue
            # The other words of the row, past their spacing, as far as the line beside it reaches.
            lo, hi = max(0, line[0] - lh), min(ink.shape[1], line[2] + lh)
            cols = np.flatnonzero(loose[strip[1]:strip[3], lo:hi].any(axis=0))
            if not len(cols):
                continue
            row = (min(strip[0], lo + int(cols[0])), strip[1], max(strip[2], lo + int(cols[-1]) + 1), strip[3])
            if row[2] - row[0] < EDGE_WIDE * lh:
                continue
            box = _edge_glyphs(gray, known, row, lh)
            if box is not None and not any(_covered(box, [b]) > 0.3 for b in found):
                found.append(box)
            break
    return found


def _edge_glyphs(gray, known, strip, lh):
    """The box of the dark letters the strip lies on, one line tall, or None."""
    sx0, sy0, sx1, sy1 = strip
    gh, gw = gray.shape
    wx0, wx1 = max(0, sx0 - lh), min(gw, sx1 + lh)
    wy0, wy1 = max(0, sy0 - lh), min(gh, sy1 + lh)
    dark = (gray[wy0:wy1, wx0:wx1] < INK_LEVEL) & ~known[wy0:wy1, wx0:wx1]
    count, labels, stats, _ = cv2.connectedComponentsWithStats(dark.astype(np.uint8), connectivity=8)
    on_strip = np.zeros_like(dark)
    on_strip[sy0 - wy0:sy1 - wy0, sx0 - wx0:sx1 - wx0] = True
    letters = []
    for label in range(1, count):
        x, y, bw, bh = (int(v) for v in stats[label, :4])
        # A letter: about as tall as the line, not a stroke of the art running past it.
        if not (0.3 * lh <= bh <= 1.3 * lh and bw <= 2 * lh) or stats[label, 4] < GLYPH_FILL * bw * bh:
            continue
        if (on_strip & (labels == label)).any():
            letters.append((wx0 + x, wy0 + y, wx0 + x + bw, wy0 + y + bh))
    if not letters:
        return None
    # A letter joined to a stroke of the art reaches past the row of the others: it is left out.
    top, bottom = np.median([b[1] for b in letters]), np.median([b[3] for b in letters])
    letters = [b for b in letters if b[1] >= top - 0.3 * lh and b[3] <= bottom + 0.3 * lh]
    x0, y0 = min(b[0] for b in letters), min(b[1] for b in letters)
    x1, y1 = max(b[2] for b in letters), max(b[3] for b in letters)
    # The letters have to reach past the strip to a line's height, and cover most of its width.
    if not (0.6 * lh <= y1 - y0 <= 1.3 * lh) or (x1 - x0) < 0.6 * (sx1 - sx0):
        return None
    # Punctuation at either end ("IN DEBT."), inside the row of letters.
    gap = max(3, int(round(lh * FIT_GAP)))
    for label in range(1, count):
        x, y, bw, bh = (int(v) for v in stats[label, :4])
        mx0, my0, mx1, my1 = wx0 + x, wy0 + y, wx0 + x + bw, wy0 + y + bh
        if my0 >= y0 and my1 <= y1 and bw <= 0.5 * lh and (0 <= x0 - mx1 <= gap or 0 <= mx0 - x1 <= gap):
            x0, x1 = min(x0, mx0), max(x1, mx1)
    return max(0, x0 - 1), max(0, y0 - 1), min(gw, x1 + 1), min(gh, y1 + 1)


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


GLYPH_FILL = 0.15  # a letter fills at least this share of its box; a thin slanted stroke of the art does not
GLYPH_PAPER = 0.6  # and at least this share of the pixels just around it is paper


def _on_paper(window, labels, label, stat):
    """True when the pixels right around a dark piece are mostly paper (or a light halo).

    A letter the detector missed sits on the paper of its line; a piece of the drawing beside
    the line (the bottles on a shelf next to "GO-AGAIN,") is among the greys of the drawing.
    """
    x, y, w, h = (int(v) for v in stat[:4])
    y0, y1, x0, x1 = max(0, y - 2), min(window.shape[0], y + h + 2), max(0, x - 2), min(window.shape[1], x + w + 2)
    piece = (labels[y0:y1, x0:x1] == label).astype(np.uint8)
    ring = (cv2.dilate(piece, np.ones((5, 5), np.uint8)) > 0) & (piece == 0)
    return bool(ring.any()) and float(np.mean(window[y0:y1, x0:x1][ring] >= PAPER_LIGHT)) >= GLYPH_PAPER


def _glyph_span(gray, x0, x1, r0, r1, height, lo, hi):
    """Widen x0..x1 over dark glyphs of the image that sit inside the row band r0..r1.

    The detector mask can miss the first letter of a bold italic word (the "A" of
    "AMOUNT", read "MOUN").  A letter stays inside its line; a bubble outline or
    the art runs above or below it and is never taken.  Neither is the end of a speed
    line that stops at the halo of the letters, as short as a letter but thin and slanted
    (8% of its box, against 25% for the thinnest letter): the box took the black ground
    beside it, and the speech was taken for light letters on black.
    """
    h, w = gray.shape
    margin = max(2, int(round(0.15 * height)))
    reach = int(round(2 * height))
    wx0, wx1 = max(lo, x0 - reach), min(hi, x1 + reach)
    wy0, wy1 = max(0, r0 - margin - 1), min(h, r1 + margin + 1)
    if wx1 <= wx0 or wy1 <= wy0:
        return x0, x1
    window = gray[wy0:wy1, wx0:wx1]
    dark = (window < INK_LEVEL).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(dark, connectivity=8)
    glyphs = [(wx0 + int(sx), wx0 + int(sx + sw)) for k, (sx, sy, sw, sh, area) in enumerate(stats[1:], 1)
              if sy > 0 and sy + sh < wy1 - wy0 and sh >= 0.3 * (r1 - r0) and area >= GLYPH_FILL * sw * sh
              and _on_paper(window, labels, k, stats[k])]
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


def _valley_runs(counts, r0, r1):
    """Rows r0..r1 cut where the ink nearly stops.

    Lines that touch (outlined lettering, tight leading) have a row or two with only a
    few pixels between them.  ``counts`` is the ink per row.
    """
    body = counts[r0:r1]
    valley = body > FIT_VALLEY * float(np.median(body[body > 0]))
    return [(r0 + a, r0 + b) for a, b in _runs(valley, gap=0)]


def fit_lines(ink, items, height, changes, gray=None, valley=False):
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
                runs.extend(_valley_runs(counts, r0, r1))
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
            cut = False
            if valley and len(runs) == 1 and runs[0][1] - runs[0][0] > SPLIT_CHECK * height:
                # Lines with tight leading touch through a stray dot or the tip of a letter: cut
                # where the ink nearly stops, and keep the line that holds the box.  A box 11 px
                # tall over letters 14 px tall, joined to the line above, read "DP".
                pieces = [(a, b) for a, b in _valley_runs(ink[:, x0:x1].sum(axis=1), *runs[0])
                          if b - a >= MIN_PART * height]
                if pieces:
                    runs, cut = [max(pieces, key=lambda p: min(p[1], y1) - max(p[0], y0))], True
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
            changes.append(("valley" if cut else "fit", box, [fitted]))
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


# One line across two bubbles joined side by side ----------------------------------

GAP_SPLIT = 1.0  # blank between two words of a line, in letter heights of the smaller one
GAP_SPECK = 2    # px of blank tolerated inside one word
GAP_PAD = 2      # px kept above and below the letters of each part


def gap_cuts(mask, gray, boxes):
    """{line index: [(x0, y0, x1, y1), ...]} for line boxes across two bubbles that touch.

    One Piece 1161 p7: "?!" in one bubble and "KOFF..." in the bubble grown out of
    it, with no outline between them on the line; the detector drew one box over
    both and the region was taken for art.  A blank as wide as the letters beside it,
    with the outline of the bubbles poking into it, is the seam of the two bubbles.
    Spaced-out words in one bubble have only paper between them and are never cut.
    Dots and specks ride along with the word they follow.
    """
    mask = np.asarray(mask) > 127
    gray = np.asarray(gray)
    cuts = {}
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = int(x1), int(y1)
        ink = mask[y0:y1, x0:x1]
        if not ink.size or x1 - x0 <= y1 - y0:
            continue
        words = _runs(ink.any(axis=0), GAP_SPECK)
        if len(words) < 2:
            continue
        # The mask often covers only part of each letter: their height is read on the page's ink
        # the mask touches; the outline poking in is ink the mask never touches.
        page_ink = gray[y0:y1, x0:x1] < INK_LEVEL
        _, labels = cv2.connectedComponents(page_ink.astype(np.uint8), connectivity=8)
        touched = np.unique(labels[page_ink & ink])
        letters_ink = np.isin(labels, touched[touched > 0]) | ink
        spans_y = []
        for a, b in words:
            rows = np.flatnonzero(letters_ink[:, a:b].any(axis=1))
            spans_y.append((int(rows[0]), int(rows[-1]) + 1))
        heights = [r1 - r0 for r0, r1 in spans_y]
        letters = [h >= MIN_PART * max(heights) for h in heights]

        def word_from(k, step):
            while 0 <= k < len(words) and not letters[k]:
                k += step
            return k if 0 <= k < len(words) else None

        near = cv2.dilate(letters_ink.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        dark = page_ink & ~near
        parts = [[words[0][0], words[0][1], letters[0]]]
        for k in range(1, len(words)):
            a, b = words[k]
            left, right = word_from(k - 1, -1), word_from(k, 1)
            seam = False
            if left is not None and right is not None:
                small = min((left, right), key=lambda j: heights[j])
                r0, r1 = spans_y[small]
                stripe = dark[:, parts[-1][1]:a]
                # Paper all along the smaller letters (a letter the mask missed is dark there),
                # and the outline coming in from the top or the bottom of the box.
                seam = a - parts[-1][1] >= GAP_SPLIT * heights[small] and not stripe[r0:r1].any() \
                    and (stripe[0].any() or stripe[-1].any())
            if seam:
                parts.append([a, b, letters[k]])
            else:
                parts[-1][1] = b
                parts[-1][2] = parts[-1][2] or letters[k]
        spans = []
        for a, b, has_letters in parts:
            if spans and not has_letters:
                spans[-1][1] = b
            elif spans and not spans[-1][2]:
                spans[-1][1:] = [b, True]
            else:
                spans.append([a, b, has_letters])
        if len(spans) >= 2:
            # Each part as tall as its own letters: small letters in the full height of the box are
            # read as noise ("KOFF..." read "46").
            cuts[i] = []
            for a, b, _ in spans:
                rows = np.flatnonzero(letters_ink[:, a:b].any(axis=1))
                cuts[i].append((x0 + a, max(y0, y0 + int(rows[0]) - GAP_PAD), x0 + b,
                                min(y1, y0 + int(rows[-1]) + 1 + GAP_PAD)))
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
DIGIT_WORD_LETTERS = 3  # a word with one stray digit is retried as every letter only with this many letters
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
         "goin", "doin", "nothin", "somethin", "dammit", "huh", "heh", "hmph", "tch", "ugh", "oi", "eh", "uh", "um", "hm"}


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
        lead = re.match(r"[.…]*", h).group(0) if dash else ""  # "...FIRE- BLITZ"
        h = h[len(lead):]
        if re.fullmatch(r"[A-Z]{2,}", h) and re.fullmatch(r"[A-Z]{2,}\W*", tail):
            t = re.match(r"[A-Z]+", tail).group(0)
            whole = h + t
            if dash and f"{h}-{t}".lower() in keep:
                parts[i:i + 3] = [f"{lead}{h}-{tail}"]  # a name of the glossary: "JI- HYUN" -> "JI-HYUN"
                changed += 1
                continue
            if whole.lower() in common and (dash or t.lower() in SUFFIXES
                                            or not (_known(h, common, names) and _known(t, common, names))):
                parts[i:i + 3] = [lead + whole + tail[len(t):]]
                changed += 1
                continue
            if dash and (t.lower() in HONORIFICS or (_known(h, common, names) and _known(t, common, names))):
                parts[i:i + 3] = [f"{lead}{h}-{tail}"]  # "AZUSA- SAN" -> "AZUSA-SAN", "HIGH- SCHOOL" -> "HIGH-SCHOOL"
                changed += 1
                continue
            # A tail that is no word of its own is the rest of a name or a cry ("NEP- TUNIANS",
            # "SHAK- KYYY"), unless it repeats the head, a stutter ("STOP- STOOOOP"), or the head is
            # a word cut short before a name or a cry ("WAIT- ZORAN!") and the whole is no name.
            plain = re.sub(r"(.)\1+", r"\1", t).startswith(re.sub(r"(.)\1+", r"\1", h))
            if (dash and not _known(t, common, names) and not plain
                    and (not _known(h, common, names) or _known(whole, common, names))):
                parts[i:i + 3] = [lead + whole + tail[len(t):]]
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
        # One digit inside a capital word ("ADMIRA4", "7AMMIT") no pair above covers: any letter may
        # have been read as it.  Ordinals and units ("4TH", "10PM") have too few letters or two digits,
        # and a number after a word ("SECTOR7") is not read as a plural "S".
        digits = re.findall(r"\d", core)
        if len(digits) == 1 and len(letters) >= DIGIT_WORD_LETTERS:
            at = core.index(digits[0])
            hits = {c for c in (core[:at] + ch + core[at + 1:] for ch in string.ascii_uppercase
                                if not (ch == "S" and at == len(core) - 1))
                    if c.lower() in common or c.lower() in SLANG}
            if len(hits) == 1:
                changed += 1
                return word.replace(core, hits.pop())
        return word

    fixed = re.sub(r"[A-Za-z0-9/|']*[A-Za-z][A-Za-z0-9/|']*", repl, text)
    return fixed, changed


SUFFIXES = {"ing", "ed", "ly", "er", "ers", "est", "tion", "tions", "ness", "ment", "able", "ful", "less", "ous", "ity"}
HONORIFICS = {"san", "kun", "chan", "sama", "senpai", "sensei", "dono", "nim", "ssi", "hyung", "noona", "oppa", "unnie", "sunbae"}

SFX_SHAPE = re.compile(r"(.)\1\1|(?:OOSH|OOM|OOF|ASH|USH|ANG|ONK|ACK|UNK|RRK|SSH|HH|ZZ|WHAM|THUD|THUMP|SPLA\w*|KR\w+)$")
# Cries a Brazilian reader reads the same as they are drawn: stretched out ("AAAAH") they stay drawn.
SAME_CRY = {"ah", "oh", "uh", "eh", "ha", "hah", "ugh"}


def english_sound_effect(text):
    """One lettered word that is no English word and looks like an onomatopoeia ("VLOOSH", "SPLOOSH").

    Grand Blue p53: "SPLOOSH", drawn across the art and read "VLOOSH", was erased
    and written as "Vluuuf".  Real words ("BOB", "NO!") are left to the translator,
    also when a shout stretches them ("YEAAAH", One Piece 1161 p16, stayed in English).
    """
    common, names = english_words()

    def join(match):
        # A cry broken over two lines ("GYAA- / AAA!!", One Piece 1161 p7) is one word; a stutter
        # ("NO- NOOOO!") or a real word on either side ("SOME- THING") stays apart.
        left, right = match.group(1), match.group(2)
        plain = re.sub(r"(.)\1+", r"\1", right.lower())
        if plain.startswith(re.sub(r"(.)\1+", r"\1", left.lower())) or left.lower() in common \
                or (len(plain) > 1 and plain in common) or right.lower() in common:
            return match.group(0)
        return left + right
    text = re.sub(r"([A-Za-z]+)-\s+([A-Za-z]+)", join, text or "")
    words = re.findall(r"[A-Za-z]+", text)
    # A lone letter that is no word ("R", a piece of the vertical "KRRK" on Grand Blue
    # p19, was written over as "É.") is a piece of a drawn sound.
    if len(words) == 1 and len(words[0]) == 1 and words[0].upper() not in "IAO" \
            and not re.search(r"[?!]", text):
        return True
    if len(words) != 1 or len(words[0]) < 4 or words[0] != words[0].upper():
        return False
    word = words[0].lower()
    if not common or word in common or word in names:
        return False
    for short in {re.sub(r"(.)\1{2,}", r"\1", word), re.sub(r"(.)\1{2,}", r"\1\1", word)}:
        if short != word and short in common and re.search("[aeiouy]", short) and short not in SAME_CRY \
                and not SFX_SHAPE.search(short.upper()):
            return False
    return bool(SFX_SHAPE.search(words[0]))
