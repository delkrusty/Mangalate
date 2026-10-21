# SPDX-License-Identifier: GPL-3.0-only
"""Mangalate adaptations of the separately executed GPL engine, 2026-10-13.

Based on NLLBTranslator at:
https://github.com/zyddnys/manga-image-translator/blob/d6de6ab62a7be6afc0d07a3184149cdefbcd32f2/manga_translator/translators/nllb.py
Retains GPL-3.0 licensing. No warranty; upstream LICENSE is in the Docker source tree.
"""
import os


def translate_nllb_batch(self, from_lang, to_lang, queries):
    import torch
    self.tokenizer.src_lang = from_lang
    encoded = self.tokenizer(queries, return_tensors="pt", padding=True,
                             truncation=True, max_length=512)
    encoded = {key: value.to(self.device) for key, value in encoded.items()}
    # lang_code_to_id was removed from current Transformers tokenizers.
    target_id = self.tokenizer.convert_tokens_to_ids(to_lang)
    if target_id is None or target_id == self.tokenizer.unk_token_id:
        raise ValueError("Unsupported NLLB target language")
    with torch.no_grad():
        generated = self.model.generate(**encoded, forced_bos_token_id=target_id,
                                        max_length=512, num_beams=5)
    result = self.tokenizer.batch_decode(generated, skip_special_tokens=True)
    unchanged = sum(a.strip().lower() == b.strip().lower() for a, b in zip(queries, result))
    print(f"NLLB: source={from_lang} target={to_lang} rows={len(queries)} unchanged={unchanged}", flush=True)
    if len(result) != len(queries) or any(not text.strip() for text in result):
        raise ValueError("NLLB returned incomplete translations")
    return result


async def load_nllb(self, from_lang, to_lang, device):
    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
    self.device = device if device == "cpu" or ":" in device else device + ":0"
    # Use the same directory as upstream's explicit download/cache check.
    self.tokenizer = AutoTokenizer.from_pretrained(self._TRANSLATOR_MODEL,
                                                   cache_dir=self._MODEL_SUB_DIR)
    self.model = AutoModelForSeq2SeqLM.from_pretrained(self._TRANSLATOR_MODEL,
                                                      cache_dir=self._MODEL_SUB_DIR)
    self.model = self.model.to(self.device)
    self.model.eval()


async def infer_nllb(self, from_lang, to_lang, queries):
    if from_lang == "auto":
        if not hasattr(self, "_mangalate_langid"):
            from py3langid.langid import LanguageIdentifier, MODEL_FILE
            from manga_translator.translators.nllb import ISO_639_1_TO_FLORES_200
            detector = LanguageIdentifier.from_model_file(MODEL_FILE, norm_probs=True)
            detector.set_languages(list(ISO_639_1_TO_FLORES_200))
            self._mangalate_langid = detector
        detected = self._mangalate_langid.classify("\n".join(queries))[0]
        from_lang = self._map_detected_lang_to_translator(detected)
        if from_lang is None:
            raise ValueError("NLLB could not resolve source language")
    return self._translate_batch(from_lang, to_lang, queries)


_POOL = None


def provider_pool():
    """Rotation pool when setup.py stored several providers; None for one key."""
    global _POOL
    if _POOL is None:
        import os
        from pathlib import Path
        from providers import ProviderPool, parse_secret
        try:
            text = Path(os.environ.get("MANGALATE_API_KEY_FILE", "/run/secrets/provider_key")).read_text()
        except OSError:
            text = ""
        providers = parse_secret(text)
        _POOL = ProviderPool(providers) if providers else False
        if providers:
            print("BYOK: alternância entre " + ", ".join(p["name"] for p in providers), flush=True)
    return _POOL or None


def provider_client(pool, provider):
    import openai
    clients = pool.__dict__.setdefault("clients", {})
    if provider["name"] not in clients:
        clients[provider["name"]] = openai.AsyncOpenAI(api_key=provider["key"], base_url=provider["base"],
                                                       max_retries=0)
    return clients[provider["name"]]


def parse_numbered_lines(content, count):
    """Fallback for models that number lines as '1.', '1)', '[1]' or '<1>' instead of '<|1|>'.

    Accepted only when the numbers are exactly 1..count, in order, one per line,
    so a merged, missing or reordered bubble is still rejected.
    """
    import re
    pattern = re.compile(r"^\s*(?:<\|?(\d+)\|?>|\[(\d+)\]|(\d+)[.):])\s*(.*)$")
    numbers, texts = [], []
    for line in content.strip().splitlines():
        match = pattern.match(line)
        if match:
            numbers.append(int(next(g for g in match.groups()[:3] if g)))
            texts.append(match.group(4).strip())
        elif line.strip() and texts:
            texts[-1] = (texts[-1] + " " + line.strip()).strip()
        elif line.strip():
            return None
    if numbers != list(range(1, count + 1)) or any(not text for text in texts):
        return None
    return texts


def parse_plain_lines(content, count):
    """Fallback for answers with one translation per line and no markers at all.

    Accepted only when there are exactly `count` non-empty lines (Grand Blue 87:
    Groq answered 8 correct lines for 8 bubbles, without markers).
    """
    import re
    lines = [line.strip() for line in content.strip().splitlines() if line.strip()]
    # Numbered answers are judged only by parse_numbered_lines: a reordered "1. 3. 2."
    # must never be accepted here as plain lines.
    if any(re.match(r"^(?:<\|?\d+\|?>|\[\d+\]|\d+[.):])", line) for line in lines):
        return None
    return lines if count > 1 and len(lines) == count else None


# A marker the model mangled but whose number is clear: "<|5;|&gt;" (op1153-8a p14, Gemini).
MARKER = r"<\|(\d+)[;:,.]?\|(?:>|&gt;)"


def parse_marked(content, count):
    import re
    markers = list(re.finditer(MARKER, content))
    # One empty marker right after the last bubble ("<|10|>" before the terms line) is not a bubble.
    if markers and int(markers[-1].group(1)) == count + 1 and not content[markers[-1].end():].strip():
        content = content[:markers.pop().start()]
    if not markers and count == 1 and content:
        return [content]
    if not markers:
        fallback = parse_numbered_lines(content, count)
        if fallback is None:
            fallback = parse_plain_lines(content, count)
        if fallback is not None:
            return fallback
    if [int(marker.group(1)) for marker in markers] != list(range(1, count + 1)):
        raise ValueError("BYOK returned missing, duplicate or reordered markers")
    if content[:markers[0].start()].strip():
        raise ValueError("BYOK returned extra content before translations")
    translations = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(content)
        text = content[marker.end():end].strip()
        if not text:
            raise ValueError("BYOK returned an empty bubble")
        translations.append(text)
    return translations


# Work memory for the page being translated (memory.WorkMemory.context), set by the
# caller before each page like the page rows; terms the AI listed are collected here.
# Context variables: two pages can be in flight at once (core.py), each with its own.
import contextvars

_PAGE_CONTEXT = contextvars.ContextVar("mangalate_page_context", default=None)
_LEARNED_TERMS = contextvars.ContextVar("mangalate_learned_terms", default=None)
_PAGE_ROWS = contextvars.ContextVar("mangalate_page_rows", default=None)


def page_context():
    return _PAGE_CONTEXT.get()


