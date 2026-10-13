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


async def request_byok_translation(self, to_lang, prompt):
    messages = [{"role": "system", "content": self.chat_system_template.format(to_lang=to_lang)}]
    sample = self.get_chat_sample(to_lang)
    if sample:
        messages.extend([{"role": "user", "content": sample[0]},
                         {"role": "assistant", "content": sample[1]}])
    messages.append({"role": "user", "content": prompt})
    model = self.model
    if not model:
        from manga_translator.translators.keys import CUSTOM_OPENAI_MODEL
        model = CUSTOM_OPENAI_MODEL
    response = await self.client.chat.completions.create(
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
    if not isinstance(content, str) or not content.strip() or choice.finish_reason == "length":
        raise ValueError("BYOK returned incomplete content")
    usage = response.usage
    self.token_count_last = (getattr(usage, "total_tokens", 0) or 0) if usage else 0
    self.token_count += self.token_count_last
    return content


async def translate_byok(self, from_lang, to_lang, queries):
    import asyncio
    import re
    translations = []
    # Avoid the upstream loop which restarts still-running paid requests.
    self.client.max_retries = 0
    for prompt, count in self._assemble_prompts(from_lang, to_lang, queries):
        content = await asyncio.wait_for(self._request_translation(to_lang, prompt), timeout=180)
        content = self.extract_capture_groups(content, rf"{self.rgx_capture}").strip()
        markers = list(re.finditer(r"<\|(\d+)\|>", content))
        if not markers and count == 1 and content:
            translations.append(content)
            continue
        if [int(marker.group(1)) for marker in markers] != list(range(1, count + 1)):
            raise ValueError("BYOK returned missing, duplicate or reordered markers")
        if content[:markers[0].start()].strip():
            raise ValueError("BYOK returned extra content before translations")
        for index, marker in enumerate(markers):
            end = markers[index + 1].start() if index + 1 < len(markers) else len(content)
            text = content[marker.end():end].strip()
            if not text:
                raise ValueError("BYOK returned an empty bubble")
            translations.append(text)
    return translations


def validate_byok_results(original_translate):
    async def translate(self, from_lang, to_lang, queries):
        result = await original_translate(self, from_lang, to_lang, queries)
        if len(result) != len(queries) or any(not isinstance(text, str) or not text.strip() for text in result):
            raise ValueError("BYOK returned incomplete translations")
        return result
    return translate


def validate_page_translations(original_translate):
    async def translate(self, config, ctx):
        regions = list(ctx.text_regions or [])
        result = await original_translate(self, config, ctx)
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
        MangaTranslator._mangalate_compat_applied = True
