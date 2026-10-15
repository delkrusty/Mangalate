# SPDX-License-Identifier: GPL-3.0-only
"""Mangalate adaptations of the separately executed GPL engine, 2026-10-13.

Based on NLLBTranslator at:
https://github.com/zyddnys/manga-image-translator/blob/d6de6ab62a7be6afc0d07a3184149cdefbcd32f2/manga_translator/translators/nllb.py
Retains GPL-3.0 licensing. No warranty; upstream LICENSE is in the Docker source tree.
"""


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


def parse_marked(content, count):
    import re
    markers = list(re.finditer(r"<\|(\d+)\|>", content))
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


async def request_byok_translation(self, to_lang, prompt, client=None, model=None):
    messages = [{"role": "system", "content": self.chat_system_template.format(to_lang=to_lang)}]
    sample = self.get_chat_sample(to_lang)
    if sample:
        messages.extend([{"role": "user", "content": sample[0]},
                         {"role": "assistant", "content": sample[1]}])
    messages.append({"role": "user", "content": prompt})
    model = model or self.model
    if not model:
        from manga_translator.translators.keys import CUSTOM_OPENAI_MODEL
        model = CUSTOM_OPENAI_MODEL
    response = await (client or self.client).chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=self._MAX_TOKENS,
        temperature=self.temperature,
        top_p=self.top_p,
    )
    if not response.choices:
        raise ValueError("BYOK returned no choices")
    choice = response.choices[0]
    content = choice.message.content
    if not isinstance(content, str) or not content.strip():
        raise ValueError("BYOK returned empty content")
    if choice.finish_reason == "length":
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
    pool = provider_pool()
    for prompt, count in self._assemble_prompts(from_lang, to_lang, queries):
        if pool:
            async def attempt(provider, prompt=prompt, count=count):
                content = await asyncio.wait_for(
                    self._request_translation(to_lang, prompt, provider_client(pool, provider), provider["model"]),
                    timeout=180)
                extracted = (self.extract_capture_groups(content, rf"{self.rgx_capture}") or "").strip()
                try:
                    return parse_marked(extracted, count)
                except ValueError:
                    # Kept in memory for the local --diagnostics report only; never logged.
                    pool.__dict__.setdefault("raw", []).append((provider["name"], count, prompt, content))
                    raise
            translations += await pool.run(attempt)
            continue
        content = await asyncio.wait_for(self._request_translation(to_lang, prompt), timeout=180)
        translations += parse_marked(self.extract_capture_groups(content, rf"{self.rgx_capture}").strip(), count)
    return translations


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


def classify_regions(original_merge):
    """Decide once, before translation, which blocks are cleaned and translated.

    A block on artwork is removed from the page's regions, so it is neither
    translated, masked nor rendered: the original stays intact and the block is
    reported for review instead of receiving Portuguese over English.
    """
    async def merge(self, config, ctx):
        import cv2
        from quality import classify_region
        regions = await original_merge(self, config, ctx)
        ctx.mangalate_preserved = []
        if not regions or not protect_art(config):
            return regions
        image, raw = ctx.img_rgb, ctx.mask_raw
        if raw is not None and raw.shape[:2] != image.shape[:2]:
            raw = cv2.resize(raw, (image.shape[1], image.shape[0]), interpolation=cv2.INTER_NEAREST)
        kept = []
        for region in regions:
            region.mangalate_background = classify_region(image, raw, region.lines)
            if region.mangalate_background["kind"] == "interior":
                kept.append(region)
            else:
                ctx.mangalate_preserved.append(region)
        print(f"Region check: kept={len(kept)} preserved_original={len(ctx.mangalate_preserved)}", flush=True)
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
        if not result or not result[0] or result[1] is None:
            return result
        textlines, mask_raw, mask = result[0], result[1], result[2]
        import numpy as np
        from quality import repair_lines, _box
        from manga_translator.utils import Quadrilateral
        image = getattr(ctx, "img_rgb", None)
        if image is not None and np.asarray(mask_raw).shape[:2] != np.asarray(image).shape[:2]:
            return result
        horizontal = [i for i, line in enumerate(textlines) if getattr(line, "direction", "h") == "h"]
        boxes = [_box(textlines[i].pts) for i in horizontal]
        repaired, changes = repair_lines(mask_raw, boxes)
        ctx.mangalate_line_repairs = [{"tipo": kind, "antes": before, "depois": after} for kind, before, after in changes]
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
        print(f"Line repair: split={split} added={len(changes) - split}", flush=True)
        return (lines, mask_raw, mask) + tuple(result[3:])
    return detect


async def refine_mask_consistently(self, config, ctx):
    """Mask every kept region; the art decision was already taken in classify_regions.

    The engine would otherwise re-run its colour test here and silently drop
    the mask of blocks that are still translated and rendered.
    """
    from manga_translator.mask_refinement import dispatch
    return await dispatch(ctx.text_regions, ctx.img_rgb, ctx.mask_raw, "fit_text",
                          config.mask_dilation_offset, 0, self.verbose, self.kernel_size)


def validate_page_translations(original_translate):
    async def translate(self, config, ctx):
        regions = list(ctx.text_regions or [])
        result = await original_translate(self, config, ctx)
        if not legacy_quality() and isinstance(result, list):
            from quality import normalize_spacing
            for region in result:
                if isinstance(getattr(region, "translation", None), str):
                    region.translation = normalize_spacing(region.translation)
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
            MangaTranslator._run_detection = repair_textlines(detection_fallback(MangaTranslator._run_detection))
            from manga_translator.rendering import text_render
            from quality import compact_symbols, whole_word_breaker
            text_render.compact_special_symbols = compact_symbols(text_render.compact_special_symbols)
            text_render.calc_horizontal = whole_word_breaker(text_render.calc_horizontal,
                                                             text_render.get_string_width)
        MangaTranslator._mangalate_compat_applied = True
