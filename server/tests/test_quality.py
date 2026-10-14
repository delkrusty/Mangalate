"""Regression tests for cleanup classification and Portuguese line breaking.

Only numpy/OpenCV are needed; all images are synthetic.
"""
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from quality import (broken_words, classify_region, compact_symbols, normalize_spacing,
                     whole_word_breaker)

RNG = np.random.default_rng(65)


def page(fill=(255, 255, 255), size=(400, 300)):
    return np.full((size[1], size[0], 3), fill, np.uint8)


def write(image, text, origin, colour, scale=0.9):
    cv2.putText(image, text, origin, cv2.FONT_HERSHEY_SIMPLEX, scale, colour, 2, cv2.LINE_AA)
    return image


def text_mask(image, background):
    diff = np.abs(image.astype(int) - np.asarray(background, int)).sum(axis=2)
    return (diff > 90).astype(np.uint8) * 255


def bubble(image, centre, axes, fill, outline=(0, 0, 0)):
    cv2.ellipse(image, centre, axes, 0, 0, 360, fill, -1, cv2.LINE_AA)
    cv2.ellipse(image, centre, axes, 0, 0, 360, outline, 3, cv2.LINE_AA)
    return image


def quad(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def noisy_art(size=(400, 300)):
    art = RNG.integers(0, 255, (size[1] // 10, size[0] // 10, 3), dtype=np.uint8)
    return cv2.resize(art, size, interpolation=cv2.INTER_NEAREST)


class BackgroundTest(unittest.TestCase):
    def check(self, image, background, box, expected):
        mask = text_mask(image, background)
        verdict = classify_region(image, mask, [quad(*box)])
        self.assertEqual(verdict["kind"], expected, verdict)
        return verdict

    def test_white_bubble_black_text_is_cleaned(self):
        image = bubble(page((90, 140, 200)), (200, 150), (150, 80), (255, 255, 255))
        write(image, "WHAT IS GOING ON?", (90, 160), (0, 0, 0), 0.75)
        self.check(image, (255, 255, 255), (88, 138, 320, 166), "interior")

    def test_coloured_text_in_tinted_bubble_is_cleaned(self):
        # 0.5.2 dropped this mask because the block had >10 coloured pixels.
        image = bubble(page(), (200, 150), (150, 80), (238, 226, 205), (150, 100, 40))
        write(image, "AT TOMORROW'S", (100, 145), (150, 90, 40))
        write(image, "BALL.", (165, 180), (150, 90, 40))
        self.check(image, (238, 226, 205), (98, 122, 305, 186), "interior")

    def test_red_text_on_white_burst_is_cleaned(self):
        image = page((250, 200, 210))
        pts = np.array([[60, 60], [200, 30], [340, 60], [370, 150], [340, 240], [200, 270], [60, 240], [30, 150]])
        cv2.fillPoly(image, [pts], (255, 255, 255))
        cv2.polylines(image, [pts], True, (220, 60, 90), 3)
        write(image, "NO WAY!", (130, 130), (220, 60, 90))
        write(image, "ABSOLUTELY NOT!", (85, 170), (220, 60, 90))
        self.check(image, (255, 255, 255), (83, 107, 320, 178), "interior")

    def test_gradient_bubble_is_cleaned(self):
        image = page()
        ramp = np.linspace(200, 250, 400).astype(np.uint8)
        image[:] = np.stack([ramp, np.full(400, 235, np.uint8), 255 - ramp // 4], axis=1)[None]
        write(image, "YES, I THINK WE", (90, 140), (30, 110, 60))
        write(image, "SHOULD DESTROY IT.", (75, 175), (30, 110, 60))
        mask = text_mask(image, image[5, 5]) * 0
        mask[115:185, 70:340] = (np.abs(image[115:185, 70:340].astype(int) - [30, 110, 60]).sum(axis=2) < 120) * 255
        verdict = classify_region(image, mask, [quad(73, 117, 335, 183)])
        self.assertEqual(verdict["kind"], "interior", verdict)

    def test_white_bubble_beside_coloured_art_is_cleaned(self):
        # 0.5.2 tested a wide rectangle that reached the art around the bubble.
        image = noisy_art()
        bubble(image, (200, 150), (140, 70), (255, 255, 255))
        write(image, "ABOUT DESTROYING", (95, 145), (20, 20, 60), 0.75)
        write(image, "THE MAGE TOWER", (105, 175), (20, 20, 60), 0.75)
        self.check(image, (255, 255, 255), (93, 125, 310, 182), "interior")

    def test_text_over_artwork_is_preserved(self):
        image = noisy_art()
        write(image, "CLENCH", (110, 160), (90, 20, 90), 1.4)
        mask = np.zeros(image.shape[:2], np.uint8)
        verdict = classify_region(image, mask, [quad(105, 120, 270, 168)])
        self.assertEqual(verdict["kind"], "art", verdict)

    def test_empty_region_is_never_cleaned(self):
        self.assertEqual(classify_region(page(), None, [])["kind"], "art")


class SpacingTest(unittest.TestCase):
    def test_restores_space_after_punctuation(self):
        self.assertEqual(normalize_spacing("Sim,eu estava prestes a fazê-lo."), "Sim, eu estava prestes a fazê-lo.")
        self.assertEqual(normalize_spacing("Understood,Kaiser."), "Understood, Kaiser.")
        self.assertEqual(normalize_spacing("HARU,SOBRE"), "HARU, SOBRE")
        self.assertEqual(normalize_spacing("Também,vou mudar."), "Também, vou mudar.")
        self.assertEqual(normalize_spacing("Sério?Não acredito!Vamos"), "Sério? Não acredito! Vamos")
        self.assertEqual(normalize_spacing("Acabou.Agora vamos"), "Acabou. Agora vamos")

    def test_removes_space_before_punctuation(self):
        self.assertEqual(normalize_spacing("O quê ?  Não , obrigado ."), "O quê? Não, obrigado.")

    def test_keeps_numbers_and_ellipses(self):
        for text in ("Custa 3,5 moedas.", "Às 10:30 em ponto.", "Bem... talvez.", "Eu...", "V.S.O.P"):
            self.assertEqual(normalize_spacing(text), text)

    def test_cjk_is_untouched(self):
        self.assertEqual(normalize_spacing("何、これ？"), "何、これ？")

    def test_compact_symbols_keeps_spaces_outside_cjk(self):
        original = lambda text: text.replace(", ", ",")
        compact = compact_symbols(original)
        self.assertEqual(compact("Sim, eu sei..."), "Sim, eu sei…")
        self.assertEqual(compact("はい、 そう"), original("はい、 そう"))


class WholeWordTest(unittest.TestCase):
    @staticmethod
    def width(font_size, text):
        return len(text) * font_size // 2

    def letter_splitting_engine(self, font_size, text, max_width, max_height, language, hyphenate):
        """Mimics the engine: a word wider than the box is cut at any letter."""
        lines, line = [], ""
        for word in text.split():
            while self.width(font_size, word) > max_width:
                cut = max(1, max_width * 2 // font_size)
                lines.append(word[:cut])
                word = word[cut:]
            candidate = f"{line} {word}".strip()
            if line and self.width(font_size, candidate) > max_width:
                lines.append(line)
                candidate = word
            line = candidate
        lines.append(line)
        return lines, [self.width(font_size, x) for x in lines]

    def test_engine_mimic_reproduces_the_bug(self):
        lines, _ = self.letter_splitting_engine(20, "O que está acontecendo?", 100, 80, "PTB", False)
        self.assertTrue(broken_words("O que está acontecendo?", lines), lines)

    def test_words_are_never_split_without_hyphenation(self):
        calc = whole_word_breaker(self.letter_splitting_engine, self.width)
        for text in ("O que está acontecendo?", "Understood, Kaiser.", "ABSOLUTAMENTE NÃO!",
                     "Nietzschean assumiu a torre"):
            lines, _ = calc(20, text, 100, 80, "PTB", False)
            self.assertFalse(broken_words(text, lines), (text, lines))

    def test_hyphenation_mode_is_left_to_the_engine(self):
        seen = []
        def engine(font_size, text, max_width, *rest):
            seen.append(max_width)
            return [text], [0]
        whole_word_breaker(engine, self.width)(20, "acontecendo", 50, 80, "PTB", True)
        self.assertEqual(seen, [50])


class PipelineHookTest(unittest.TestCase):
    """The same decision must drive translation, mask and rendering."""

    def page_with_bubble_and_art(self):
        image = noisy_art((600, 300))
        bubble(image, (150, 150), (130, 70), (240, 210, 220), (200, 60, 90))
        write(image, "NO WAY!", (95, 160), (200, 60, 90))
        write(image, "CLENCH", (390, 160), (90, 20, 90), 1.4)
        mask = np.zeros(image.shape[:2], np.uint8)
        mask[130:170, 90:215] = (np.abs(image[130:170, 90:215].astype(int) - [200, 60, 90]).sum(axis=2) < 90) * 255
        return image, mask

    def run_merge(self, ignore_bubble):
        import asyncio
        from types import SimpleNamespace
        from engine_compat import classify_regions
        image, mask = self.page_with_bubble_and_art()
        regions = [SimpleNamespace(name="bubble", lines=np.array([quad(92, 135, 212, 166)])),
                   SimpleNamespace(name="art", lines=np.array([quad(385, 120, 545, 168)]))]
        async def merge(self, config, ctx):
            return list(regions)
        ctx = SimpleNamespace(img_rgb=image, mask_raw=mask)
        config = SimpleNamespace(ocr=SimpleNamespace(ignore_bubble=ignore_bubble))
        kept = asyncio.run(classify_regions(merge)(None, config, ctx))
        return [r.name for r in kept], [r.name for r in ctx.mangalate_preserved]

    def test_art_text_is_removed_before_translation_and_reported(self):
        self.assertEqual(self.run_merge(8), (["bubble"], ["art"]))

    def test_allow_art_text_keeps_every_region(self):
        self.assertEqual(self.run_merge(0), (["bubble", "art"], []))


class DetectionFallbackTest(unittest.TestCase):
    class Detector(str):
        @property
        def value(self):
            return str(self)

    def config(self, name):
        import copy
        detector = SimpleNamespaceCopy(detector=self.Detector(name), detection_size=2048)
        return SimpleNamespaceCopy(detector=detector)

    def run_detect(self, name, found):
        import asyncio
        from engine_compat import detection_fallback
        calls = []
        async def detect(self, config, ctx):
            calls.append((str(config.detector.detector), config.detector.detection_size))
            return (found.get(str(config.detector.detector), []), "mask", None)
        result = asyncio.run(detection_fallback(detect)(None, self.config(name), None))
        return result[0], calls

    def test_ctd_empty_page_retries_with_default_detector(self):
        lines, calls = self.run_detect("ctd", {"default": ["line"]})
        self.assertEqual(lines, ["line"])
        self.assertEqual(calls, [("ctd", 2048), ("default", 1536)])

    def test_ctd_with_text_or_other_detector_runs_once(self):
        self.assertEqual(self.run_detect("ctd", {"ctd": ["a"]})[1], [("ctd", 2048)])
        self.assertEqual(self.run_detect("default", {})[1], [("default", 2048)])

    def test_both_empty_keeps_original_result(self):
        lines, calls = self.run_detect("ctd", {})
        self.assertEqual((lines, len(calls)), ([], 2))


class SimpleNamespaceCopy:
    def __init__(self, **values):
        self.__dict__.update(values)

    def model_copy(self, deep=False):
        import copy
        return copy.deepcopy(self)


if __name__ == "__main__":
    unittest.main()