def _learned():
    terms = _LEARNED_TERMS.get()
    if terms is None:
        terms = []
        _LEARNED_TERMS.set(terms)
    return terms


def set_page_context(context):
    _PAGE_CONTEXT.set(context)
    _LEARNED_TERMS.set([])


def take_learned_terms():
    terms = list(_learned())
    _LEARNED_TERMS.set([])
    return terms


def strip_terms(content):
    """(answer without the optional <|termos|> line, terms); kept only if the answer parses."""
    if page_context() is None:
        return content, []
    from memory import split_terms
    return split_terms(content)


async def request_byok_translation(self, to_lang, prompt, client=None, model=None):
    system = self.chat_system_template.format(to_lang=to_lang)
    if page_context() is not None:
        from memory import context_block
        system += context_block(page_context(), prompt)
    messages = [{"role": "system", "content": system}]
    sample = self.get_chat_sample(to_lang)
    if sample:
        messages.extend([{"role": "user", "content": sample[0]},
                         {"role": "assistant", "content": sample[1]}])
    messages.append({"role": "user", "content": prompt})
    model = model or self.model
    if not model:
        from manga_translator.translators.keys import CUSTOM_OPENAI_MODEL
        model = CUSTOM_OPENAI_MODEL
    client = client or self.client
    from providers import short_reasoning
    extra = {"extra_body": {"reasoning_effort": "low"}} if short_reasoning(getattr(client, "base_url", ""), model) else {}
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=self._MAX_TOKENS,
        temperature=self.temperature,
        top_p=self.top_p,
        **extra,
    )
    if isinstance(response, (str, bytes)):
        from providers import NotAnAnswer
        raise NotAnAnswer("BYOK address did not answer as a chat API")
    if not getattr(response, "choices", None):
        raise ValueError("BYOK returned no choices")
    choice = response.choices[0]
    content = getattr(getattr(choice, "message", None), "content", None)
    if not isinstance(content, str) or not content.strip():
        raise ValueError("BYOK returned empty content")
    if getattr(choice, "finish_reason", None) == "length":
        raise ValueError("BYOK answer cut by max_tokens")
    usage = response.usage
    self.token_count_last = (getattr(usage, "total_tokens", 0) or 0) if usage else 0
    self.token_count += self.token_count_last
    return content


async def translate_byok(self, from_lang, to_lang, queries):
    import asyncio
    translations = []
    # Avoid the upstream loop which restarts still-running paid requests.
    self.client.max_retries = 0
    from providers import AI_TIMEOUT
    pool = provider_pool()
    offset = 0
    for prompt, count in self._assemble_prompts(from_lang, to_lang, queries):
        sources = list(queries[offset:offset + count])
        offset += count
        if pool:
            async def ask(provider, prompt):
                content = await asyncio.wait_for(
                    self._request_translation(to_lang, prompt, provider_client(pool, provider), provider["model"]),
                    timeout=AI_TIMEOUT)
                answer, terms = strip_terms(content)
                extracted = (self.extract_capture_groups(answer, rf"{self.rgx_capture}") or "").strip()
                return content, extracted, terms

            async def attempt(provider, prompt=prompt, count=count, sources=sources):
                content, extracted, terms = await ask(provider, prompt)
                try:
                    parsed = parse_marked(extracted, count)
                except ValueError as exc:
                    # Kept in memory for the local --diagnostics report only; never logged.
                    pool.__dict__.setdefault("raw", []).append((provider["name"], count, prompt, content))
                    # One second try with the marker problem pointed out before the page goes to
                    # the next AI (op1153-6a: Gemini merged two bubbles on three pages and the
                    # weaker reserve wrote Spanish).  A limit or timeout here rests the provider.
                    print("Second try: answer out of format", flush=True)
                    content, extracted, terms = await ask(provider, prompt + "\n\n" + marker_note(extracted, count))
                    try:
                        parsed = parse_marked(extracted, count)
                    except ValueError:
                        pool.__dict__["raw"].append((provider["name"], count, prompt, content))
                        raise exc
                notes = answer_problems(sources, parsed)
                if notes:
                    # One second try with the problems pointed out; the better answer stays.
                    from quality import UNCHANGED_NOTE
                    same = sum(UNCHANGED_NOTE in note for note in notes)
                    print(f"Second try: {len(notes)} problem(s) in the answer"
                          + (f", {same} returned unchanged" if same else ""), flush=True)
                    try:
                        _, again, again_terms = await ask(provider, prompt + "\n\nA previous answer had these problems; "
                                                          "avoid them and keep every marker:\n" + "\n".join(notes))
                        retried = parse_marked(again, count)
                        if len(answer_problems(sources, retried)) < len(notes):
                            parsed, terms = retried, again_terms
                    except Exception as exc:
                        if type(exc).__name__ == "AllProvidersResting":
                            raise
                _learned().extend(terms)
                return parsed
            translations += await pool.run(attempt)
            continue
        content = await asyncio.wait_for(self._request_translation(to_lang, prompt), timeout=180)
        answer, terms = strip_terms(content)
        translations += parse_marked(self.extract_capture_groups(answer, rf"{self.rgx_capture}").strip(), count)
        _learned().extend(terms)
    return translations


def marker_note(answer, count):
    """What was wrong with the markers of an answer, for the second try (no answer text)."""
    import re
    found = [int(n) for n in re.findall(MARKER, answer or "")]
    missing = [n for n in range(1, count + 1) if n not in found]
    twice = sorted({n for n in found if found.count(n) > 1})
    extra = sorted({n for n in found if n > count})
    problems = ([f"missing {', '.join(f'<|{n}|>' for n in missing)}"] if missing else []) + \
               ([f"repeated {', '.join(f'<|{n}|>' for n in twice)}"] if twice else []) + \
               ([f"no region {', '.join(f'<|{n}|>' for n in extra)}"] if extra else [])
    if not problems:
        problems = ["text before <|1|> or an empty region"] if found == list(range(1, count + 1)) \
            else ["markers out of order"]
    return ("A previous answer broke the format (" + "; ".join(problems) +
            f"). Answer again with exactly {count} lines, <|1|> to <|{count}|> in order, one translation per "
            "marker: never merge two regions into one, even when they form one sentence.")


def answer_problems(sources, translations):
    """Dropped names and unfounded feminine forms (quality.translation_problems) for this page."""
    from quality import translation_problems
    context = page_context() or {}
    earlier = " ".join(pair.get("original", "") for page in context.get("previous") or []
                       for pair in (page if isinstance(page, list) else []) if isinstance(pair, dict))
    return translation_problems(sources, translations, context.get("glossary") or [], earlier)


def validate_byok_results(original_translate):
    async def translate(self, from_lang, to_lang, queries):
        result = await original_translate(self, from_lang, to_lang, queries)
        if len(result) != len(queries) or any(not isinstance(text, str) or not text.strip() for text in result):
            raise ValueError("BYOK returned incomplete translations")
        return result
    return translate


def legacy_quality():
    """MANGALATE_LEGACY_QUALITY=true restores 0.5.2 cleanup/spacing for A/B comparison."""
    import os
    return os.environ.get("MANGALATE_LEGACY_QUALITY", "false").lower() == "true"


