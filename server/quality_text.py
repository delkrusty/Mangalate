"""Text spacing, line and block grouping and sentence case of the translated text.

Split out of quality.py; ``quality`` re-exports every name.
"""

import re

import numpy as np


STACKED = 2.5  # a line box this many times taller than wide holds letters stacked one per row


def stacked(quads):
    """True when every line box is a column of letters stacked one per row ("GUYS!" in a tall bubble)."""
    quads = [np.asarray(q, np.float32).reshape(4, 2) for q in quads]
    return bool(quads) and all(np.ptp(q[:, 1]) > STACKED * max(float(np.ptp(q[:, 0])), 1.0) for q in quads)


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
