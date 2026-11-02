"""OCR letter mix-ups in comic capitals and the bundled English word list.

Split out of quality.py; ``quality`` re-exports every name, so ``quality.fix_ocr_words`` still works.
"""

import re
import string


# OCR letter mix-ups in comic capitals -------------------------------------------

# What the OCR read -> what the letterer drew.  Only words the list does not know
# are touched, and only when exactly one common word comes out.
OCR_CONFUSIONS = (("LI", "U"), ("LJ", "U"), ("IJ", "U"), ("E", "F"), ("F", "E"), ("O", "D"), ("O", "C"), ("O", "Q"),
                  ("C", "D"), ("I", "D"), ("I", "L"), ("I", "T"), ("L", "I"), ("0", "O"), ("1", "I"), ("5", "S"),
                  ("7", "T"), ("8", "B"), ("/", "I"), ("|", "I"), ("VV", "W"), ("RN", "M"), ("Q", "O"))
OCR_FINAL_L = 5  # a final "L" read as "A" after an "A" ("HOSPITAA") is undone in words this long (letters)
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
            # Anywhere else an "L" read as "A" turned cries and names into words ("GAA!", "MAIA").
            if len(w) >= OCR_FINAL_L and w.endswith("AA"):
                nxt.add(w[:-1] + "L")
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

    # The last letter of a word echoed after its punctuation at the end of the speech: "NICE CONTROL,L"
    # for "NICE CONTROL." (Manga teste p15), which the translator reads as the start of the next speech.
    # Inside the speech the letter may be a glued word ("HI,I KNOW") or a stutter ("WAIT,T-THAT").
    def echo(match):
        nonlocal changed
        if not _known(match.group(1), common, names):
            return match.group(0)
        changed += 1
        return match.group(1) + match.group(3)

    text = re.sub(r"\b([A-Z]+([A-Z]))([,.!?])\2(?=\s*$)", echo, text)

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


def misread_names(text, names):
    """Known names of several words the OCR may have read with one letter off.

    Manwha teste p64: a name like MARA KELL was read "MARA TELL"; "tell" is an English word, so
    fix_ocr_words left it and the AI lettered the wrong name.  The text is not changed:
    "DID MARA TELL YOU?" is a name and a verb, and only the AI can tell them apart, so the
    pairs go to it as a hint (memory.context_block).  A pair needs a name of two or more
    words with exactly one word off by one letter (same length, 3+ letters), the word read
    an English word and the name's word not one (the OCR misreads into words, not out of
    them: "KIM MINJI" is never a hint for "KIM MINJU"), and a matching word the word list
    does not know (not "RED DRAGON" for "BED DRAGON").  Returns [(words read, name), ...].
    """
    common, _ = english_words()
    found = []
    for name in names:
        parts = [p.upper() for p in re.findall(r"[A-Za-z]+", str(name or ""))]
        if len(parts) < 2 or " ".join(parts) != str(name).strip().upper():
            continue
        pattern = r"(?<![A-Za-z])" + r"\s+".join(r"([A-Za-z]{%d})" % len(p) for p in parts) + r"(?![A-Za-z])"
        for match in re.finditer(pattern, text or ""):
            words = [w.upper() for w in match.groups()]
            off = [k for k, (w, p) in enumerate(zip(words, parts)) if w != p]
            if len(off) != 1 or match.group(0) != match.group(0).upper():
                continue
            k = off[0]
            if (len(parts[k]) < 3 or sum(a != b for a, b in zip(words[k], parts[k])) != 1
                    or parts[k].lower() in common or words[k].lower() not in common
                    or all(p.lower() in common for j, p in enumerate(parts) if j != k)):
                continue
            pair = (" ".join(words), str(name).strip())
            if pair not in found:
                found.append(pair)
    return found


SUFFIXES = {"ing", "ed", "ly", "er", "ers", "est", "tion", "tions", "ness", "ment", "able", "ful", "less", "ous", "ity"}
HONORIFICS = {"san", "kun", "chan", "sama", "senpai", "sensei", "dono", "nim", "ssi", "hyung", "noona", "oppa", "unnie", "sunbae"}

SFX_SHAPE = re.compile(r"(.)\1\1|(?:OOSH|OOM|OOF|ASH|USH|ANG|ONK|ACK|UNK|RRK|SSH|HH|ZZ|WHAM|THUD|THUMP|SPLA\w*|KR\w+)$")
# Cries a Brazilian reader reads the same as they are drawn: stretched out ("AAAAH") they stay drawn.
SAME_CRY = {"ah", "oh", "uh", "eh", "ha", "hah", "ugh"}
# Sounds that are English words too: alone in a block (or repeated, "KNOCK KNOCK") they are an
# action drawn on the page, not speech; in a sentence ("CLICK IT!") they are words.
SOUND_WORDS = {"click", "clack", "clank", "clang", "clink", "bang", "boom", "crash", "crack", "creak", "snap",
               "slam", "thunk", "tap", "knock", "beep", "buzz", "pop", "whoosh", "swoosh", "swish", "splash",
               "splat", "drip", "gulp", "sniff", "smack", "thwack", "whack", "zap", "ding", "dong", "rumble",
               "rattle", "crunch", "munch", "sizzle", "tick", "tock", "flick", "flap", "clap", "slurp", "squeak"}


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
    # A letter read twice at the end of a column ("K CLICK") is no word of its own.  A question,
    # a comma or a full stop ("BOOM?", "KNOCK, KNOCK.") is someone saying the word.
    whole = [w for w in words if len(w) > 1 or w.upper() in "IAO" or not any(w.upper() in o.upper() for o in words if len(o) > 1)]
    if whole and not re.search(r"[?,]|(?<!\.)\.(?!\.)", text) \
            and all(w.lower() in SOUND_WORDS and w == w.upper() for w in whole) \
            and len(set(w.lower() for w in whole)) <= 2:
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