def protect_art(config):
    # Profiles keep ignore_bubble=8 as the "protect text on artwork" switch;
    # the gateway sets it to 0 when MANGALATE_ALLOW_ART_TEXT=true.
    value = getattr(config.ocr, "ignore_bubble", 0) or 0
    return 1 <= value <= 50


# Rows of the page inside the strip being translated (seams.Strip), set by the
# caller before each page (a context variable, see the page context above).
def set_page_rows(top, bottom):
    _PAGE_ROWS.set((int(top), int(bottom)))


def on_page(regions, rows):
    """Regions whose text touches the page rows; the rest lie wholly in borrowed context.

    TBATE (new episode) p6: the top of a bubble belonging to p7, cut by the end
    of the borrowed strip, was sent to the AI as "AWW, THATS N" and came back
    untranslated.  Such regions are never part of the page and only confuse the
    translation, so they are dropped before it.
    """
    if not rows:
        return list(regions), []
    top, bottom = rows
    inside, outside = [], []
    for region in regions:
        y0, y1 = float(region.xyxy[1]), float(region.xyxy[3])
        (inside if y1 > top and y0 < bottom else outside).append(region)
    return inside, outside


def is_sound_effect(text):
    """Japanese lettering in an English scan is a sound effect drawn on the art.

    Grand Blue 87 p6: the line repair joined "BOB" to the kana "ぷか" below it;
    the OCR read "BOBふ。か", the AI answered "Bob?" and the effect was erased.
    Kana or kanji with only a few Latin letters around them is left as drawn.
    """
    import re
    from quality import english_sound_effect
    text = str(text or "")
    if not re.search(r"[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]", text):
        return english_sound_effect(text)
    return len(re.findall(r"[A-Za-z]", text)) < 12


CREDIT = None


def is_credit(text):
    """Title, credit and scan-group lettering stays as drawn.

    TBATE new p84 "THE BEGINNING AFTER™END"; TBATE 236 p27 the "thunderscans"
    watermark was translated; TBATE 240 p68 "Original Art by: YOYO" became "Arte original por: YOY".
    A chapter subtitle read with its staff ("By ... Translation: ... Lettering: ...", One Piece
    1153 p1) would otherwise be cleaned and written over as one paragraph.
    """
    import re
    global CREDIT
    if CREDIT is None:
        CREDIT = re.compile(r"[™©®]|\b\w{3,}scans?\b|discord|patreon|ko-?fi|www\.|\.(?:com|net|org|gg)\b"
                            r"|by\s*:|\b(?:tl|pr|ts|qc|raws?|editor|proofreader|typesetter|translator|cleaner|redrawer)\s*:"
                            r"|\b(?:translation|lettering|letterer|illustrations?)\s*:"
                            r"|\btapa\w*\W{0,3}origin"
                            r"|read (?:the |this |more |latest )?chapters? (?:at|on)|support us|our (?:web)?site",
                            re.I)
    return bool(CREDIT.search(str(text or "")))


CREDIT_ROLE = None


def credits_page(regions):
    """Two or more staff credits ("Story and adaptation by:", "Original Art by:") make a credits page."""
    import re
    global CREDIT_ROLE
    if CREDIT_ROLE is None:
        CREDIT_ROLE = re.compile(r"by\s*:|adaptation|original art|story and|produced\s*by", re.I)
    return sum(bool(CREDIT_ROLE.search(str(getattr(r, "text", "") or ""))) for r in regions) >= 2


def credit_followers(regions):
    """Ids of the lines right below a credit: "Original Art by:" / "EternalUwU, chacha" (TBATE 240 p68)."""
    from quality import same_block
    credits = [r for r in regions if is_credit(getattr(r, "text", ""))]
    follow = set()
    for region in regions:
        if any(c is region for c in credits):
            continue
        try:
            if any(same_block(c, region) for c in credits):
                follow.add(id(region))
        except (AttributeError, TypeError, ValueError):
            pass
    return follow


# A bubble's interior is at least this many times the text box's area; the search clips
# open sides to the box, so a fill no larger than the box is open page around the text, not a bubble.
BUBBLE_BEYOND_BOX = 1.1


def join_split_blocks(regions, image, text_mask=None):
    """One speech the detector split in two stacked regions becomes one region again.

    Otherwise each piece is translated alone ("o de verdade" / "Treino") and
    both translations are fitted to the same bubble, one over the other.
    """
    import cv2
    import numpy as np
    import lettering
    from quality import join_blocks, absorb_contained, column_groups, block_groups, paragraph_of, text_blocks, _box

    page_blocks = None
    if text_mask is not None:
        try:
            page_blocks = text_blocks(np.asarray(text_mask),
                                      [_box(q) for r in regions for q in np.asarray(getattr(r, "lines", []))])
        except Exception:  # never lose a page over this
            page_blocks = None

    def inside(a, b):
        # Two paragraphs side by side, separated below, are two speeches even in one open bubble.
        if getattr(a, "mangalate_block", None) is not None and getattr(b, "mangalate_block", None) is not None                 and a.mangalate_block[0] == b.mangalate_block[0] and a.mangalate_block[1] != b.mangalate_block[1]:
            return False
        ax0, ay0, ax1, ay1 = (int(v) for v in a.xyxy)
        found = lettering.bubble_mask(image, (ax0, ay0, ax1, ay1))
        if found is not None:
            mask, wx0, wy0 = found
            # The letters are holes in the flat interior; fill them so a point on a glyph counts.
            contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            mask = cv2.drawContours(np.zeros(mask.shape, np.uint8), contours, -1, 1, -1) > 0
            if mask.sum() < BUBBLE_BEYOND_BOX * (ax1 - ax0) * (ay1 - ay0):
                found = None
        if found is None:
            # Text written on the page, no bubble: the pieces of one paragraph are one speech.
            if page_blocks is None:
                return False
            pa = paragraph_of(page_blocks, [_box(q) for q in np.asarray(a.lines)])
            return pa is not None and pa == paragraph_of(page_blocks, [_box(q) for q in np.asarray(b.lines)])
        bx0, by0, bx1, by1 = (int(v) for v in b.xyxy)
        cx, cy = (bx0 + bx1) // 2 - wx0, (by0 + by1) // 2 - wy0
        return 0 <= cy < mask.shape[0] and 0 <= cx < mask.shape[1] and bool(mask[cy, cx])

    def make(a, b):
        return type(a)(np.concatenate([np.asarray(a.lines), np.asarray(b.lines)]), list(a.texts) + list(b.texts),
                       font_size=max(a.font_size, b.font_size), angle=a.angle, prob=min(a.prob, b.prob),
                       fg_color=a.fg_colors, bg_color=a.bg_colors)

    def absorb(outer, inner):
        # Lines in reading order: "LOOKS / LIKE / IORI..." (Grand Blue p25), not "LOOKS IORI ... LIKE".
        pairs = list(zip(np.asarray(outer.lines), outer.texts)) + list(zip(np.asarray(inner.lines), inner.texts))
        pairs.sort(key=lambda p: float(np.asarray(p[0], float)[:, 1].mean()))
        return type(outer)(np.stack([p[0] for p in pairs]), [p[1] for p in pairs],
                           font_size=max(outer.font_size, inner.font_size), angle=outer.angle,
                           prob=min(outer.prob, inner.prob), fg_color=outer.fg_colors, bg_color=outer.bg_colors)

    if image is None or not all(hasattr(r, "xyxy") and hasattr(r, "lines") for r in regions):
        return regions
    horizontal = [r for r in regions if getattr(r, "horizontal", True)]
    others = [r for r in regions if not getattr(r, "horizontal", True)]
    def columns(region):
        # Two speeches side by side that the merge read as one, line by line interleaved.
        boxes = [_box(q) for q in np.asarray(region.lines)]
        groups = column_groups(boxes)
        gaps = [min(boxes[i][0] for i in b) - max(boxes[i][2] for i in a) for a, b in zip(groups, groups[1:])]
        paragraphs = False
        if (len(groups) < 2 or min(gaps) <= 0) and text_mask is not None and len(region.texts) == len(boxes):
            groups, paragraphs = block_groups(np.asarray(text_mask), boxes), True
            groups = sorted(groups, key=lambda g: min(boxes[i][0] for i in g))
            gaps = [1] * (len(groups) - 1) or [0]
        if len(groups) < 2 or min(gaps) <= 0 or max(len(g) for g in groups) < 2 or len(region.texts) != len(boxes):
            return [region]
        lines, texts = np.asarray(region.lines), list(region.texts)
        parts = [type(region)(lines[g], [texts[i] for i in g], font_size=region.font_size, angle=region.angle,
                              prob=region.prob, fg_color=region.fg_colors, bg_color=region.bg_colors)
                 for g in (sorted(g, key=lambda i: boxes[i][1]) for g in groups)]
        if paragraphs:
            for k, part in enumerate(parts):
                part.mangalate_block = (id(region), k)
        return parts

    try:
        split = [part for region in horizontal for part in columns(region)]
        if len(split) > len(horizontal):
            print(f"Region split: {len(split) - len(horizontal)} column(s) separated", flush=True)
        horizontal = split
        before = len(horizontal)
        horizontal = absorb_contained(horizontal, absorb, inside)
        if len(horizontal) < before:
            print(f"Region join: {before - len(horizontal)} line(s) inside another speech joined", flush=True)
        joined = join_blocks(horizontal, make, inside)
    except Exception as exc:  # never lose a page over this
        print(f"Region join skipped: {type(exc).__name__}", flush=True)
        return regions
    if len(joined) < len(horizontal):
        print(f"Region join: {len(horizontal) - len(joined)} split speech(es) joined", flush=True)
    return joined + others


