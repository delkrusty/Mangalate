"""Checks on the read and translated text: speech or sound, negation, gender and English left over.

Split out of quality.py; ``quality`` re-exports every name.
"""

import re

from quality_text import page_names
from quality_words import _contractions, english_words


# Small words of speech: a word the OCR ran into its neighbour is split only next to one of these.
SPEECH_WORDS = {"i", "a", "is", "it", "its", "the", "this", "that", "you", "he", "she", "we", "they", "me", "my",
                "no", "not", "of", "to", "in", "on", "and", "so", "be", "am", "are", "was", "do", "what", "who"}


def run_together(word, common):
    """``word`` as two words when the OCR read them without the space ("THISIS"), else [word].

    Webtoon p41: "THIS IS..." in a condensed font came back as one word that is not in the
    dictionary, and the bubble was kept as a drawn sound.  The split needs two dictionary
    words, one of them a small word of speech, so "BADUMP" or "AHAHA" stay one sound.  A name
    ("NOAH"), a word with an apostrophe, a repeated syllable ("HEHE") and a word with more than
    one such split ("INEVER": "IN EVER" or "I NEVER") stay whole: a wrong space misleads the AI.
    """
    low = word.lower()
    if "'" in low or low in common or low in english_words()[1]:
        return [word]
    def word_ok(part):
        return part in SPEECH_WORDS or len(part) >= 2 and (part in common or part in _contractions(common))
    cuts = []
    for i in range(1, len(low) - 1):  # "I" and "A" are words of one letter
        head, tail = low[:i], low[i:]
        if head != tail and (head in SPEECH_WORDS or tail in SPEECH_WORDS) and word_ok(head) and word_ok(tail):
            cuts.append(i)
    return [word[:cuts[0]], word[cuts[0]:]] if len(cuts) == 1 else [word]


def spaced_words(text):
    """A one-word ``text`` with the space back between words the OCR ran together ("THISIS" -> "THIS IS").

    Only a lone word: in a longer line the AI has the context, and a wrong split would mislead it.
    """
    common, _ = english_words()
    words = re.findall(r"[A-Za-z']+", text or "")
    if len(words) != 1:
        return text
    return re.sub(r"[A-Za-z']+", lambda m: " ".join(run_together(m.group(0), common)), text)


def reads_as_speech(text, several_rows=False, joined=False):
    """True when a scanned bubble's OCR text reads as an English line, not a drawn sound.

    A line has a common English word and either two words or end punctuation:
    "MUSCLE?", "I SEE." yes; "GRAB" (a sound in a jagged box) or "REEE" no.  ``joined`` also
    reads one word as two run together ("THISIS"); only the bubble scan asks for it, never the
    checks for a logo or a speech over the drawing, where a word kept whole keeps the art.
    """
    common, _ = english_words()
    words = re.findall(r"[A-Za-z']+", text or "")
    if joined and len(words) == 1:  # "THISIS": two words the OCR ran together
        words = run_together(words[0], common)
    if not words or not any(len(w) >= 2 and (w.lower() in common or w.lower().replace("'", "") in _contractions(common))
                            for w in words):
        return False
    # A comma ends a line that goes on in the next caption (webtoon p36: "NO," alone in a box).
    return several_rows or len(words) >= 2 or bool(re.search(r"[.!?…,-]\W*$", text.strip()))


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
    r"\b(?:not|never|nobody|nothing|none|neither|nor|no one|cannot|without)\b|\b" + NT + r"\b|\bno\s+\w|"
    # A bare "NO," or "OH NO!" (webtoon p36: "NO," alone in a caption came back "Ora,"), not "NO. 1".
    r"\bno\b\s*(?:[,!?…]|\.(?!\s*\d)|$)", re.I)
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
# A singular verb before a plural participle, or a plural verb before a masculine singular one:
# "foi mortos" (Manwha teste p64, "...HAS BEEN KILLED!"), "foram derrotado".  A feminine noun
# after a plural verb is no participle ("são comida", "são piada"), and "a gente foi convidados"
# is spoken Portuguese.
_PARTICIPLE = r"(?:[\wÀ-ÿ]{2,}[ai]d|mort|pres|feit|dit|vist|abert|post|escrit|cobert|pag|salv|solt|extint)"
PARTICIPLE_NUMBER = re.compile(
    r"(?<![\wÀ-ÿ])(?:(?:foi|é|era|está|estava|ficou|será|seria)\s+" + _PARTICIPLE + r"[oa]s"
    r"|(?:foram|são|eram|estão|estavam|ficaram|serão|seriam)\s+" + _PARTICIPLE + r"o)(?![\wÀ-ÿ])", re.I)
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
    match = next((m for m in PARTICIPLE_NUMBER.finditer(text or "")
                  if not re.search(r"(?<![\wÀ-ÿ])a gente\s*$", text[:m.start()], re.I)), None)
    if match:
        notes.append(f"\"{match.group(0)}\" mixes singular and plural: make the verb and the participle agree")
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
