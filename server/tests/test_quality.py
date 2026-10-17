"""Regression tests for cleanup classification and Portuguese line breaking.

Only numpy/OpenCV are needed; all images are synthetic.
"""
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import quality
from quality import (broken_words, bubble_glyphs, classify_region, compact_symbols, normalize_spacing,
                     repair_lines, whole_word_breaker)

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


class LineRepairTest(unittest.TestCase):
    """Lines the detector mask covers but no line box does (TBATE 236 p6, Grand Blue 87 p3)."""

    LINES = ["THE KI", "RESTRAINER", "MUST'VE MAL-", "FUNCTIONED."]

    def bubble_mask(self):
        image = page((0, 0, 0), (420, 320))
        boxes = []
        for i, text in enumerate(self.LINES):
            (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
            x, y = 210 - w // 2, 60 + i * 34
            cv2.putText(image, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
            boxes.append((x - 2, y - h - 3, x + w + 2, y + 6))
        return np.ascontiguousarray(image[:, :, 0]), boxes

    def test_missing_line_is_added(self):
        mask, boxes = self.bubble_mask()
        repaired, changes = repair_lines(mask, boxes[:2] + boxes[3:])
        self.assertEqual([kind for kind, _, _ in changes], ["added"])
        added = [box for box, source in repaired if source is None]
        self.assertEqual(len(added), 1)
        self.assertTrue(boxes[2][1] <= added[0][1] < added[0][3] <= boxes[2][3])

    def test_box_holding_two_lines_is_split(self):
        mask, boxes = self.bubble_mask()
        both = (min(boxes[2][0], boxes[3][0]), boxes[2][1], max(boxes[2][2], boxes[3][2]), boxes[3][3])
        repaired, changes = repair_lines(mask, boxes[:2] + [both])
        self.assertEqual([kind for kind, _, _ in changes], ["split"])
        self.assertEqual(len(repaired), 4)

    def test_complete_page_is_untouched(self):
        mask, boxes = self.bubble_mask()
        repaired, changes = repair_lines(mask, boxes)
        self.assertEqual(changes, [])
        self.assertEqual([box for box, _ in repaired], boxes)

    def test_vertical_lettering_is_not_split(self):
        mask = np.zeros((300, 200), np.uint8)
        for i, letter in enumerate("BOOM"):
            cv2.putText(mask, letter, (90, 50 + i * 50), cv2.FONT_HERSHEY_SIMPLEX, 1.4, 255, 3)
        lines = [(20, 20, 160, 40), (20, 250, 160, 270)]
        repaired, changes = repair_lines(mask, lines + [(85, 15, 125, 215)])
        self.assertEqual([c for c in changes if c[0] == "split"], [])

    def test_far_away_blob_is_not_a_line(self):
        mask, boxes = self.bubble_mask()
        cv2.rectangle(mask, (20, 290), (90, 310), 255, -1)  # art far below the bubble
        _, changes = repair_lines(mask, boxes)
        self.assertEqual(changes, [])

    def test_hook_replaces_textlines_before_ocr(self):
        import asyncio
        import types
        from types import SimpleNamespace
        from engine_compat import repair_textlines

        class Quad:
            def __init__(self, pts, text, prob):
                self.pts, self.text, self.prob, self.direction = np.asarray(pts), text, prob, "h"
        fake = types.ModuleType("manga_translator.utils")
        fake.Quadrilateral = Quad
        package = types.ModuleType("manga_translator")
        package.utils = fake
        mask, boxes = self.bubble_mask()
        lines = [Quad(quad(*b), "", 0.9) for i, b in enumerate(boxes) if i != 2]
        async def detect(self, config, ctx):
            return lines, mask, mask
        ctx = SimpleNamespace(img_rgb=np.zeros(mask.shape + (3,), np.uint8))
        saved = {k: sys.modules.get(k) for k in ("manga_translator", "manga_translator.utils")}
        sys.modules.update({"manga_translator": package, "manga_translator.utils": fake})
        try:
            result = asyncio.run(repair_textlines(detect)(None, None, ctx))
        finally:
            for key, value in saved.items():
                if value is None:
                    sys.modules.pop(key, None)
                else:
                    sys.modules[key] = value
        self.assertEqual(len(result[0]), 4)
        self.assertEqual(len(ctx.mangalate_line_repairs), 1)
        self.assertIs(result[1], mask)


class OcrRescueTest(unittest.TestCase):
    """A line dropped by the OCR threshold inside a paragraph is read again (TBATE 236 p6)."""

    class Line:
        def __init__(self, box, text=""):
            self.pts, self.text, self.prob, self.direction = np.asarray(quad(*box)), text, 0.0, "h"

    def run_ocr(self, lines, dropped):
        import asyncio
        import types
        from types import SimpleNamespace
        from engine_compat import rescue_ocr, RESCUE_PROB
        seen = {}
        async def dispatch(name, image, textlines, config, device, verbose):
            seen["prob"], seen["count"] = config.prob, len(textlines)
            for line in textlines:
                line.text, line.prob = "MUSTVE MAL-", 0.08
            return list(textlines)
        module = types.ModuleType("manga_translator.ocr")
        module.dispatch = dispatch
        async def original(self, config, ctx):
            for line in ctx.textlines:
                line.text = "" if line in dropped else "OK TEXT"
            return [line for line in ctx.textlines if line not in dropped]
        ocr_config = SimpleNamespace(ocr="48px", prob=None, model_copy=lambda deep: SimpleNamespace(ocr="48px", prob=None))
        config = SimpleNamespace(ocr=ocr_config, render=SimpleNamespace(font_color_fg=None, font_color_bg=None))
        ctx = SimpleNamespace(textlines=lines, img_rgb=None)
        translator = SimpleNamespace(device="cpu", verbose=False)
        saved = sys.modules.get("manga_translator.ocr")
        sys.modules["manga_translator.ocr"] = module
        try:
            result = asyncio.run(rescue_ocr(original)(translator, config, ctx))
        finally:
            if saved is None:
                sys.modules.pop("manga_translator.ocr", None)
            else:
                sys.modules["manga_translator.ocr"] = saved
        self.assertTrue(not seen or seen["prob"] == RESCUE_PROB)
        return result, seen, ctx

    def test_dropped_line_between_kept_lines_is_read_again(self):
        lines = [self.Line((100, 40 + i * 34, 300, 68 + i * 34)) for i in range(4)]
        result, seen, ctx = self.run_ocr(lines, [lines[2]])
        self.assertEqual(seen["count"], 1)
        self.assertEqual(len(result), 4)
        self.assertEqual(len(ctx.mangalate_ocr_rescued), 1)

    def test_lonely_dropped_line_is_left_alone(self):
        lines = [self.Line((100, 40, 300, 68)), self.Line((100, 600, 300, 628))]
        result, seen, _ = self.run_ocr(lines, [lines[1]])
        self.assertEqual(seen, {})
        self.assertEqual(len(result), 1)


class BubbleGlyphTest(unittest.TestCase):
    """Letters the detector mask missed are found as holes in the flat interior (TBATE new p12)."""

    def page(self, double_outline=False):
        image = np.full((400, 500, 3), 60, np.uint8)
        cv2.ellipse(image, (250, 200), (200, 150), 0, 0, 360, (250, 250, 250), -1)
        cv2.ellipse(image, (250, 200), (200, 150), 0, 0, 360, (0, 0, 0), 4)
        if double_outline:
            cv2.ellipse(image, (250, 200), (185, 135), 0, 0, 360, (170, 170, 170), 1)
        for i, text in enumerate(["THIS IS", "GOING TO BE", "OF US."]):
            cv2.putText(image, text, (150, 150 + i * 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (10, 10, 10), 3)
        return image

    def test_letters_below_the_box_are_found(self):
        image = self.page()
        found = bubble_glyphs(image, (145, 120, 360, 200), 30, near=1.6)
        self.assertGreater(found[205:240, 150:300].sum(), 100)   # "OF US." line
        self.assertFalse(found[:, :60].any())                    # nothing outside the bubble

    def test_hairline_of_a_double_outline_is_not_a_letter(self):
        image = self.page(double_outline=True)
        found = bubble_glyphs(image, (145, 120, 360, 240), 30, near=3)
        self.assertFalse(found[60:70, 200:300].any())            # top of the inner hairline

    def test_text_on_art_gives_nothing(self):
        image = noisy_art((500, 400))
        write(image, "CLENCH", (100, 200), (10, 10, 10), 1.4)
        self.assertFalse(bubble_glyphs(image, (95, 160, 300, 210), 40).any())

    def test_missing_line_is_added_when_the_mask_misses_it(self):
        image = self.page()
        mask = np.zeros(image.shape[:2], np.uint8)
        mask[120:200, 145:360] = 255  # detector saw the first two lines only
        boxes = [(145, 122, 290, 158), (145, 162, 360, 198)]
        seen = mask > 0
        for box in boxes:
            seen |= bubble_glyphs(image, box, box[3] - box[1], near=1.6)
        _, changes = repair_lines(seen.astype(np.uint8) * 255, boxes)
        self.assertEqual([kind for kind, _, _ in changes], ["added"])


class PageRowsTest(unittest.TestCase):
    """Regions lying only in the borrowed neighbour strips are not translated."""

    def test_only_regions_touching_the_page_are_kept(self):
        from types import SimpleNamespace
        from engine_compat import on_page
        above = SimpleNamespace(xyxy=(0, 10, 50, 90))
        crossing = SimpleNamespace(xyxy=(0, 90, 50, 130))
        inside = SimpleNamespace(xyxy=(0, 300, 50, 340))
        below = SimpleNamespace(xyxy=(0, 1010, 50, 1060))
        kept, skipped = on_page([above, crossing, inside, below], (100, 1000))
        self.assertEqual(kept, [crossing, inside])
        self.assertEqual(skipped, [above, below])

    def test_without_a_strip_everything_is_kept(self):
        from types import SimpleNamespace
        from engine_compat import on_page
        regions = [SimpleNamespace(xyxy=(0, 0, 10, 10))]
        self.assertEqual(on_page(regions, None), (regions, []))


if __name__ == "__main__":
    unittest.main()


class GoldStandardTextTest(unittest.TestCase):
    def test_leading_ellipsis_has_no_space(self):
        self.assertEqual(quality.normalize_spacing("… mas eu"), "…mas eu")  # TBATE 240 p30
        self.assertEqual(quality.normalize_spacing("Ok… Vamos"), "Ok… Vamos")

    def test_lost_negation_asks_again(self):
        notes = quality.translation_problems(["I'M NOT FAMILIAR WITH IT"], ["Estou familiarizado com isso."])
        self.assertTrue(any("negation" in n for n in notes))
        for source, text in (("I'M NOT FAMILIAR", "Não conheço."), ("ISN'T IT GREAT?", "Que ótimo, né?"),
                             ("I CAN'T WAIT!", "Mal posso esperar!"), ("NO ONE CAME", "Ninguém veio."),
                             ("I CANNOT ALLOW THIS", "Isso é inaceitável."), ("HELLO", "Olá.")):
            self.assertFalse(quality.lost_negation(source, text), source)

    def test_stacked_orphan_lines_are_a_paragraph(self):
        h = 20
        para = [(100, 100 + i * 24, 180 + (i % 2) * 10, 120 + i * 24) for i in range(4)]
        stray = [(400, 300, 440, 320)]
        kept = quality.paragraph_lines(para + stray, h)
        self.assertEqual(sorted(kept), sorted(para))
        self.assertEqual(quality.paragraph_lines(stray, h), [])


class OuroTwoTest(unittest.TestCase):
    """What the second gold-standard round showed."""

    def test_ocr_mixups_are_undone(self):
        cases = {
            "TM LINEAMILIAR WITH THE WALL": "I'M UNFAMILIAR WITH THE WALL",  # TBATE 240 p32
            "YOUR ARMS BEING PULLEO": "YOUR ARMS BEING PULLED",             # Grand Blue p45
            "I BORE L/TTLE FONDNESS": "I BORE LITTLE FONDNESS",
            "PRAISEO YOUR STRATEGIO ACUMEN": "PRAISED YOUR STRATEGIC ACUMEN",
            "THEY COVERED /T UP.": "THEY COVERED IT UP.",
        }
        for source, expected in cases.items():
            self.assertEqual(quality.fix_ocr_words(source)[0], expected)
        for kept in ("OOH! CARIA LOVES THOSE.", "THATS OKAY. SHOULDNT YOU", "COMMANDER VIRION",
                     "ALBOLD, BACK TO ELSHIRE", "Mixed case words like Pulleo", "HUH?"):
            self.assertEqual(quality.fix_ocr_words(kept)[0], kept)
        self.assertEqual(quality.fix_ocr_words("THE PULLEO", keep=["PULLEO"])[0], "THE PULLEO")

    def test_second_reading_of_the_same_letters_is_dropped(self):
        boxes = [(181, 478, 240, 527), (177, 469, 239, 535), (600, 100, 700, 200)]
        self.assertEqual(quality.duplicate_regions(boxes, ["GOT IT!", "8E", "SORRY"]), {1})
        self.assertEqual(quality.duplicate_regions(boxes[:1] + boxes[2:], ["GOT IT!", "SORRY"]), set())

    def test_stutter_keeps_the_word_lowercase(self):
        self.assertEqual(quality.tidy_start("E-Eu tô com medo, Grey."), "E-eu tô com medo, Grey.")
        self.assertEqual(quality.tidy_start("A-Arthur, espera", names={"Arthur"}), "A-Arthur, espera")

    def test_feminine_after_estar_needs_a_woman(self):
        notes = quality.translation_problems(["YOU MUST BE WORRIED ABOUT EVERYONES SAFETY."],
                                             ["Você deve estar preocupada com a segurança de todos."])
        self.assertTrue(any("feminine" in n for n in notes))


class OuroThreeTest(unittest.TestCase):
    def test_small_text_inside_a_big_box_is_not_a_duplicate(self):
        # Grand Blue p43/p55: "SORRY" under a "FULL YALL" box four times its size is another text.
        boxes = [(595, 1583, 690, 1625), (518, 1587, 691, 1687)]
        self.assertEqual(quality.duplicate_regions(boxes, ["SORRY", "FULL YALL."]), set())
        same = [(100, 100, 200, 150), (95, 98, 205, 160)]
        self.assertEqual(quality.duplicate_regions(same, ["GOT IT!", "GOTIT 8E 3"]), {1})

    def test_english_sound_effects(self):
        for sfx in ("VLOOSH", "SPLOOSH!", "GRRR", "KONK", "R", "K."):
            self.assertTrue(quality.english_sound_effect(sfx), sfx)
        for word in ("BOB", "NO!", "HELLO", "TOKITA", "I JUST CANT GET IT!", "I...", "A", "O!", "H?"):
            self.assertFalse(quality.english_sound_effect(word), word)


class AddedNegationTest(unittest.TestCase):
    def test_added_negation_asks_again(self):
        # TBATE 238 p42: "I WANT TO FIGHT IN THE WAR!" -> "Eu não quero lutar na guerra!"
        notes = quality.translation_problems(["I WANT TO FIGHT IN THE WAR!"], ["Eu não quero lutar na guerra!"])
        self.assertTrue(any("no negation" in n for n in notes))
        for source, text in (("COUNT ME IN!", "Não quero ficar de fora!"), ("I DONT WANT IT", "Não quero."),
                             ("AS IF...", "Até parece..."), ("IM UNFAMILIAR WITH IT", "Não conheço.")):
            self.assertFalse(quality.added_negation(source, text), source)


class BubbleScanTest(unittest.TestCase):
    """Small white bubbles the detector missed (Grand Blue pp. 19/27)."""

    def page(self, text="I SEE.", shape="ellipse"):
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (700, 700), (150, 150, 150))
        d = ImageDraw.Draw(img)
        if shape == "ellipse":
            d.ellipse((250, 250, 450, 400), fill="white", outline="black", width=3)
        else:  # a jagged burst
            pts = []
            for k in range(24):
                r = 110 if k % 2 else 60
                a = np.pi * k / 12
                pts.append((350 + r * np.cos(a), 325 + r * np.sin(a)))
            d.polygon(pts, fill="white", outline="black")
        font = ImageFont.truetype(str(Path(__file__).resolve().parents[1] / "fonts" / "ComicNeue-Bold.ttf"), 26)
        w = d.textlength(text, font=font)
        d.text((350 - w / 2, 312), text, fill="black", font=font)
        return np.array(img)

    def test_finds_text_in_undetected_bubble(self):
        found = quality.bubble_text_lines(self.page(), [])
        self.assertEqual(len(found), 1)
        bubble, rows, letters = found[0]
        self.assertEqual(len(rows), 1)
        x0, y0, x1, y1 = rows[0]
        self.assertTrue(300 < x0 < 350 < x1 < 400 and 300 < y0 < y1 < 350, rows[0])
        self.assertTrue(letters[y0:y1, x0:x1].any())

    def test_bubble_with_a_detected_box_is_skipped(self):
        self.assertEqual(quality.bubble_text_lines(self.page(), [(320, 310, 380, 340)]), [])

    def test_jagged_burst_and_empty_bubble_are_skipped(self):
        self.assertEqual(quality.bubble_text_lines(self.page(shape="burst"), []), [])
        self.assertEqual(quality.bubble_text_lines(self.page(text=""), []), [])

    def test_reads_as_speech(self):
        for text in ("MUSCLE?", "I SEE.", "HOW'S THAT?", "WHAT ARE YOU"):
            self.assertTrue(quality.reads_as_speech(text), text)
        for text in ("GRAB", "REEE", "", "ZZZT!"):
            self.assertFalse(quality.reads_as_speech(text), text)

    def test_hook_adds_scanned_lines_and_paints_mask(self):
        import asyncio
        import types
        from types import SimpleNamespace
        from engine_compat import repair_textlines

        class Quad:
            def __init__(self, pts, text, prob):
                self.pts, self.text, self.prob, self.direction = np.asarray(pts), text, prob, "h"
        fake = types.ModuleType("manga_translator.utils")
        fake.Quadrilateral = Quad
        package = types.ModuleType("manga_translator")
        package.utils = fake
        image = self.page()
        mask = np.zeros(image.shape[:2], np.uint8)
        async def detect(self, config, ctx):
            return [], mask, None
        ctx = SimpleNamespace(img_rgb=image)
        saved = {k: sys.modules.get(k) for k in ("manga_translator", "manga_translator.utils")}
        sys.modules.update({"manga_translator": package, "manga_translator.utils": fake})
        try:
            result = asyncio.run(repair_textlines(detect)(None, None, ctx))
        finally:
            for key, value in saved.items():
                if value is None:
                    sys.modules.pop(key, None)
                else:
                    sys.modules[key] = value
        self.assertEqual(len(result[0]), 1)
        self.assertEqual(len(ctx.mangalate_scanned), 1)
        self.assertTrue(result[1].any())
        self.assertFalse(mask.any())

    def test_scanned_sound_stays_as_art(self):
        from types import SimpleNamespace
        from engine_compat import scanned_sounds
        speech = SimpleNamespace(xyxy=(300, 310, 400, 340), text="I SEE.")
        sound = SimpleNamespace(xyxy=(300, 310, 400, 340), text="GRAB")
        outside = SimpleNamespace(xyxy=(10, 10, 60, 40), text="GRAB")
        kept, drawn = scanned_sounds([speech, sound, outside], [(250, 250, 450, 400)])
        self.assertEqual(kept, [speech, outside])
        self.assertEqual(drawn, [sound])


class LeakingBubbleScanTest(unittest.TestCase):
    """A white bubble whose outline is broken where it meets a light background.

    Found on a real page: a sound effect lettered across the bubble outline left gaps,
    the bubble white ran into the light sky of the panel, and the scan saw one jagged
    white area touching the sound effect box, so the speech stayed in English.
    """

    SOUND = (398, 300, 440, 470)  # vertical sound effect box across the gaps, mostly outside the bubble

    @staticmethod
    def font(size):
        from PIL import ImageFont
        return ImageFont.truetype(str(Path(__file__).resolve().parents[1] / "fonts" / "ComicNeue-Bold.ttf"), size)

    def page(self, content="text", gap=10):
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (900, 1200), (120, 120, 120))
        d = ImageDraw.Draw(img)
        d.rectangle((420, 250, 600, 450), fill=(240, 240, 240))  # light sky beside the bubble
        d.ellipse((190, 250, 410, 550), fill="white", outline="black", width=4)
        if gap:  # the outline broken twice towards the sky, as between sound effect letters
            d.rectangle((395, 330, 425, 330 + gap - 1), fill="white")
            d.rectangle((395, 380, 425, 380 + gap - 1), fill="white")
        for k, y in enumerate(range(305, 465, 40)):  # the sound effect letters, dark, across the gaps
            d.text((404, y), "HUH!"[k], fill="black", font=self.font(30))
        if content == "text":
            font = self.font(26)
            for y, line in ((365, "WE CAN"), (400, "GO NOW.")):
                w = d.textlength(line, font=font)
                d.text((300 - w / 2, y), line, fill="black", font=font)
        elif content == "face":
            d.ellipse((255, 355, 345, 445), outline="black", width=3)
            d.ellipse((277, 382, 289, 394), fill="black")
            d.ellipse((311, 382, 323, 394), fill="black")
            d.arc((282, 406, 318, 424), 0, 180, fill="black", width=3)
        return np.array(img)

    def test_speech_in_a_bubble_open_to_a_light_background_is_found(self):
        found = quality.bubble_text_lines(self.page(), [self.SOUND])
        self.assertEqual(len(found), 1)
        bubble, rows, letters = found[0]
        self.assertEqual(len(rows), 2)
        self.assertLess(bubble[2], 430, bubble)  # the bubble alone, not the sky
        for x0, y0, x1, y1 in rows:
            self.assertTrue(200 < x0 < 300 < x1 < 400 and 350 < y0 < y1 < 450, rows)
        self.assertFalse(letters[:, 398:].any())  # the sound effect is not taken as speech

    def test_closed_bubble_touching_the_sound_box_is_unchanged(self):
        self.assertEqual(quality.bubble_text_lines(self.page(gap=0), [self.SOUND]), [])

    def test_face_in_an_open_bubble_is_not_speech(self):
        self.assertEqual(quality.bubble_text_lines(self.page(content="face"), [self.SOUND]), [])

    def test_open_bubble_already_detected_is_skipped(self):
        self.assertEqual(quality.bubble_text_lines(self.page(), [self.SOUND, (240, 360, 360, 440)]), [])

    def test_sky_alone_is_not_a_bubble(self):
        self.assertEqual(quality.bubble_text_lines(self.page(content=None), [self.SOUND]), [])


class ContainedRegionTest(unittest.TestCase):
    """Grand Blue p25: the tilted "LIKE" had its own region inside "LOOKS / IORI SCORED..."."""

    def region(self, box, texts, lines):
        from types import SimpleNamespace
        return SimpleNamespace(xyxy=box, texts=texts, lines=lines)

    def absorb(self, outer, inner):
        pairs = sorted(list(zip(outer.lines, outer.texts)) + list(zip(inner.lines, inner.texts)))
        return self.region(outer.xyxy, [t for _, t in pairs], [y for y, _ in pairs])

    def test_inner_line_joins_in_reading_order(self):
        outer = self.region((1096, 1383, 1231, 1612), ["LOOKS", "IORI", "SCORED"], [1400, 1460, 1495])
        inner = self.region((1115, 1392, 1214, 1465), ["LIKE"], [1428])
        other = self.region((300, 1400, 400, 1450), ["DON'T"], [1420])
        out = quality.absorb_contained([outer, inner, other], self.absorb)
        self.assertEqual(len(out), 2)
        self.assertIn(["LOOKS", "LIKE", "IORI", "SCORED"], [r.texts for r in out])

    def test_separate_bubble_is_kept(self):
        outer = self.region((0, 0, 400, 400), ["A"], [10])
        inner = self.region((150, 150, 200, 180), ["B"], [160])
        out = quality.absorb_contained([outer, inner], self.absorb, inside=lambda a, b: False)
        self.assertEqual(len(out), 2)


class ColumnTest(unittest.TestCase):
    """Grand Blue p19: "YOU / GOTTA / RELAX." beside "THERE'S NO POINT / ... / THROUGH IT."."""

    def page(self):
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (500, 300), "white")
        d = ImageDraw.Draw(img)
        font = ImageFont.truetype(str(Path(__file__).resolve().parents[1] / "fonts" / "ComicNeue-Bold.ttf"), 24)
        right = ["THERE'S NO", "POINT", "TRYING", "TO POWER", "THROUGH"]
        left = {3: "YOU", 4: "GOTTA", 5: "RELAX."}
        boxes = []
        for row in range(6):
            y = 20 + 30 * row
            spans = []
            if row in left:
                d.text((40, y), left[row], fill="black", font=font)
                spans.append((40, 40 + int(d.textlength(left[row], font=font))))
            if row < len(right):
                w = int(d.textlength(right[row], font=font))
                d.text((260 - w // 2, y), right[row], fill="black", font=font)
                spans.append((260 - w // 2, 260 - w // 2 + w))
            boxes.append((min(s[0] for s in spans), y + 4, max(s[1] for s in spans), y + 28))
        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY), boxes

    def test_box_across_two_columns_is_cut(self):
        gray, boxes = self.page()
        cuts = quality.column_cuts(gray, boxes)
        self.assertEqual(sorted(cuts), [3, 4])
        gx0, gx1 = cuts[3]
        self.assertTrue(boxes[5][2] <= gx0 + 2 and gx1 <= 260 - 60, cuts)

    def test_one_paragraph_is_not_cut(self):
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (500, 200), "white")
        d = ImageDraw.Draw(img)
        font = ImageFont.truetype(str(Path(__file__).resolve().parents[1] / "fonts" / "ComicNeue-Bold.ttf"), 24)
        boxes = []
        for row, text in enumerate(["I THOUGHT I'D", "OVERCOME MY FEAR,", "BUT THE WATER", "STILL FREAKS ME OUT!"]):
            w = int(d.textlength(text, font=font))
            d.text((250 - w // 2, 20 + 30 * row), text, fill="black", font=font)
            boxes.append((250 - w // 2, 24 + 30 * row, 250 - w // 2 + w, 48 + 30 * row))
        self.assertEqual(quality.column_cuts(cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY), boxes), {})

    def test_column_groups(self):
        self.assertEqual(quality.column_groups([(0, 0, 50, 10), (60, 0, 120, 10), (10, 12, 40, 22), (70, 12, 110, 22)]),
                         [[0, 2], [1, 3]])
        self.assertEqual(len(quality.column_groups([(0, 0, 100, 10), (20, 12, 80, 22), (40, 24, 140, 34)])), 1)

    def test_region_over_two_columns_is_split(self):
        from engine_compat import join_split_blocks

        class Block:
            def __init__(self, lines, texts, font_size=20, angle=0, prob=1.0, fg_color=None, bg_color=None):
                self.lines, self.texts = np.asarray(lines), list(texts)
                self.font_size, self.angle, self.prob = font_size, angle, prob
                self.fg_colors, self.bg_colors, self.horizontal = fg_color, bg_color, True
                pts = self.lines.reshape(-1, 2)
                self.xyxy = (*pts.min(axis=0), *pts.max(axis=0))
        rows = [(200, 0, 320, 20, "THERE'S NO"), (40, 30, 100, 50, "YOU"), (200, 30, 320, 50, "TO POWER"),
                (40, 60, 100, 80, "GOTTA"), (200, 60, 320, 80, "THROUGH")]
        block = Block([quad(*r[:4]) for r in rows], [r[4] for r in rows])
        out = join_split_blocks([block], np.full((300, 400, 3), 255, np.uint8))
        self.assertEqual(sorted(b.texts for b in out), [["THERE'S NO", "TO POWER", "THROUGH"], ["YOU", "GOTTA"]])


class BrokenWordTest(unittest.TestCase):
    """Words the letterer split across lines (Grand Blue p25 "ART- ISTRY" became "arte-ístria")."""

    def test_rejoined(self):
        cases = {"GIVE HIM POINTS FOR ART- ISTRY.": "GIVE HIM POINTS FOR ARTISTRY.",
                 "TOKITA IS STRAIN- ING?": "TOKITA IS STRAINING?",
                 "THATS ODDLY CONVINC ING.": "THATS ODDLY CONVINCING.",
                 "STOP PRETEND ING..": "STOP PRETENDING..",
                 "I'M SURE AZUSA- SAN APPRE- CIATED THAT!": "I'M SURE AZUSA-SAN APPRECIATED THAT!",
                 "HIGH- SCHOOL": "HIGH-SCHOOL"}
        for text, fixed in cases.items():
            self.assertEqual(quality.fix_ocr_words(text)[0], fixed)

    def test_real_words_kept_apart(self):
        for text in ("WALK IN TO THE ROOM", "A LOT OF FUN", "THE KING IS DEAD", "I CAN SING", "WAIT-- WHAT"):
            self.assertEqual(quality.fix_ocr_words(text), (text, 0))


class OuroSevenTest(unittest.TestCase):
    def test_short_ocr_mixups(self):
        self.assertEqual(quality.fix_ocr_words("IWO BODIES IN PAIN")[0], "TWO BODIES IN PAIN")
        self.assertEqual(quality.fix_ocr_words("ITLL PASS RIGHI THROUGH--")[0], "ITLL PASS RIGHT THROUGH--")
        for text in ("A LIL?", "I GOTTA GO", "YOU AND THE"):
            self.assertEqual(quality.fix_ocr_words(text), (text, 0))

    def test_two_rows_of_letters_are_speech(self):
        self.assertFalse(quality.reads_as_speech("ASS"))
        self.assertTrue(quality.reads_as_speech("ASS", several_rows=True))
        self.assertFalse(quality.reads_as_speech("REEE", several_rows=True))

    def test_scan_follows_rows_below_the_white_area(self):
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (400, 500), (150, 150, 150))
        d = ImageDraw.Draw(img)
        # The bubble runs off the page; the scan only sees the closed part above the line,
        # as the letters of the second row closed it off on the page.
        d.rectangle((100, 200, 300, 520), fill="white", outline="black", width=3)
        font = ImageFont.truetype(str(Path(__file__).resolve().parents[1] / "fonts" / "ComicNeue-Bold.ttf"), 26)
        d.text((165, 252), "ASS-", fill="black", font=font)
        d.rectangle((100, 286, 300, 287), fill="black")
        d.text((150, 290), "HOLE...", fill="black", font=font)
        found = quality.bubble_text_lines(np.array(img), [])
        self.assertEqual([len(rows) for _, rows, _ in found], [2])