def fix_ocr(regions):
    """OCR letter mix-ups ("TM LINEAMILIAR" -> "I'M UNFAMILIAR") fixed before translation."""
    from quality import fix_ocr_words
    keep = [g.get("source", "") for g in (page_context() or {}).get("glossary") or [] if isinstance(g, dict)]
    total = 0
    for region in regions:
        try:
            text, changed = fix_ocr_words(getattr(region, "text", ""), keep)
        except Exception as exc:  # never lose a page over this
            print(f"OCR fix skipped: {type(exc).__name__}", flush=True)
            return
        if changed:
            region.text = text
            total += changed
    if total:
        print(f"OCR fix: {total} word(s)", flush=True)


def scanned_sounds(regions, bubbles, rows=None):
    """Split off text found only by the bubble scan that does not read as a line of speech.

    The scan also catches a sound drawn in a closed shape ("GRAB", "REEE"); those
    stay as drawn.  Two or more rows of letters with a common word are speech even
    when the OCR kept one word (Grand Blue p23: "ASS- / HOLE..." read as "ASS").
    Returns (kept regions, regions left as art).
    """
    from quality import reads_as_speech
    if not bubbles:
        return regions, []
    rows = list(rows or [1] * len(bubbles))
    kept, drawn = [], []
    for region in regions:
        x0, y0, x1, y1 = (int(v) for v in region.xyxy)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        found = [k for k, b in enumerate(bubbles) if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]]
        text = getattr(region, "text", "")
        if found and not reads_as_speech(text, several_rows=rows[found[0]] >= 2):
            region.mangalate_background = {"kind": "efeito_sonoro"}
            drawn.append(region)
        else:
            kept.append(region)
    if drawn:
        print(f"Bubble scan: {len(drawn)} kept as art: {[getattr(r, 'text', '') for r in drawn]}", flush=True)
    return kept, drawn


def drop_duplicates(regions):
    """A second, worse reading of the same letters is dropped (quality.duplicate_regions)."""
    from quality import duplicate_regions
    try:
        boxes = [tuple(int(v) for v in r.xyxy) for r in regions]
        drop = duplicate_regions(boxes, [getattr(r, "text", "") for r in regions])
    except Exception as exc:  # never lose a page over this
        print(f"Duplicate check skipped: {type(exc).__name__}", flush=True)
        return regions
    if drop:
        print(f"Duplicate regions: {len(drop)} dropped at {[boxes[i] for i in sorted(drop)]}", flush=True)
    return [r for i, r in enumerate(regions) if i not in drop]


def classify_regions(original_merge):
    """Decide once, before translation, which blocks are cleaned and translated.

    A block on artwork is removed from the page's regions, so it is neither
    translated, masked nor rendered: the original stays intact and the block is
    reported for review instead of receiving Portuguese over English.
    """
    async def merge(self, config, ctx):
        import cv2
        import numpy as np
        from quality import classify_region
        regions = await original_merge(self, config, ctx)
        ctx.mangalate_preserved = []
        if regions:
            regions, context_only = on_page(regions, _PAGE_ROWS.get())
            if context_only:
                print(f"Region check: {len(context_only)} only in the neighbouring pages, skipped", flush=True)
            regions = join_split_blocks(regions, ctx.img_rgb, getattr(ctx, "mask_raw", None))
            regions = drop_duplicates(regions)
            regions, drawn = scanned_sounds(regions, getattr(ctx, "mangalate_scanned", []),
                                            getattr(ctx, "mangalate_scanned_rows", None))
            ctx.mangalate_preserved.extend(drawn)
        if not regions or not protect_art(config):
            fix_ocr(regions or [])
            return regions
        image, raw = ctx.img_rgb, ctx.mask_raw
        if raw is not None and raw.shape[:2] != image.shape[:2]:
            raw = cv2.resize(raw, (image.shape[1], image.shape[0]), interpolation=cv2.INTER_NEAREST)
        follow = credit_followers(regions)
        if credits_page(regions):
            # End-of-chapter credits: the logo, the platform seal and every name stay as drawn
            # (TBATE 240 p68: the logo read as "FTERTHEEND" became "After the end").
            follow |= {id(r) for r in regions}
        kept = []
        for region in regions:
            text = getattr(region, "text", "")
            if is_sound_effect(text) or is_credit(text) or id(region) in follow:
                if id(region) in follow and not is_sound_effect(text):
                    region.mangalate_background = {"kind": "creditos"}
                    ctx.mangalate_preserved.append(region)
                    continue
                region.mangalate_background = {"kind": "efeito_sonoro" if is_sound_effect(text) else "creditos"}
                ctx.mangalate_preserved.append(region)
                continue
            region.mangalate_background = classify_region(image, raw, region.lines)
            # Outlined lettering over the art is translated; only the letters and their outline are cleaned.
            if region.mangalate_background["kind"] == "contorno":
                from quality import outlined_area, outlined_colours
                if not outlined_area(image, region.lines).any():
                    # Nothing to clean: the translation would be written over the English.
                    region.mangalate_background["kind"] = "art"
                    ctx.mangalate_preserved.append(region)
                    continue
                fg, bg = outlined_colours(image, region.lines)
                region.fg_colors, region.bg_colors = np.array(fg), np.array(bg)
            # A speech written over the drawing, on a mostly light page (One Piece 1161 p5
            # "WELL, CONSIDERING..."), is translated too: only its letters are cleaned.
            if region.mangalate_background["kind"] == "art":
                try:
                    from quality import reads_as_speech, speech_on_paper
                    if reads_as_speech(text, len(region.lines) > 1) and speech_on_paper(image, raw, region.lines):
                        region.mangalate_background["kind"] = "tracos"
                        region.mangalate_background["fala"] = True
                except Exception as exc:  # the speech stays as drawn, as before
                    print(f"Speech on paper skipped: {type(exc).__name__}", flush=True)
            # Lettering on a white part of the drawing, crossed by its strokes: translated, and
            # only the letters are cleaned (quality.letters_area).
            if region.mangalate_background["kind"] == "tracos":
                from quality import letters_area
                if not letters_area(image, raw, region.lines).any():
                    region.mangalate_background["kind"] = "art"
                    ctx.mangalate_preserved.append(region)
                    continue
            if region.mangalate_background["kind"] in ("interior", "contorno", "tracos"):
                kept.append(region)
            else:
                ctx.mangalate_preserved.append(region)
        print(f"Region check: kept={len(kept)} preserved_original={len(ctx.mangalate_preserved)}", flush=True)
        fix_ocr(kept)
        return kept
    return merge


def detection_fallback(original_detect):
    """When CTD finds no text on a page, try the default detector once.

    CTD groups lines of one bubble better, but missed the serif lettering of
    burst bubbles (episode 65, pages 101/102) that the default detector finds.
    """
    async def detect(self, config, ctx):
        result = await original_detect(self, config, ctx)
        detector = getattr(config.detector.detector, "value", config.detector.detector)
        if (result and result[0]) or detector != "ctd":
            return result
        retry = config.model_copy(deep=True)
        retry.detector.detector = type(config.detector.detector)("default")
        retry.detector.detection_size = 1536
        second = await original_detect(self, retry, ctx)
        if second and second[0]:
            print(f"Detection fallback: ctd=0 default={len(second[0])}", flush=True)
            return second
        return result
    return detect


def repair_textlines(original_detect):
    """Give every lettered line of the detector mask its own box before OCR.

    Short tests (Grand Blue 87 pp. 3/7/9, TBATE 236 pp. 1/6): the pixel mask
    covered the line, but no line box did, so the line stayed in English.
    """
    async def detect(self, config, ctx):
        result = await original_detect(self, config, ctx)
        if not result or result[1] is None:
            return result
        textlines, mask_raw, mask = list(result[0] or []), result[1], result[2]
        import cv2
        import numpy as np
        from quality import repair_lines, _box
        from manga_translator.utils import Quadrilateral
        image = getattr(ctx, "img_rgb", None)
        if image is not None and np.asarray(mask_raw).shape[:2] != np.asarray(image).shape[:2]:
            return result
        horizontal = [i for i, line in enumerate(textlines) if getattr(line, "direction", "h") == "h"]
        boxes = [_box(textlines[i].pts) for i in horizontal]
        ctx.mangalate_detector_lines = [list(_box(line.pts)) for line in textlines]  # --diagnostics only
        # Letters inside a flat interior count even where the detector mask missed them.
        from quality import bubble_glyphs, NEAR_LINES
        seen = np.asarray(mask_raw) > 127
        if image is not None:
            for box in boxes:
                seen = seen | bubble_glyphs(np.asarray(image), box, box[3] - box[1], near=NEAR_LINES)
        gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY) if image is not None else None
        repaired, changes = repair_lines(seen.astype(np.uint8) * 255, boxes, gray)
        ctx.mangalate_line_repairs = [{"tipo": kind, "antes": before, "depois": after} for kind, before, after in changes]
        # One box across two columns of text in the same bubble is cut at the gutter.
        if image is not None:
            from quality import column_cuts
            try:
                gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
                cuts = column_cuts(gray, [box for box, _ in repaired])
            except Exception as exc:  # never lose a page over this
                print(f"Column check skipped: {type(exc).__name__}", flush=True)
                cuts = {}
            for i in sorted(cuts, reverse=True):
                (x0, y0, x1, y1), source = repaired[i]
                gx0, gx1 = cuts[i]
                parts = [(x0, y0, gx0, y1), (gx1, y0, x1, y1)]
                repaired[i:i + 1] = [(part, source) for part in parts]
                changes.append(("column", (x0, y0, x1, y1), parts))
            # One box across two paragraphs side by side (a bubble and the text on the page beside it).
            from quality import block_cuts
            try:
                cuts = block_cuts(np.asarray(mask_raw), [box for box, _ in repaired])
            except Exception as exc:  # never lose a page over this
                print(f"Block check skipped: {type(exc).__name__}", flush=True)
                cuts = {}
            for i in sorted(cuts, reverse=True):
                (x0, y0, x1, y1), source = repaired[i]
                parts = [(a, y0, b, y1) for a, b in cuts[i]]
                repaired[i:i + 1] = [(part, source) for part in parts]
                changes.append(("column", (x0, y0, x1, y1), parts))
        # Small white bubbles the detector did not see at all.
        scanned = []
        if image is not None:
            from quality import bubble_text_lines
            try:
                scanned = bubble_text_lines(np.asarray(image), [_box(line.pts) for line in textlines])
            except Exception as exc:  # never lose a page over this
                print(f"Bubble scan skipped: {type(exc).__name__}", flush=True)
        ctx.mangalate_scanned = [bubble for bubble, _, _ in scanned]
        ctx.mangalate_scanned_rows = [len(rows) for _, rows, _ in scanned]
        if scanned:
            mask_raw = np.asarray(mask_raw).copy()
            for bubble, rows, letters in scanned:
                mask_raw[cv2.dilate(letters.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0] = 255
                for x0, y0, x1, y1 in rows:
                    if x1 - x0 < y1 - y0:  # a one-letter row ("I") stays a horizontal line
                        pad = (y1 - y0 - (x1 - x0)) // 2 + 1
                        x0, x1 = max(bubble[0], x0 - pad), min(bubble[2], x1 + pad)
                    changes.append(("bubble", None, (x0, y0, x1, y1)))
                    repaired.append(((x0, y0, x1, y1), None))
            print(f"Bubble scan: {len(scanned)} bubble(s) at {ctx.mangalate_scanned}", flush=True)
        if not changes:
            return result
        lines = [line for i, line in enumerate(textlines) if i not in set(horizontal)]
        for box, source in repaired:
            original = textlines[horizontal[source]] if source is not None else None
            if original is not None and box == boxes[source]:
                lines.append(original)
                continue
            x0, y0, x1, y1 = box
            pts = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.int64)
            lines.append(Quadrilateral(pts, "", original.prob if original is not None else 1.0))
        split = sum(1 for kind, _, _ in changes if kind == "split")
        scan = sum(1 for kind, _, _ in changes if kind == "bubble")
        column = sum(1 for kind, _, _ in changes if kind == "column")
        fit = sum(1 for kind, _, _ in changes if kind in ("fit", "refit"))
        print(f"Line repair: split={split} added={len(changes) - split - scan - column - fit} scanned={scan} "
              f"column_cuts={column} fitted={fit}", flush=True)
        return (lines, mask_raw, mask) + tuple(result[3:])
    return detect


def _line_size(region):
    """Height of a region's lines; for letters stacked one per row, the width of the column."""
    import numpy as np
    from quality import stacked
    lines = [np.asarray(l, float).reshape(4, 2) for l in region.lines]
    if not lines:
        return float(region.font_size)
    if stacked(lines):
        return float(np.median([np.ptp(l[:, 0]) for l in lines]))
    return float(np.median([np.linalg.norm(l[3] - l[0]) for l in lines]))


def bubble_layout(rendering, text_render):
    """Replace the engine's 'fit to the original text box' with 'fit to the bubble'.

    See lettering.py.  Regions without a usable bubble keep the engine's own
    sizing and drawing.
    """
    import numpy as np
    import lettering
    from quality import has_cjk, stacked
    original_resize = rendering.resize_regions_to_font_size
    original_render = rendering.render

    def horizontal(region):
        direction = getattr(region, "_direction", None) or region.direction
        return direction in ("horizontal", "h") or (direction == "auto" and region.horizontal)

    def line_height(region):
        heights = [float(np.linalg.norm(np.asarray(l[3]) - np.asarray(l[0]))) for l in region.lines]
        return float(np.median(heights)) if heights else float(region.font_size)

    def resize(img, text_regions, font_size_fixed, font_size_offset, font_size_minimum):
        points = original_resize(img, text_regions, font_size_fixed, font_size_offset, font_size_minimum)
        if font_size_fixed is not None:
            return points
        minimum = font_size_minimum if font_size_minimum and font_size_minimum > 0 else round((img.shape[0] + img.shape[1]) / 200)
        boxes = [tuple(int(v) for v in r.xyxy) for r in text_regions]
        planned = 0
        for i, region in enumerate(text_regions):
            region.mangalate_plan = None
            region.mangalate_shaped = None
            text = region.get_translation_for_rendering()
            if text and not has_cjk(text) and stacked(region.lines):
                # Letters stacked one per row in a tall bubble ("GUYS!"): the translation too.
                try:
                    plan = lettering.plan_stacked(boxes[i], text, lettering.font_file(), max(8, round(minimum * 0.6)))
                except Exception as exc:  # never lose a page over the nicer layout
                    print(f"Stacked layout skipped: {type(exc).__name__}", flush=True)
                    plan = None
                if plan is not None:
                    region.mangalate_shaped = plan
                    region.font_size = plan["size"]
                    x0, y0, x1, y1 = plan["box"]
                    points[i] = np.array([[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]], dtype=np.int64)
                    planned += 1
                    continue
            if not text or not horizontal(region) or has_cjk(text):
                continue
            def layout(size, width, height, text=text, lang=region.target_lang):
                return text_render.calc_horizontal(size, text, width, height, lang, False)
            others = boxes[:i] + boxes[i + 1:]
            page = img
            if (getattr(region, "mangalate_background", None) or {}).get("kind") == "tracos":
                # Strokes of the drawing still cross where the letters were: plan as if the
                # block were paper (quality.paper_under), so the text keeps its room.
                try:
                    import cv2
                    from quality import paper_under
                    _, colour = paper_under(img, region.lines, line_height(region))
                    hull = cv2.convexHull(np.concatenate([np.asarray(l, np.int32).reshape(-1, 2) for l in region.lines]))
                    page = img.copy()
                    cv2.fillPoly(page, [hull.reshape(-1, 1, 2)], tuple(int(c) for c in colour))
                except Exception as exc:  # plan on the page as it is
                    print(f"Stroke room skipped: {type(exc).__name__}", flush=True)
                    page = img
            try:
                shaped = lettering.plan_shaped(page, boxes[i], others, text, lettering.font_file(),
                                               line_height(region), max(8, round(minimum * 0.6)),
                                               offset=font_size_offset or 0)
            except Exception as exc:  # never lose a page over the nicer layout
                print(f"Shaped layout skipped: {type(exc).__name__}", flush=True)
                shaped = None
            if shaped is not None:
                region.mangalate_shaped = shaped
                region.font_size = shaped["size"]
                x0, y0, x1, y1 = shaped["box"]
                points[i] = np.array([[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]], dtype=np.int64)
                planned += 1
                continue
            try:
                plan = lettering.plan(page, boxes[i], others, text, layout,
                                      line_height(region) + 0, max(8, round(minimum * 0.6)),
                                      offset=font_size_offset or 0)
            except Exception as exc:  # never lose a page over the nicer layout
                print(f"Bubble layout skipped: {type(exc).__name__}", flush=True)
                plan = None
            if plan is None:
                continue
            size, (x0, y0, x1, y1) = plan
            region.mangalate_plan = plan
            region.font_size = size
            points[i] = np.array([[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]], dtype=np.int64)
            planned += 1
        print(f"Bubble layout: {planned} of {len(text_regions)} regions fitted to the bubble", flush=True)
        return points

    def render(img, region, dst_points, hyphenate, line_spacing, disable_font_border):
        shaped = getattr(region, "mangalate_shaped", None)
        if shaped is not None:
            fg, bg = rendering.fg_bg_compare(*region.get_font_colors())
            return lettering.draw_shaped(img, shaped, fg, None if disable_font_border else bg)
        plan = getattr(region, "mangalate_plan", None)
        if plan is None:
            return original_render(img, region, dst_points, hyphenate, line_spacing, disable_font_border)
        import cv2
        size, (x0, y0, x1, y1) = plan
        fg, bg = rendering.fg_bg_compare(*region.get_font_colors())
        if disable_font_border:
            bg = None
        box = text_render.put_text_horizontal(size, region.get_translation_for_rendering(), x1 - x0, y1 - y0,
                                              "center", False, fg, bg, region.target_lang, False,
                                              lettering.LINE_SPACING)
        if box is None:
            return img
        h, w = box.shape[:2]
        scale = min(1.0, (x1 - x0) / w, (y1 - y0) / h)
        if scale < 1.0:
            box = cv2.resize(box, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
            h, w = box.shape[:2]
        left = (x0 + x1) // 2 - w // 2
        top = (y0 + y1) // 2 - h // 2
        H, W = img.shape[:2]
        cx0, cy0, cx1, cy1 = max(0, left), max(0, top), min(W, left + w), min(H, top + h)
        if cx1 <= cx0 or cy1 <= cy0:
            return img
        part = box[cy0 - top:cy1 - top, cx0 - left:cx1 - left]
        alpha = part[:, :, 3:4].astype(np.float32) / 255.0
        target = img[cy0:cy1, cx0:cx1].astype(np.float32)
        img[cy0:cy1, cx0:cx1] = np.clip(target * (1 - alpha) + part[:, :, :3].astype(np.float32) * alpha, 0, 255).astype(np.uint8)
        return img

    rendering.resize_regions_to_font_size = resize
    rendering.render = render


def keep_clean_copy(original_render):
    """The renderer draws into ctx.img_inpainted; keep the cleaned page for diagnostics."""
    async def render(self, config, ctx):
        image = getattr(ctx, "img_inpainted", None)
        ctx.mangalate_clean = image.copy() if image is not None else None
        lines = []
        try:  # a panel border the cleaning cut where it crossed the text is drawn back after the lettering
            import numpy as np
            from quality import through_lines
            for region in ctx.text_regions or []:
                lines += through_lines(ctx.img_rgb, ctx.mask, region.xyxy, _line_size(region))
        except Exception as exc:  # never lose a page over this
            print(f"Line redraw skipped: {type(exc).__name__}", flush=True)
            lines = []
        result = await original_render(self, config, ctx)
        if lines and ctx.mangalate_clean is not None:
            try:
                from quality import redraw_lines
                result = redraw_lines(result, ctx.mangalate_clean, ctx.mask, lines)
                print(f"Line redraw: {len(lines)} line(s) through the text drawn back", flush=True)
            except Exception as exc:  # never lose a page over this
                print(f"Line redraw skipped: {type(exc).__name__}", flush=True)
        return result
    return render


RESCUE_PROB = 0.02


def rescue_ocr(original_ocr):
    """Read again, with a lower threshold, lines the OCR dropped inside a paragraph.

    The 48px OCR drops lines read with confidence below 0.2.  TBATE 236 p6: the
    bold italic "MUST'VE MAL-" had a box and was covered by the mask, but was
    dropped here and stayed in English between two translated lines.  The AI
    fixes small OCR mistakes, so a doubtful reading beats an untouched line.
    """
    async def ocr(self, config, ctx):
        before = list(ctx.textlines or [])
        ctx.mangalate_drawn = []
        result = await original_ocr(self, config, ctx)
        kept = {id(line) for line in result}
        lost = [line for line in before if id(line) not in kept and getattr(line, "direction", "h") == "h"]
        from quality import _box
        # --diagnostics only: what the OCR read on each line, and the lines it dropped.
        ctx.mangalate_ocr_lines = [{"caixa": list(_box(l.pts)), "texto": str(getattr(l, "text", "")),
                                    "prob": round(float(getattr(l, "prob", 0) or 0), 3)} for l in result]
        ctx.mangalate_ocr_lost = [list(_box(l.pts)) for l in lost]
        if not lost:
            return result
        from quality import near_lines
        candidates = [lost[i] for i in near_lines([_box(l.pts) for l in lost],
                                                   [_box(l.pts) for l in result if getattr(l, "direction", "h") == "h"])]
        if not candidates:
            return result
        from manga_translator.ocr import dispatch as dispatch_ocr
        retry = config.ocr.model_copy(deep=True) if hasattr(config.ocr, "model_copy") else config.ocr
        retry.prob = RESCUE_PROB
        read = await dispatch_ocr(config.ocr.ocr, ctx.img_rgb, candidates, retry, self.device, self.verbose)
        # A drawing the detector took for a line (an anger vein, One Piece 1161 p16) comes back
        # as one consonant repeated, "JJJJ": real speech has two different letters or a vowel.
        # A drawn-out vowel ("AAA!!!", the end of a cry split in two lines) is still speech.
        def letters(line):
            return [ch.upper() for ch in str(line.text) if ch.isalpha()]
        def drawing(line):
            found = set(letters(line))
            return len(found) == 1 and not found & set("AEIOUY")
        rescued = [line for line in read if len(letters(line)) >= 2 and not drawing(line)]
        # Kept out of the cleaning mask by refine_mask_consistently.
        ctx.mangalate_drawn = [list(_box(l.pts)) for l in read if len(letters(l)) >= 2 and drawing(l)]
        render = getattr(config, "render", None)
        for line in rescued:
            if getattr(render, "font_color_fg", None):
                line.fg_r, line.fg_g, line.fg_b = render.font_color_fg
            if getattr(render, "font_color_bg", None):
                line.bg_r, line.bg_g, line.bg_b = render.font_color_bg
        ctx.mangalate_ocr_rescued = [{"caixa": list(_box(l.pts)), "prob": round(float(l.prob), 3)} for l in rescued]
        if rescued:
            print(f"OCR rescue: {len(rescued)} of {len(lost)} dropped lines read again", flush=True)
        return list(result) + rescued
    return ocr


async def refine_mask_consistently(self, config, ctx):
    """Mask every kept region; the art decision was already taken in classify_regions.

    The engine would otherwise re-run its colour test here and silently drop
    the mask of blocks that are still translated and rendered.
    """
    import cv2
    import numpy as np
    from manga_translator.mask_refinement import dispatch
    from quality import glyphs_to_clean
    mask = await dispatch(ctx.text_regions, ctx.img_rgb, ctx.mask_raw, "fit_text",
                          config.mask_dilation_offset, 0, self.verbose, self.kernel_size)
    # Pieces of letters the detector mask missed (italic overhangs, the last dots of
    # "...") would stay on the page as stray marks: add the letters of the text inside
    # the bubble interior (quality.glyphs_to_clean).
    h, w = mask.shape[:2]
    grown = np.zeros((h, w), bool)
    for region in ctx.text_regions or []:
        grown |= glyphs_to_clean(ctx.img_rgb, region.xyxy, _line_size(region))
    if grown.any():
        mask = mask.copy()
        mask[grown] = 255
    # A drawing the OCR read as "JJJJ" (quality.drawn_marks) stays whole.
    drawn = getattr(ctx, "mangalate_drawn", None)
    if drawn:
        try:
            from quality import drawn_marks
            keep = drawn_marks(ctx.img_rgb, drawn)
            if keep.any():
                mask = mask.copy()
                mask[keep] = 0
        except Exception as exc:  # never lose a page over this
            print(f"Drawn marks skipped: {type(exc).__name__}", flush=True)
    # Outlined lettering over the art, or lettering crossed by strokes of the drawing: the
    # cleaning stays on the letters (and their outline).
    from quality import letters_area, outlined_area
    for region in ctx.text_regions or []:
        kind = (getattr(region, "mangalate_background", None) or {}).get("kind")
        if kind not in ("contorno", "tracos"):
            continue
        x0, y0, x1, y1 = (int(v) for v in region.xyxy)
        pad = int(max(8, region.font_size))
        x0, y0, x1, y1 = max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad)
        if kind == "contorno":
            allowed = outlined_area(ctx.img_rgb, region.lines)
        else:
            try:
                raw = ctx.mask_raw
                if raw.shape[:2] != (h, w):
                    raw = cv2.resize(raw, (w, h), interpolation=cv2.INTER_NEAREST)
                allowed = letters_area(ctx.img_rgb, raw, region.lines)
            except Exception as exc:  # cleaned like a bubble, as before: never lose the speech
                print(f"Letters-only cleaning skipped: {type(exc).__name__}", flush=True)
                continue
        for other in ctx.text_regions:  # the cleaning of a bubble next to it stays
            if other is not region:
                ox0, oy0, ox1, oy1 = (int(v) for v in other.xyxy)
                allowed[max(0, oy0):oy1, max(0, ox0):ox1] = True
        mask = mask.copy()
        mask[y0:y1, x0:x1][~allowed[y0:y1, x0:x1]] = 0
    return mask


def validate_page_translations(original_translate):
    async def translate(self, config, ctx):
        regions = list(ctx.text_regions or [])
        result = await original_translate(self, config, ctx)
        if not legacy_quality() and isinstance(result, list):
            import re
            from quality import (normalize_spacing, page_names, same_text, sentence_case, source_names, tidy_start,
                                 unchanged_english)
            texts = [getattr(region, "translation", None) for region in result]
            names = page_names([t for t in texts if isinstance(t, str)])
            names |= {g["target"] for g in (page_context() or {}).get("glossary", [])}
            # The engine drops an answer equal to its source, and the English lettering stays
            # (op1161 p16 "AH.."). What reads the same in Portuguese is lettered like the rest;
            # an English echo stays as drawn and is reported with the preserved regions.
            kept = {id(region) for region in result}
            same = [region for region in regions if id(region) not in kept
                    and isinstance(getattr(region, "translation", None), str)
                    and same_text(region.text, region.translation) and re.search(r"[^\W\d_]", region.text)]
            back = {id(region) for region in same if not unchanged_english(region.text, names)}
            for region in same:
                if id(region) in back:
                    region.mangalate_same_as_source = True  # memory.remember learns no name from it
            if same:
                if kept <= {id(region) for region in regions}:  # same order as before: the early cleaning stays
                    result = [region for region in regions if id(region) in kept or id(region) in back]
                else:
                    result = result + [region for region in same if id(region) in back]
                for region in same:
                    if id(region) not in back:
                        region.mangalate_background = dict(getattr(region, "mangalate_background", None) or {},
                                                           devolvida_igual=True)
                        ctx.mangalate_preserved = list(getattr(ctx, "mangalate_preserved", None) or []) + [region]
                print(f"Same as the original: {len(back)} lettered, {len(same) - len(back)} left as drawn", flush=True)
            for region in result:
                if isinstance(getattr(region, "translation", None), str):
                    # The (m)/(f) marks belong to the terms line only (memory.TERMS_INSTRUCTION);
                    # Grand Blue p42 got "Bob (m)" written on the page.
                    region.translation = re.sub(r"\s*\((?:m|f)\)(?!\w)", "", region.translation)
                    # Model control tokens that leaked into the answer (Grand Blue p22: "Kouhei: 5 pts. <|10|").
                    region.translation = re.sub(r"\s*<\|[^<>|]{0,20}(?:\|>?|>|$)", "", region.translation)
                    own = names | source_names(getattr(region, "text", ""), region.translation)
                    fixed = sentence_case(region.translation, own)
                    fixed = tidy_start(fixed, getattr(region, "text", ""), own)
                    region.translation = normalize_spacing(fixed)
        blank = sum(not getattr(region, "translation", "").strip() for region in regions)
        unchanged = sum(getattr(region, "translation", "").strip().lower() == region.text.strip().lower()
                        for region in regions)
        print(f"Page translation: input_regions={len(regions)} output_regions={len(result)} blank={blank} unchanged={unchanged}",
              flush=True)
        if regions and not result and blank:
            raise ValueError("Page contains recognized text but no usable translations")
        return result
    return translate


class PanelCV:
    """Normalize OpenCV 4/5 geometry only inside the legacy panel finder."""
    def __init__(self, cv):
        self.cv = cv

    def __getattr__(self, name):
        return getattr(self.cv, name)

    def findContours(self, *args, **kwargs):
        import numpy as np
        parts = list(self.cv.findContours(*args, **kwargs))
        parts[-2] = [np.asarray(contour).reshape(-1, 1, 2) for contour in parts[-2]]
        return tuple(parts)

    def approxPolyDP(self, *args, **kwargs):
        return self.cv.approxPolyDP(*args, **kwargs).reshape(-1, 1, 2)

    def convexHull(self, *args, **kwargs):
        return self.cv.convexHull(*args, **kwargs).reshape(-1, 1, 2)

    def createLineSegmentDetector(self, *args, **kwargs):
        from types import SimpleNamespace
        detector = self.cv.createLineSegmentDetector(*args, **kwargs)
        def detect(*detect_args, **detect_kwargs):
            parts = list(detector.detect(*detect_args, **detect_kwargs))
            if parts[0] is not None:
                parts[0] = parts[0].reshape(-1, 1, 4)
            return tuple(parts)
        return SimpleNamespace(detect=detect)


def find_panels(img_rgb, rtl=True):
    import cv2
    from tempfile import TemporaryDirectory
    from pathlib import Path
    from manga_translator.utils.panel.kumikolib import Kumiko
    # Always remove the intermediate page, even if the panel finder fails.
    with TemporaryDirectory(prefix="mangalate-panel-") as folder:
        path = str(Path(folder) / "page.png")
        if not cv2.imwrite(path, img_rgb):
            raise ValueError("Panel image could not be written")
        finder = Kumiko({"rtl": rtl})
        finder.parse_image(path)
        infos = finder.get_infos()
        return infos[0]["panels"] if infos else []


def apply_compatibility():
    from manga_translator import MangaTranslator
    from manga_translator.translators.nllb import NLLBTranslator, ISO_639_1_TO_FLORES_200
    from manga_translator.translators.custom_openai import CustomOpenAiTranslator
    ISO_639_1_TO_FLORES_200.pop("kn", None)  # Kannada is not Korean.
    ISO_639_1_TO_FLORES_200["ko"] = "kor_Hang"
    NLLBTranslator._translate_batch = translate_nllb_batch
    NLLBTranslator._load = load_nllb
    NLLBTranslator._infer = infer_nllb
    NLLBTranslator._LANGUAGE_CODE_MAP["POL"] = "pol_Latn"
    import cv2
    import importlib
    cv = PanelCV(cv2)
    for name in ("page", "panel", "debug"):
        module = importlib.import_module("manga_translator.utils.panel.lib." + name)
        module.cv = cv
    from manga_translator.utils import panel, sort
    panel.get_panels_from_array = find_panels
    sort.get_panels_from_array = find_panels
    if not getattr(CustomOpenAiTranslator, "_mangalate_compat_applied", False):
        CustomOpenAiTranslator._request_translation = request_byok_translation
        CustomOpenAiTranslator._translate = validate_byok_results(translate_byok)
        CustomOpenAiTranslator._mangalate_compat_applied = True
    if not getattr(MangaTranslator, "_mangalate_compat_applied", False):
        MangaTranslator._run_text_translation = validate_page_translations(MangaTranslator._run_text_translation)
        if not legacy_quality():
            MangaTranslator._run_textline_merge = classify_regions(MangaTranslator._run_textline_merge)
            MangaTranslator._run_mask_refinement = refine_mask_consistently
            MangaTranslator._run_ocr = rescue_ocr(MangaTranslator._run_ocr)
            MangaTranslator._run_text_rendering = keep_clean_copy(MangaTranslator._run_text_rendering)
            MangaTranslator._run_detection = repair_textlines(detection_fallback(MangaTranslator._run_detection))
            from manga_translator.rendering import text_render
            from quality import compact_symbols, whole_word_breaker
            text_render.compact_special_symbols = compact_symbols(text_render.compact_special_symbols)
            text_render.calc_horizontal = whole_word_breaker(text_render.calc_horizontal,
                                                             text_render.get_string_width)
            if os.environ.get("MANGALATE_BUBBLE_LAYOUT", "true").lower() != "false":
                import manga_translator.rendering as rendering
                bubble_layout(rendering, text_render)
        from speed import install
        install(MangaTranslator)
        MangaTranslator._mangalate_compat_applied = True
