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
from quality import (broken_words, bubble_glyphs, glyphs_to_clean, classify_region, compact_symbols, normalize_spacing,
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

    def outlined(self, outline=True, colour=(255, 255, 255)):
        image = noisy_art((420, 200))
        letters = np.zeros(image.shape[:2], np.uint8)
        for text, y in (("SO THIS", 80), ("IS IT?", 140)):
            cv2.putText(letters, text, (60, y), cv2.FONT_HERSHEY_SIMPLEX, 1.6, 255, 4)
        if outline:
            image[cv2.dilate(letters, np.ones((9, 9), np.uint8)) > 0] = (0, 0, 0)
        image[letters > 0] = colour
        mask = np.zeros(image.shape[:2], np.uint8)
        mask[40:155, 50:330] = 255
        return image, mask, [quad(55, 45, 320, 90), quad(55, 105, 270, 150)]

    def test_outlined_lettering_over_art_is_its_own_interior(self):
        # Grand Blue 102 p31: white letters with a thick black outline over a dark,
        # toned background.  The outline belongs to the lettering, not to the art.
        image, mask, quads = self.outlined()
        self.assertEqual(classify_region(image, mask, quads)["kind"], "contorno")

    def test_one_outlined_word_over_art_stays_art(self):
        # The usual sound effect: one word, white with a black outline, drawn over the art.
        image = noisy_art((420, 200))
        letters = np.zeros(image.shape[:2], np.uint8)
        cv2.putText(letters, "BAM", (60, 110), cv2.FONT_HERSHEY_SIMPLEX, 1.6, 255, 4)
        image[cv2.dilate(letters, np.ones((9, 9), np.uint8)) > 0] = (0, 0, 0)
        image[letters > 0] = (255, 255, 255)
        mask = np.zeros(image.shape[:2], np.uint8)
        mask[60:125, 50:200] = 255
        self.assertEqual(classify_region(image, mask, [quad(55, 65, 190, 120)])["kind"], "art")

    def test_dark_letters_in_a_white_bubble_are_not_outlined_lettering(self):
        image = noisy_art((420, 200))
        image[30:165, 45:335] = 255  # a narrow white bubble; the art comes right up to it
        letters = np.zeros(image.shape[:2], np.uint8)
        for text, y in (("SO THIS", 80), ("IS IT?", 140)):
            cv2.putText(letters, text, (60, y), cv2.FONT_HERSHEY_SIMPLEX, 1.6, 255, 6)
        image[letters > 0] = 0
        self.assertNotEqual(classify_region(image, letters, [quad(55, 45, 320, 90), quad(55, 105, 270, 150)])["kind"],
                            "contorno")

    def test_plain_lettering_over_art_stays_art(self):
        for outline, colour in ((False, (255, 255, 255)), (False, (0, 0, 0))):
            image, mask, quads = self.outlined(outline, colour)
            self.assertEqual(classify_region(image, mask, quads)["kind"], "art", (outline, colour))

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

    LINES = (("NO WAIT DONT", 60), ("TAKE THOSE TWO", 88), ("THEY ARE THE ONLY", 116), ("WAY I CAN FIX", 144),
             ("ALL OF THIS NOW", 172))

    def paragraph(self, image):
        """Five lines of dark lettering; returns the detector mask (letters only) and the line quads."""
        letters = page(size=(image.shape[1], image.shape[0]))
        quads = []
        for text, y in self.LINES:
            write(image, text, (100, y), (0, 0, 0), 0.7)
            write(letters, text, (100, y), (0, 0, 0), 0.7)
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
            quads.append(quad(98, y - th - 3, 102 + tw, y + 4))
        return text_mask(letters, (255, 255, 255)), quads

    def strands(self, image):
        for x in (150, 205, 250, 290):
            strand = np.array([[x + 30, 10], [x + 12, 90], [x, 170], [x - 20, 250]], np.int32)
            cv2.polylines(image, [strand], False, (0, 0, 0), 2, cv2.LINE_AA)
        return image

    def test_lettering_on_paper_crossed_by_drawn_strokes_cleans_only_its_letters(self):
        # One Piece 1161 p5: a speech written on a white part of the drawing, with strands of
        # hair running between the lines.  The margin is mostly paper (0.91), so it was cleaned
        # as a bubble and the hair went with the letters.  It is still translated, but only
        # the letters are cleaned.
        image = self.strands(page(size=(420, 260)))
        mask, quads = self.paragraph(image)
        verdict = classify_region(image, mask, quads)
        self.assertGreaterEqual(verdict["interior_share"], quality.MIN_INTERIOR_SHARE, verdict)
        self.assertEqual(verdict["kind"], "tracos", verdict)
        allowed = quality.letters_area(image, mask, quads)
        self.assertTrue(allowed[mask > 0].all())                 # every letter is cleaned
        lines = quality._line_mask(image.shape, [np.asarray(q, np.float32) for q in quads]) > 0
        strand_ink = (image.min(axis=2) < 128) & ~cv2.dilate(lines.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
        self.assertTrue(strand_ink.any())
        self.assertFalse(allowed[strand_ink].any())              # the strands between and around the lines stay
        # The new lettering is planned as if the line boxes were paper: the strands that
        # still cross them must not shrink its room.
        boxes, colour = quality.paper_under(image, quads)
        self.assertTrue(boxes[lines].all())
        self.assertTrue((colour >= 240).all(), colour)

    def test_light_outline_of_dark_letters_is_cleaned_with_them(self):
        # cap146 p178: black letters with a white outline on a lilac page crossed by speed
        # lines.  With the letters alone, the flat fill took the white outline for the paper
        # and painted white ghosts of the letters.
        image = page((235, 222, 240), (420, 260))
        mask, quads = self.paragraph(page(size=(420, 260)))
        outline = cv2.dilate(mask, np.ones((11, 11), np.uint8)) > 0  # thicker than LETTER_GROW
        image[outline] = 255
        image[mask > 0] = 0
        allowed = quality.letters_area(image, mask, quads)
        self.assertTrue(allowed[outline].all())
        lines = quality._line_mask(image.shape, [np.asarray(q, np.float32) for q in quads]) > 0
        far = ~cv2.dilate(lines.astype(np.uint8), np.ones((21, 21), np.uint8)).astype(bool)
        self.assertFalse(allowed[far].any())                      # the page around stays

    def logo(self):
        """Lettering five times taller than a speech, crossed by the lines of its ornaments."""
        image, letters = page(size=(800, 600)), page(size=(800, 600))
        for canvas in (image, letters):
            cv2.putText(canvas, "LOGO", (150, 420), cv2.FONT_HERSHEY_SIMPLEX, 5.0, (0, 0, 0), 28, cv2.LINE_AA)
        for x in (170, 260, 350, 440, 530):
            cv2.line(image, (x + 20, 150), (x - 20, 600), (0, 0, 0), 3, cv2.LINE_AA)
        return image, text_mask(letters, (255, 255, 255)), [quad(140, 271, 560, 434)]

    def test_logo_crossed_by_its_ornaments_is_a_drawn_title(self):
        # One Piece 1161 p2: the series logo on a blank page read as lettering crossed by
        # strokes; it was cleaned and written over as "One Piece".
        image, mask, quads = self.logo()
        self.assertEqual(classify_region(image, mask, quads)["kind"], "tracos")
        self.assertTrue(quality.drawn_title(image.shape, quads))
        # Speech over the drawing, and letters stacked one per row in a tall bubble, are not.
        speech = self.strands(page(size=(420, 260)))
        _, lines = self.paragraph(speech)
        self.assertFalse(quality.drawn_title(speech.shape, lines))
        self.assertFalse(quality.drawn_title((1145, 784), [quad(112, 370, 149, 572)]))  # Grand Blue 102 p20 "GUYS!"

    def test_tight_bubble_and_one_crossing_line_stay_interior(self):
        # The outline runs along the margin, and a panel border (Grand Blue 102 p3) or a
        # tail crosses it only on two sides: still a bubble.
        image = page(size=(420, 260))
        cv2.ellipse(image, (210, 118), (170, 100), 0, 0, 360, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.line(image, (205, 0), (205, 259), (0, 0, 0), 2, cv2.LINE_AA)
        mask, quads = self.paragraph(image)
        verdict = classify_region(image, mask, quads)
        self.assertEqual(verdict["kind"], "interior", verdict)
        self.assertEqual(verdict["strokes"], 2, verdict)  # the border, above and below the text

    def test_lettering_at_the_edge_of_the_image_is_classified(self):
        # Ink on the last row or column of the image (a webtoon slice cut under a bubble)
        # once made the stroke count read past the image and fail the whole page.
        image = page(size=(420, 260))
        mask, quads = self.paragraph(image)
        image, mask = image[:180, :215].copy(), mask[:180, :215].copy()
        image[179, :] = 120
        image[:, 214] = 120
        quads = [[[min(x, 214), min(y, 179)] for x, y in q] for q in quads]
        self.assertIn(classify_region(image, mask, quads)["kind"], ("interior", "art"))
        self.assertEqual(quality.crossing_strokes(np.array([10, 179]), np.array([214, 10]), mask > 0,
                                                  np.ones(mask.shape, np.uint8), 6, 20), 0)

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

    def hatched_speech(self, text, dark=False, tone=False):
        import asyncio
        from types import SimpleNamespace
        from engine_compat import classify_regions
        image = page(size=(420, 260))
        if dark:
            image[:] = noisy_art((420, 260)) // 3
        mask, quads = BackgroundTest.paragraph(BackgroundTest, image)
        for x in range(60, 400, 20):  # hatching all around and between the lines
            cv2.line(image, (x, 0), (x - 40, 259), (0, 0, 0), 2)
        if tone:
            image[:] = 255
            for dy in (0, 1):
                for dx in (0, 1):
                    image[dy::4, dx::4] = 0  # screentone dots, 2 px every 4
            image[cv2.dilate(mask, np.ones((7, 7), np.uint8)) > 0] = 255  # the white outline of the letters
        image[mask > 0] = 0
        # The detector also marks the bits of hatching between the letters, as on the real page.
        boxes = quality._line_mask(image.shape, [np.asarray(q, np.float32) for q in quads]) > 0
        mask[boxes & (image.min(axis=2) < 128)] = 255
        region = SimpleNamespace(name="fala", text=text, lines=np.array(quads))
        async def merge(self, config, ctx):
            return [region]
        ctx = SimpleNamespace(img_rgb=image, mask_raw=mask)
        config = SimpleNamespace(ocr=SimpleNamespace(ignore_bubble=8))
        kept = asyncio.run(classify_regions(merge)(None, config, ctx))
        return [r.name for r in kept], region.mangalate_background

    def test_speech_over_hatching_on_a_light_page_is_translated(self):
        # One Piece 1161 p5 "WELL, CONSIDERING...": the hatching makes the margin art
        # (0.44), and the speech stayed in English.  Only its letters are cleaned now.
        kept, background = self.hatched_speech("WELL, I GUESS I DESERVE THIS TOO...")
        self.assertLess(background["interior_share"], quality.MIN_INTERIOR_SHARE)
        self.assertEqual((kept, background["kind"]), (["fala"], "tracos"))

    def test_sound_or_dark_art_under_the_letters_stays_as_drawn(self):
        self.assertEqual(self.hatched_speech("BAM")[0], [])
        self.assertEqual(self.hatched_speech("WELL, I GUESS I DESERVE THIS TOO...", dark=True)[0], [])
        # Grand Blue 102 p7: white-outlined letters over screentone; the white between the
        # dots is not paper, and cleaning the letters smeared the tone.
        self.assertEqual(self.hatched_speech("WELL, I GUESS I DESERVE THIS TOO...", tone=True)[0], [])

    def test_speech_the_mask_misses_or_two_speeches_stay_as_drawn(self):
        image = page(size=(420, 260))
        mask, quads = BackgroundTest.paragraph(BackgroundTest, image)
        self.assertTrue(quality.speech_on_paper(image, mask, quads))
        # Grand Blue 106 p16: a tilted line the detector mask missed left an English ghost.
        missed = mask.copy()
        missed[40:100] = 0
        self.assertFalse(quality.speech_on_paper(image, missed, quads))
        # Grand Blue 102 p33: two speeches side by side in one block, their lines interleaved.
        side = [quad(98, 40, 200, 64), quad(260, 40, 380, 64), quad(98, 70, 200, 94), quad(260, 70, 380, 94)]
        self.assertFalse(quality.speech_on_paper(image, mask, side))
        # Grand Blue 102 p4: a form drawn askew; the new lines are written level over it.
        centre = (210, 110)
        turn = cv2.getRotationMatrix2D(centre, 7, 1.0)
        tilted_image = cv2.warpAffine(image, turn, (420, 260), borderValue=(255, 255, 255))
        tilted_mask = cv2.warpAffine(mask, turn, (420, 260))
        tilted = [cv2.transform(np.asarray(q, np.float32).reshape(1, 4, 2), turn).reshape(4, 2) for q in quads]
        self.assertFalse(quality.speech_on_paper(tilted_image, tilted_mask, tilted))
        # Grand Blue 102 p20: "GUYS!" stacked one letter per row in a tall bubble came out tiny.
        stacked = page(size=(420, 260))
        letters = np.zeros(stacked.shape[:2], np.uint8)
        for i, ch in enumerate("GUYS!"):
            cv2.putText(letters, ch, (200, 45 + i * 45), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 255, 3)
        stacked[letters > 0] = 0
        self.assertFalse(quality.speech_on_paper(stacked, letters, [quad(190, 10, 235, 250)]))

    def test_letters_stacked_in_a_tall_bubble_are_a_bubble(self):
        # Grand Blue 102 p20: "GUYS!" one letter per row in a tall white bubble.  The box height
        # (200 px) was taken for the line height, the margin reached the art around the bubble,
        # and the speech stayed in English.
        image = noisy_art((300, 300))
        cv2.ellipse(image, (150, 150), (45, 135), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(image, (150, 150), (45, 135), 0, 0, 360, (0, 0, 0), 3)
        letters = np.zeros(image.shape[:2], np.uint8)
        for i, ch in enumerate("GUYS!"):
            cv2.putText(letters, ch, (138, 70 + i * 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 255, 3)
        image[letters > 0] = 0
        quads = [quad(132, 45, 168, 250)]
        self.assertTrue(quality.stacked(quads))
        self.assertEqual(classify_region(image, letters, quads)["kind"], "interior")
        self.assertFalse(quality.stacked([quad(100, 40, 300, 70)]))

    def test_stacked_translation_is_written_one_capital_per_row(self):
        import lettering
        font = str(Path(__file__).resolve().parents[1] / "fonts" / "ComicNeue-Bold.ttf")
        plan = lettering.plan_stacked((112, 370, 149, 572), "Pessoal!", font, 8)
        self.assertEqual(plan["lines"], list("PESSOAL!"))
        x0, y0, x1, y1 = plan["box"]
        self.assertTrue(y1 - y0 <= (572 - 370) * lettering.STACK_ROOM + 2 and abs((x0 + x1) / 2 - 130.5) <= 1, plan)
        self.assertIsNone(lettering.plan_stacked((112, 370, 149, 380), "Pessoal!", font, 8))  # no room: as drawn

    def test_line_box_running_onto_a_wall_is_still_speech(self):
        # Grand Blue 106 p16: the box of "IN WINTER?" runs a few px onto the screentone of the
        # wall beside it; those dots are not letters the detector missed.
        image = page(size=(420, 260))
        mask, quads = BackgroundTest.paragraph(BackgroundTest, image)
        image[:, 300:] = 255
        for dy in (0, 1):
            for dx in (0, 1):
                image[dy::4, 300 + dx::4] = 0
        quads = [[[x0, y0], [max(x1, 310), y0], [max(x1, 310), y1], [x0, y1]] if i == 2 else q
                 for i, q in enumerate(quads) for (x0, y0), _, (x1, y1), _ in [q]]
        self.assertTrue(quality.speech_on_paper(image, mask, quads))

    def test_lettering_crossed_by_strokes_is_translated(self):
        import asyncio
        from types import SimpleNamespace
        from engine_compat import classify_regions
        image = BackgroundTest.strands(None, page(size=(420, 260)))
        mask, quads = BackgroundTest.paragraph(BackgroundTest, image)
        region = SimpleNamespace(name="tracos", lines=np.array(quads))
        async def merge(self, config, ctx):
            return [region]
        ctx = SimpleNamespace(img_rgb=image, mask_raw=mask)
        config = SimpleNamespace(ocr=SimpleNamespace(ignore_bubble=8))
        kept = asyncio.run(classify_regions(merge)(None, config, ctx))
        self.assertEqual([r.name for r in kept], ["tracos"])
        self.assertEqual(region.mangalate_background["kind"], "tracos")

    def test_lines_kept_as_drawn_are_never_cleaned(self):
        # Grand Blue 102 p4: the box of a translated title ran onto the small print of a form
        # kept as drawn, and its mask erased words of that print.
        from types import SimpleNamespace
        title = SimpleNamespace(lines=np.array([[[100, 20], [300, 20], [300, 66], [100, 66]]]))
        form = SimpleNamespace(lines=np.array([[[40, 60], [360, 60], [360, 74], [40, 74]],
                                               [[40, 78], [360, 78], [360, 92], [40, 92]]]))
        keep = quality.kept_lines((200, 400), [form], [title])
        self.assertTrue(keep[82, 50] and keep[66, 350])            # the small print stays...
        self.assertTrue(keep[63, 200])                             # ...also where the title box ran onto it
        self.assertFalse(keep[35, 200])                            # the title is cleaned
        self.assertTrue(keep[56, 350])                             # with a ring around the print...
        self.assertFalse(keep[56, 200])                            # ...that never reaches into the title
        # A kept box lying inside the translated lines is a duplicate of that speech, and a kept box
        # around the whole speech (read as a sound effect) is the same text: both cleaned with it.
        duplicate = SimpleNamespace(lines=np.array([[[120, 30], [280, 30], [280, 50], [120, 50]]]))
        self.assertFalse(quality.kept_lines((200, 400), [duplicate], [title]).any())
        around = SimpleNamespace(lines=np.array([[[90, 10], [310, 10], [310, 76], [90, 76]]]))
        self.assertFalse(quality.kept_lines((200, 400), [around], [title]).any())
        self.assertFalse(quality.kept_lines((200, 400), [], [title]).any())

    def test_tall_kept_column_does_not_unmask_the_speech_beside_it(self):
        # Grand Blue 106 p38: a tall vertical sound effect kept as drawn next to a bubble.  A ring
        # as wide as its "line height" (the whole column) took the overhanging tips, comma and
        # "!" of the speech out of the mask, and they stayed in English.
        from types import SimpleNamespace
        column = SimpleNamespace(lines=np.array([[[300, 20], [340, 20], [340, 420], [300, 420]]]))
        speech = SimpleNamespace(lines=np.array([[[120, 200], [280, 200], [280, 222], [120, 222]]]))
        keep = quality.kept_lines((450, 400), [column], [speech])
        self.assertTrue(keep[200, 320])                            # the column stays
        self.assertFalse(keep[226, 200])                           # a tail just under the speech box is still cleaned
        self.assertFalse(keep[210, 285])                           # and a "!" just past its end
        self.assertLessEqual(int(keep[200, 340:].sum()), quality.KEEP_RING_MAX + 1)  # the ring is a few px

    def test_stroke_crossing_both_boxes_goes_with_the_block_holding_most_of_it(self):
        # Grand Blue 102 p6: the box of a vertical sound effect kept as drawn ran over the bottom
        # of "SMILE" (translated): those letters stayed half masked.  Grand Blue 102 p4: the "y"
        # of the small print ran into the title's box and lost its tip.
        from types import SimpleNamespace
        gray = np.full((200, 300), 255, np.uint8)
        gray[60:80, 100:110] = 0                                   # a letter of the speech, its foot in the column box
        gray[110:150, 200:204] = 0                                 # a stroke of the kept print, its tip in the speech box
        speech = SimpleNamespace(lines=np.array([[[90, 58], [210, 58], [210, 76], [90, 76]]]))
        column = SimpleNamespace(lines=np.array([[[95, 74], [130, 74], [130, 190], [95, 190]]]))
        print_ = SimpleNamespace(lines=np.array([[[150, 116], [260, 116], [260, 150], [150, 150]]]))
        keep = quality.kept_lines(gray.shape, [column, print_], [speech], gray)
        self.assertFalse(keep[60:80, 100:110].any())               # the letter of the speech is cleaned whole
        self.assertTrue(keep[110:150, 200:204].all())              # the stroke of the print is kept whole
        self.assertTrue(keep[150, 112])                            # the rest of the column stays

    def test_drawn_title_stays_as_drawn(self):
        import asyncio
        from types import SimpleNamespace
        from engine_compat import classify_regions
        image, mask, quads = BackgroundTest.logo(None)
        region = SimpleNamespace(name="logo", lines=np.array(quads), text="LOGO")
        async def merge(self, config, ctx):
            return [region]
        ctx = SimpleNamespace(img_rgb=image, mask_raw=mask)
        config = SimpleNamespace(ocr=SimpleNamespace(ignore_bubble=8))
        kept = asyncio.run(classify_regions(merge)(None, config, ctx))
        self.assertEqual(kept, [])
        self.assertEqual(region.mangalate_background["kind"], "logo")
        self.assertEqual(ctx.mangalate_preserved, [region])
        # The same lettering read as a line of English is a big shout over speed lines: translated.
        shout = SimpleNamespace(name="grito", lines=np.array(quads), text="GET OUT!!")
        async def merge_shout(self, config, ctx):
            return [shout]
        ctx = SimpleNamespace(img_rgb=image, mask_raw=mask)
        kept = asyncio.run(classify_regions(merge_shout)(None, config, ctx))
        self.assertEqual([r.name for r in kept], ["grito"])
        self.assertEqual(shout.mangalate_background["kind"], "tracos")


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

    def test_square_box_of_wide_lines_is_split(self):
        # One Piece 1153 p6 "YES, / MAJESTY / !!", Grand Blue 106 p22 "CON- / DOMS / ?!": one box as
        # tall as wide held three short lines; it was taken for vertical lettering, not split, and
        # the OCR dropped it.  Lines of one letter ("I" over "KNEW IT.") stay horizontal.
        mask = np.zeros((320, 300), np.uint8)
        lines = [(20, 20, 280, 40), (20, 280, 280, 300)]          # the page's usual lines
        rows = []
        for i, text in enumerate(["I", "KNEW", "IT."]):
            (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
            x, y = 150 - w // 2, 120 + i * 34
            cv2.putText(mask, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 255, 2)
            rows.append((x, y - h, x + w, y))
        box = (min(r[0] for r in rows) - 4, rows[0][1] - 4, max(r[2] for r in rows) + 4, rows[-1][3] + 4)
        self.assertLessEqual(box[2] - box[0], box[3] - box[1])    # as tall as wide
        repaired, changes = repair_lines(mask, lines + [box])
        self.assertEqual([kind for kind, _, _ in changes if kind == "split"], ["split"])
        parts = sorted((b for b, source in repaired if source == 2), key=lambda b: b[1])
        self.assertEqual(len(parts), 3)
        self.assertTrue(all(b[2] - b[0] >= b[3] - b[1] for b in parts), parts)  # all horizontal

    def test_far_away_blob_is_not_a_line(self):
        mask, boxes = self.bubble_mask()
        cv2.rectangle(mask, (20, 290), (90, 310), 255, -1)  # art far below the bubble
        _, changes = repair_lines(mask, boxes)
        self.assertEqual(changes, [])

    def big_and_small(self, small_lines):
        # Big shouted lettering sets the page line height; a small bubble far from it has no box.
        mask = np.zeros((520, 640), np.uint8)
        boxes = []
        for i, text in enumerate(["HOW CAN", "THIS BE", "SO HARD"]):
            (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.6, 4)
            x, y = 600 - w, 80 + i * 70
            cv2.putText(mask, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 1.6, 255, 4)
            boxes.append((x - 2, y - h - 3, x + w + 2, y + 4))
        small = []
        for i, text in enumerate(small_lines):
            (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)
            x, y = 90 - w // 2, 350 + i * 34
            cv2.putText(mask, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 255, 2)
            small.append((x, y - h, x + w, y))
        return mask, boxes, small

    def test_small_paragraph_on_a_page_of_big_lettering_is_added(self):
        # Grand Blue 102 p39: a three-line bubble in small letters next to a bubble
        # of big italic shouting was in the mask, but under half the page line height.
        mask, boxes, small = self.big_and_small(["DONT", "SAY", "MORE!"])
        repaired, changes = repair_lines(mask, boxes)
        added = sorted((box for box, source in repaired if source is None), key=lambda b: b[1])
        self.assertEqual(len(added), 3)
        for box, line in zip(added, small):
            self.assertTrue(line[1] - 2 <= box[1] < box[3] <= line[3] + 3, (box, line))

    def test_single_small_line_on_a_page_of_big_lettering_is_left(self):
        mask, boxes, _ = self.big_and_small(["SAY"])
        _, changes = repair_lines(mask, boxes)
        self.assertEqual(changes, [])

    def test_stacked_single_letters_on_a_page_of_big_lettering_are_left(self):
        # Letters stacked one per row (a vertical sound effect) are not a paragraph of lines.
        mask, boxes, _ = self.big_and_small([])
        for i, letter in enumerate("ABCD"):
            cv2.putText(mask, letter, (300, 300 + i * 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 255, 2)
        _, changes = repair_lines(mask, boxes)
        self.assertEqual(changes, [])

    def lettered(self, lines, step=34):
        # Black letters on white, and the detector mask of the same letters.
        gray = np.full((320, 420), 255, np.uint8)
        ink = []
        for i, text in enumerate(lines):
            (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
            x, y = 210 - w // 2, 60 + i * step
            alone = np.full_like(gray, 255)
            if not text:
                ink.append(None)
                continue
            cv2.putText(alone, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 0, 2)
            gray = np.minimum(gray, alone)
            rows, cols = np.flatnonzero((alone < 128).any(axis=1)), np.flatnonzero((alone < 128).any(axis=0))
            ink.append((int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1))
        mask = np.where(gray < 128, 255, 0).astype(np.uint8)
        return gray, mask, ink

    def test_box_clipping_the_letters_is_fitted(self):
        # Grand Blue 102 pp. 27/47: a box a row or more short of the letters made the OCR drop the line.
        gray, mask, ink = self.lettered(["THE KI", "RESTRAINER", "FUNCTIONED."])
        x0, y0, x1, y1 = ink[1]
        boxes = [ink[0], (x0, y0 + 2, x1, y1 - 3), ink[2]]
        repaired, changes = repair_lines(mask, boxes)
        self.assertEqual([kind for kind, _, _ in changes], ["fit"])
        fitted = repaired[1][0]
        self.assertTrue(fitted[1] <= y0 and fitted[3] >= y1, fitted)
        self.assertLess(fitted[3] - fitted[1], (y1 - y0) + 4)  # still one line, not two

    def test_box_missing_the_first_letter_grows_over_the_page(self):
        # Grand Blue 102 p42: the mask missed the "A" of "AMOUNT" and the OCR read "MOUN".
        gray, mask, ink = self.lettered(["THE KI", "RESTRAINER", "FUNCTIONED."])
        x0, y0, x1, y1 = ink[1]
        mask[:, :x0 + 18] = 0  # the detector lost the first letter
        boxes = [ink[0], (x0 + 18, y0 - 1, x1 + 1, y1 + 1), ink[2]]
        repaired, _ = repair_lines(mask, boxes, gray)
        self.assertLessEqual(repaired[1][0][0], x0)
        unchanged, _ = repair_lines(mask, boxes)  # without the page, the mask alone decides
        self.assertEqual(unchanged[1][0][0], x0 + 18)

    def test_outline_next_to_the_line_is_not_a_letter(self):
        gray, mask, ink = self.lettered(["THE KI", "RESTRAINER", "FUNCTIONED."])
        x0, y0, x1, y1 = ink[1]
        cv2.line(gray, (x0 - 8, 10), (x0 - 8, 300), 0, 3)  # bubble outline, taller than any line
        boxes = [ink[0], (x0 - 1, y0 - 1, x1 + 1, y1 + 1), ink[2]]
        repaired, changes = repair_lines(mask, boxes, gray)
        self.assertEqual(changes, [])
        self.assertEqual([box for box, _ in repaired], boxes)

    def test_overlapping_boxes_are_cut_line_by_line(self):
        # Grand Blue 102 p20: one box over "NOW," and half the next line, another over the
        # next two lines; the OCR dropped the second and the bubble stayed half in English.
        gray, mask, ink = self.lettered(["NOW,", "HOLD", "ON.", "", "", "", "ANOTHER LINE", "AND ONE MORE"], step=26)
        ink = ink[:3] + ink[6:]
        first = (ink[0][0], ink[0][1], ink[0][2], ink[1][1] + 14)  # takes most of "HOLD" too
        second = (min(ink[1][0], ink[2][0]) - 4, ink[0][3] - 6, max(ink[1][2], ink[2][2]) + 4, ink[2][3] + 12)
        others = [(x0 - 1, y0 - 1, x1 + 1, y1 + 1) for x0, y0, x1, y1 in ink[3:]]  # one-line boxes elsewhere
        repaired, changes = repair_lines(mask, [first, second] + others)
        self.assertIn("refit", [kind for kind, _, _ in changes])
        boxes = sorted((box for box, _ in repaired if box[1] < ink[3][1] - 10), key=lambda b: b[1])
        self.assertEqual(len(boxes), 3)
        for box, line in zip(boxes, ink):
            self.assertTrue(box[1] <= line[1] + 1 and box[3] >= line[3] - 1 and box[3] - box[1] < 1.5 * (line[3] - line[1]),
                            (box, line))

    def test_tilted_paragraph_boxes_are_left_alone(self):
        # Grand Blue 102 p3: boxes of a tilted paragraph overlap a little; none holds two lines.
        gray, mask, ink = self.lettered(["I JUST KNOW", "IT WILL COME", "BACK TO US"], step=24)
        boxes = [(x0 - 2, y0 - 2, x1 + 2, y1 + 8) for x0, y0, x1, y1 in ink]  # each reaches into the next line
        _, changes = repair_lines(mask, boxes)
        self.assertNotIn("refit", [kind for kind, _, _ in changes])

    def big_lines(self):
        # Small lettering elsewhere sets the page line height; two big lines touch through a few pixels.
        mask = np.zeros((420, 640), np.uint8)
        small = []
        for i in range(4):
            cv2.putText(mask, "SMALL TEXT", (20, 40 + i * 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, 255, 2)
            small.append((18, 40 + i * 26 - 18, 170, 40 + i * 26 + 4))
        cv2.putText(mask, "STUFF", (300, 220), cv2.FONT_HERSHEY_SIMPLEX, 2.4, 255, 12)
        cv2.putText(mask, "IS IT", (300, 290), cv2.FONT_HERSHEY_SIMPLEX, 2.4, 255, 12)
        rows = np.flatnonzero(mask[150:, 280:].any(axis=1)) + 150
        return mask, small, rows

    def test_touching_big_lines_are_cut_at_the_valley(self):
        # Grand Blue 102 p31: "96%," and "ISN'T IT?" touch through their outlines; one box held both.
        mask, small, rows = self.big_lines()
        gap = rows[0] + int(np.argmin([mask[y, 280:].sum() for y in range(rows[0] + 30, rows[-1] - 30)])) + 30
        mask[gap - 1:gap + 1, 400:404] = 255  # the lines touch at a few pixels
        top, bottom = (296, rows[0] - 2, 520, gap + 6), (296, gap - 6, 520, rows[-1] + 2)
        repaired, changes = repair_lines(mask, small + [top, bottom])
        big = sorted((b for b, _ in repaired if b[1] > 140), key=lambda b: b[1])
        self.assertEqual(len(big), 2, big)
        self.assertLessEqual(big[0][3], gap + 1)
        self.assertGreaterEqual(big[1][1], gap - 1)

    def test_line_cut_again_keeps_its_letters_past_the_boxes(self):
        # Grand Blue 102 p31: the boxes stopped before the last word of "ISN'T IT?"; cut again
        # inside them, the line lost the word and the translation lost its tag question.
        mask, small, rows = self.big_lines()
        gap = rows[0] + int(np.argmin([mask[y, 280:].sum() for y in range(rows[0] + 30, rows[-1] - 30)])) + 30
        mask[gap - 1:gap + 1, 400:404] = 255
        end = int(np.flatnonzero(mask[gap:rows[-1] + 1, :].any(axis=0))[-1]) + 1
        # The boxes end inside the last word, past a word gap.
        top, bottom = (296, rows[0] - 2, end - 30, gap + 6), (296, gap - 6, end - 30, rows[-1] + 2)
        repaired, _ = repair_lines(mask, small + [top, bottom])
        big = sorted((b for b, _ in repaired if b[1] > 140), key=lambda b: b[1])
        self.assertEqual(len(big), 2, big)
        self.assertGreaterEqual(big[1][2], end - 1)

    def test_one_big_line_is_not_a_staircase(self):
        # Grand Blue 102 p31: "...THIS" in letters twice the page line height was cut into
        # "THIS" and "..." as if it were two offset lines.
        mask, small, rows = self.big_lines()
        mask[230:, :] = 0  # only "STUFF"
        cv2.circle(mask, (292, 214), 5, 255, -1)  # a dot at the bottom left, like "..."
        line = np.flatnonzero(mask[150:, 280:].any(axis=1)) + 150
        box = (284, int(line[0]) - 2, 520, int(line[-1]) + 3)
        repaired, changes = repair_lines(mask, small + [box])
        self.assertNotIn("split", [kind for kind, _, _ in changes])

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

    def run_hook(self, mask, lines):
        import asyncio
        import types
        from types import SimpleNamespace
        from engine_compat import repair_textlines
        fake = types.ModuleType("manga_translator.utils")
        fake.Quadrilateral = self.Quad
        package = types.ModuleType("manga_translator")
        package.utils = fake
        async def detect(self, config, ctx):
            return lines, mask, mask
        ctx = SimpleNamespace(img_rgb=np.zeros(mask.shape + (3,), np.uint8))
        saved = {k: sys.modules.get(k) for k in ("manga_translator", "manga_translator.utils")}
        sys.modules.update({"manga_translator": package, "manga_translator.utils": fake})
        try:
            return asyncio.run(repair_textlines(detect)(None, None, ctx))[0]
        finally:
            for key, value in saved.items():
                if value is None:
                    sys.modules.pop(key, None)
                else:
                    sys.modules[key] = value

    class Quad:
        def __init__(self, pts, text, prob, direction="h"):
            self.pts, self.text, self.prob, self.direction = np.asarray(pts), text, prob, direction

    def test_square_vertical_box_of_short_lines_is_split(self):
        # Grand Blue 106 p22: "CON- / DOMS / ?!" in a narrow bubble came as one box a little
        # taller than wide, called vertical; it never reached the line repair and was misread.
        mask = np.zeros((320, 300), np.uint8)
        lines = [self.Quad(quad(20, 20, 280, 40), "", 0.9), self.Quad(quad(20, 280, 280, 300), "", 0.9)]
        rows = []
        for i, text in enumerate(["CON-", "DOMS", "?!"]):
            (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
            x, y = 150 - w // 2, 120 + i * 34
            cv2.putText(mask, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 255, 2)
            rows.append((x, y - h, x + w, y))
        x0, x1 = min(r[0] for r in rows) - 2, max(r[2] for r in rows) + 2
        box = self.Quad(quad(x0, rows[0][1] - 4, x1, rows[-1][3] + 4), "", 0.9, "v")
        result = self.run_hook(mask, lines + [box])
        self.assertNotIn(box, result)
        self.assertEqual(len(result), 5)
        # A column of single letters (a vertical sound effect) comes back as it was.
        column = np.zeros((320, 300), np.uint8)
        for i, letter in enumerate("BOOM"):
            cv2.putText(column, letter, (140, 90 + i * 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 255, 3)
        sound = self.Quad(quad(130, 55, 185, 255), "", 0.9, "v")
        result = self.run_hook(column, lines + [sound])
        self.assertIn(sound, result)

    def test_square_vertical_box_never_takes_the_lines_of_its_neighbour(self):
        # One Piece 1161 p4: a "vertical" box over "...TO / FIND" beside a box over "FIND / US A /
        # BOAT!".  Checked together, it hid "FIND" from its neighbour's split and the speech came
        # out as "US A BOAT!".  When it does not split, the lines around it are the same as without it.
        mask = np.zeros((360, 300), np.uint8)
        lines = [self.Quad(quad(20, 20, 280, 40), "", 0.9), self.Quad(quad(20, 320, 280, 340), "", 0.9)]
        rows = []
        for i, text in enumerate(["...TO", "FIND", "US A", "BOAT!"]):
            (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
            x, y = 150 - w // 2, 120 + i * 30
            cv2.putText(mask, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, 255, 2)
            rows.append((x, y - h, x + w, y))
        x0, x1 = min(r[0] for r in rows) - 6, max(r[2] for r in rows) + 6
        below = self.Quad(quad(x0, rows[1][1] + 5, x1, rows[3][3] + 4), "", 0.9)
        above = self.Quad(quad(x0 + 4, rows[0][1] - 6, x1 - 4, rows[1][3] + 6), "", 0.9, "v")
        def boxes(result):
            return sorted(tuple(int(v) for v in np.asarray(q.pts).min(axis=0)) + tuple(int(v) for v in np.asarray(q.pts).max(axis=0))
                          for q in result if q is not above)
        without = boxes(self.run_hook(mask, lines + [below]))
        self.assertEqual(boxes(self.run_hook(mask, lines + [below, above])), without)


class LostLineTest(unittest.TestCase):
    """Lines of a speech that fell out of its region (triagem op1161, group 2)."""

    def test_dropped_box_over_the_line_above_is_trimmed_and_read_again(self):
        # One Piece 1161 p8: the box of "HIM?!" also covered the bottom of "TO FIGHT" and a vein.
        kept = [(77, 576, 135, 596), (66, 598, 147, 617), (67, 615, 145, 643)]
        lost = (47, 632, 135, 669)
        self.assertEqual(quality.near_lines([lost], kept), [])                    # too tall as it was
        trimmed = quality.trim_lost(lost, kept)
        self.assertEqual(trimmed, (47, 643, 135, 669))
        self.assertEqual(quality.near_lines([trimmed], kept), [0])
        # A line beside the paragraph, not under it, keeps its box.
        self.assertEqual(quality.trim_lost((300, 600, 380, 640), kept), (300, 600, 380, 640))

    def test_two_boxes_of_the_same_line_become_one(self):
        # One Piece 1161 p4: a small box inside a large one both fit "PIRATES": read twice.
        mask = np.zeros((300, 400), np.uint8)
        cv2.putText(mask, "PIRATES", (120, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 255, 2)
        (w, h), _ = cv2.getTextSize("PIRATES", cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
        lines = [(20, 20, 380, 44), (20, 240, 380, 264)]
        full, inner = (118, 120 - h - 3, 122 + w, 124), (180, 120 - h, 230, 122)
        repaired, _ = repair_lines(mask, lines + [full, inner])
        boxes = [b for b, _ in repaired if b[1] > 60 and b[3] < 200]
        self.assertEqual(len(boxes), 1, repaired)
        # Two different lines close together stay two.
        cv2.putText(mask, "AHOY", (150, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 255, 2)
        (w2, h2), _ = cv2.getTextSize("AHOY", cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
        repaired, _ = repair_lines(mask, lines + [full, (148, 160 - h2 - 3, 152 + w2, 164)])
        self.assertEqual(len([b for b, _ in repaired if b[1] > 60 and b[3] < 200]), 2)

    def test_two_boxes_of_the_same_line_keep_the_whole_line(self):
        # Grand Blue 102 p4: the box kept was the shorter one, and the title came out as "Mayuts".
        mask = np.zeros((300, 400), np.uint8)
        cv2.putText(mask, "CHURCH", (100, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 255, 2)
        (w, h), _ = cv2.getTextSize("CHURCH", cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
        lines = [(20, 20, 380, 44), (20, 240, 380, 264)]
        short, full = (100, 120 - h - 2, 100 + w - 12, 123), (98, 120 - h - 3, 102 + w, 124)
        for order in ([short, full], [full, short]):
            repaired, changes = repair_lines(mask, lines + order)
            # Every change lists its boxes after the repair (the diagnostics draw each one).
            self.assertTrue(all(len(b) == 4 for _, _, after in changes for b in after), changes)
            boxes = [b for b, _ in repaired if 60 < b[1] < 200]
            self.assertEqual(len(boxes), 1, repaired)
            self.assertGreaterEqual(boxes[0][2], 100 + w - 2, boxes)      # the end of the word is in

    def test_punctuation_beside_the_word_on_its_row_is_its_end(self):
        # "WHAT" and "?!" in two boxes on one row: the engine used to join them.
        self.assertEqual(quality.punctuation_owners([(100, 50, 160, 70), (164, 50, 180, 70)], ["WHAT", "?!"]), {1: 0})
        # Far along the row it is not.
        self.assertEqual(quality.punctuation_owners([(100, 50, 160, 70), (260, 50, 276, 70)], ["WHAT", "?!"]), {})
        # Right before a word on its row, it is not that word's end.
        self.assertEqual(quality.punctuation_owners([(100, 50, 160, 70), (82, 50, 96, 70)], ["WHAT", "!!"]), {})

    def test_one_glyph_marks_are_plain_punctuation_before_translation(self):
        from types import SimpleNamespace
        from engine_compat import fix_ocr
        regions = [SimpleNamespace(text="DAD ⁈"), SimpleNamespace(text="WAIT‼ WHAT⁉ HUH⁇")]
        fix_ocr(regions)
        self.assertEqual([r.text for r in regions], ["DAD ?!", "WAIT!! WHAT!? HUH??"])

    def test_punctuation_line_ends_the_speech_above_it(self):
        # One Piece 1161 p5: "URGH" over a taller "...!!": dropped as text with no letters.
        boxes = [(322, 464, 385, 492), (323, 484, 384, 527), (500, 100, 600, 130)]
        texts = ["URGH", "...!", "HELLO"]
        self.assertEqual(quality.punctuation_owners(boxes, texts), {1: 0})
        # Punctuation far from any speech, or a line with letters, joins nothing.
        self.assertEqual(quality.punctuation_owners([(10, 10, 60, 40), (300, 600, 350, 640)], ["HEY", "!!"]), {})
        self.assertEqual(quality.punctuation_owners(boxes[:1] + [(323, 494, 384, 520)], ["URGH", "OH!"]), {})
        # "WHAT" over a lone "⁈" (One Piece 1161 p7) is punctuation too.
        self.assertEqual(quality.punctuation_owners([(612, 31, 662, 50), (628, 55, 646, 73)], ["WHAT", "⁈"]), {1: 0})


    def test_punctuation_joins_only_a_kept_speech_after_the_art_decision(self):
        from functools import cached_property
        from types import SimpleNamespace
        from engine_compat import end_punctuation, set_aside_punctuation

        class Block:
            def __init__(self, box, text):
                x0, y0, x1, y1 = box
                self.lines = np.array([[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]], np.int32)
                self.text, self.texts = text, [text]

            @cached_property
            def xyxy(self):
                return np.array([self.lines[..., 0].min(), self.lines[..., 1].min(),
                                 self.lines[..., 0].max(), self.lines[..., 1].max()])

        def line(box, text):
            x0, y0, x1, y1 = box
            return SimpleNamespace(pts=np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]), text=text, direction="h")
        word, dots = line((322, 464, 385, 492), "URGH"), line((323, 484, 384, 527), "...!")
        ctx = SimpleNamespace(textlines=[word, dots])
        set_aside_punctuation(ctx)
        self.assertEqual(ctx.textlines, [word])                    # the engine never sees the dots
        speech = Block((322, 464, 385, 492), "URGH")
        speech.xyxy
        end_punctuation(ctx, [speech])
        self.assertEqual(speech.text, "URGH ...!")
        self.assertEqual(len(speech.lines), 2)                     # one box per line
        self.assertEqual(int(speech.xyxy[3]), 527)                 # the cached box was refreshed
        # With no kept speech near it (the word went to the art), nothing is joined.
        ctx = SimpleNamespace(textlines=[word, dots])
        set_aside_punctuation(ctx)
        far = Block((600, 100, 700, 130), "HELLO")
        end_punctuation(ctx, [far])
        self.assertEqual(far.text, "HELLO")
        # Its owner went to the art (a sound effect): the line is not given to the next speech.
        ctx = SimpleNamespace(textlines=[word, dots])
        set_aside_punctuation(ctx)
        sound, other = Block((322, 464, 385, 492), "URGH"), Block((320, 532, 390, 552), "HEY THERE")
        ctx.mangalate_preserved = [sound]
        end_punctuation(ctx, [other])
        self.assertEqual(other.text, "HEY THERE")
        # A "!!!" well below the last line of a long speech (One Piece 1161 p16, the end of a sound
        # effect) is measured from that line, not from the whole block: nothing is joined.
        long = Block((80, 740, 230, 760), "NOW TAKE")
        long.lines = np.concatenate([long.lines] + [long.lines + [0, 24 * k] for k in range(1, 4)])
        long.__dict__.pop("xyxy", None)
        ctx = SimpleNamespace(textlines=[line((83, 912, 135, 949), "!!!")])
        set_aside_punctuation(ctx)
        end_punctuation(ctx, [long])
        self.assertEqual(long.text, "NOW TAKE")


class OcrRescueTest(unittest.TestCase):
    """A line dropped by the OCR threshold inside a paragraph is read again (TBATE 236 p6)."""

    class Line:
        def __init__(self, box, text=""):
            self.pts, self.text, self.prob, self.direction = np.asarray(quad(*box)), text, 0.0, "h"

    def run_ocr(self, lines, dropped, reading="MUSTVE MAL-"):
        import asyncio
        import types
        from types import SimpleNamespace
        from engine_compat import rescue_ocr, RESCUE_PROB
        seen = {}
        async def dispatch(name, image, textlines, config, device, verbose):
            seen["prob"], seen["count"] = config.prob, len(textlines)
            for line in textlines:
                line.text, line.prob = reading, 0.08
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

    def test_drawn_symbol_read_as_one_letter_repeated_is_not_rescued(self):
        # One Piece 1161 p16: an anger vein and a broken heart under the last line of a
        # bubble were read again as "JJJJ", erased, and "Jjjj" was written at the end of the speech.
        lines = [self.Line((100, 40 + i * 34, 300, 68 + i * 34)) for i in range(4)]
        result, seen, ctx = self.run_ocr(lines, [lines[3]], reading="JJJJ")
        self.assertEqual(seen["count"], 1)
        self.assertEqual(len(result), 3)
        self.assertEqual(ctx.mangalate_ocr_rescued, [])
        self.assertEqual(ctx.mangalate_drawn, [[100, 142, 300, 170]])  # left out of the cleaning mask
        # A drawn-out cry still has two letters: it is speech and is read again.
        result, _, ctx = self.run_ocr(lines, [lines[3]], reading="WAAAH!!")
        self.assertEqual(len(result), 4)
        self.assertEqual(ctx.mangalate_drawn, [])
        # So is one vowel drawn out, the end of a cry split in two lines ("GYAA- / AAA!!!").
        result, _, ctx = self.run_ocr(lines, [lines[3]], reading="AAA!!!")
        self.assertEqual(len(result), 4)
        self.assertEqual(ctx.mangalate_drawn, [])

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

    def test_drawing_read_as_one_letter_repeated_stays_whole(self):
        # One Piece 1161 p16: an anger vein under the last line was read as "JJJJ".  Its own
        # box gives back only the drawing; the letters of the line above are not touched.
        image = self.page()
        vein = np.zeros(image.shape[:2], np.uint8)
        for dx in (0, 14):
            cv2.ellipse(vein, (230 + dx, 252), (6, 10), 0, 90, 270, 255, 3)
            cv2.ellipse(vein, (230 + dx + 28, 252), (6, 10), 0, -90, 90, 255, 3)
        image[vein > 0] = (10, 10, 10)
        keep = quality.drawn_marks(image, [(218, 240, 284, 264)])
        self.assertTrue(keep[vein > 0].all())
        self.assertFalse(keep[200:232, :].any())       # the line "OF US." just above
        self.assertFalse(quality.drawn_marks(image, []).any())

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

    def dotted(self):
        # A line ending in "..." whose last dots sit just past the box, and a row of dots under it.
        image = self.page()
        image[100:300, 120:400] = 250
        cv2.putText(image, "THE WORD", (150, 170), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (10, 10, 10), 3)
        dots = [(318, 166), (330, 166), (342, 166), (200, 200), (212, 200), (224, 200)]
        for x, y in dots:
            cv2.circle(image, (x, y), 3, (10, 10, 10), -1)
        return image, (148, 146, 322, 172), dots

    def test_letters_cut_by_the_box_are_cleaned_whole(self):
        # Grand Blue 102 p42/p20: the last dot of "...", or a row of dots under the word,
        # was cleaned only up to the box margin and left a grey half dot.
        image, box, dots = self.dotted()
        clean = glyphs_to_clean(image, box, 26)
        for x, y in dots:
            self.assertTrue(clean[y - 3:y + 4, x - 3:x + 4].all(), (x, y))
        self.assertFalse(clean[:, :60].any())          # the bubble outline stays

    def test_word_past_the_box_is_not_cleaned(self):
        # A word the box left out (printed text running on past what was read) was not
        # translated: erasing it would lose it.  Only the dots of punctuation follow the line.
        image = self.page()
        image[100:300, 120:400] = 250
        cv2.putText(image, "THE", (150, 170), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (10, 10, 10), 3)
        cols = np.flatnonzero((image[140:175, 120:400, 0] < 128).any(axis=0)) + 120
        end = int(cols[-1]) + 1
        cv2.putText(image, "IT", (end + 2, 170), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (10, 10, 10), 3)
        clean = glyphs_to_clean(image, (148, 146, end, 172), 26)
        self.assertFalse(clean[150:172, end + 6:end + 8].all(axis=1).any())  # only the margin touches the "I"
        self.assertFalse(clean[150:172, end + 18:end + 28].any())            # the next letter stays

    def test_small_letters_of_the_line_below_are_not_dots(self):
        # A line in lower case under the box that was not read: its small letters are not punctuation.
        image = self.page()
        image[100:300, 120:400] = 250
        cv2.putText(image, "THE WORD", (150, 170), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (10, 10, 10), 3)
        cv2.putText(image, "one more line", (160, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (10, 10, 10), 2)
        clean = glyphs_to_clean(image, (148, 146, 322, 172), 26)
        self.assertFalse(clean[186:202, 150:330].any())

    def test_cleaning_stays_off_the_outline(self):
        image, _, _ = self.dotted()
        cv2.putText(image, "EDGE", (60, 210), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (10, 10, 10), 3)  # touches the outline
        clean = glyphs_to_clean(image, (148, 146, 322, 172), 26)
        self.assertFalse(clean[190:215, 40:58].any())


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


class PortugueseCheckTest(unittest.TestCase):
    """op1153-6a: Spanish words, a superlative with the wrong gender and a doubled word."""

    def test_spanish_words_ask_again(self):
        notes = quality.translation_problems(["THANKS TO YOUR HELP, WE MADE IT."], ["Gracias à sua ajuda, conseguimos."])
        self.assertTrue(any("Spanish" in n and "Gracias" in n for n in notes))
        notes = quality.translation_problems(["IT IS VERY GOOD, SIR."], ["Está muy bom, senhor."])
        self.assertTrue(any("Spanish" in n for n in notes))
        notes = quality.translation_problems(["SHE GREW STRONGER."], ["Ela se desenvolvió mais forte."])
        self.assertTrue(any("Spanish" in n for n in notes))
        # A name from the source and plain Portuguese never trigger it.
        for source, text in (("REINA, WAIT!", "Reina, espera!"), ("THANK YOU!", "Obrigado!"),
                             ("ASK MUNOZ.", "Pergunta pro Muñoz."), ("MUÑOZ, WAIT!", "Muñoz, espera!"),
                             ("I'LL DO IT NOW", "Vou fazer agora."), ("WHERE?", "Onde?")):
            self.assertFalse(any("Spanish" in n for n in quality.translation_problems([source], [text])), text)

    def test_superlative_keeps_the_gender_of_de_todos(self):
        notes = quality.translation_problems(["THE SADDEST OF ALL THE BIRDS"],
                                             ["O mais triste de todas as aves"])
        self.assertTrue(any("gender" in n for n in notes))
        # A woman in a mixed group is "a mais forte de todos": only "o ... de todas" is flagged.
        for text in ("A mais triste de todas as aves", "O mais forte de todos!",
                     "Ela é a mais rápida de todas.", "Ela é a mais forte de todos nós."):
            self.assertFalse(any("gender" in n for n in quality.translation_problems(["X"], [text])), text)

    def test_doubled_word_asks_again(self):
        notes = quality.translation_problems(["WHY ARE YOU SO QUIET?"],
                                             ["Por que você tá tá tão quieto?"])
        self.assertTrue(any("tá tá" in n for n in notes))
        notes = quality.translation_problems(["BACK SOON. WHY SO QUIET?"], ["Já já volto. Por que tão tão quieto?"])
        self.assertTrue(any("tão tão" in n for n in notes))
        # Laughs, stutters and repetitions the original also has stay.
        for source, text in (("HA HA HA!", "Ha ha ha!"), ("C-CONGRATULATIONS!", "P-parabéns!"),
                             ("NO, NO, NO!", "Não, não, não!"), ("RUN, RUN!", "Corre, corre!"),
                             ("BZZZT BZT", "Bzzz bzzz"), ("HAHAHA!", "Ha ha ha!"), ("BYE-BYE!", "Tchau tchau!"),
                             ("SOON.", "Já já."), ("WHAT IS THIS?", "O que que é isso?"),
                             ("UH-OH.", "Oh oh.")):
            self.assertFalse(any("twice" in n for n in quality.translation_problems([source], [text])), text)

    def test_answer_equal_to_the_source_reads_the_same_only_without_english(self):
        # op1161 p16 and Grand Blue 106 p23: the AI answered an interjection, a scream and the
        # OCR of a vertical phone buzz unchanged; the engine dropped all three as untranslated.
        for source in ("OH..", "HMMM...", "AAAH!!", "GUHA- AAA!!!", "HAHAHA!", "BZZZT", "ZORVAN!!"):
            self.assertEqual(quality.unchanged_english(source), [], source)
        for source, words in (("YEAAAH!!!", ["YEAAAH"]), ("NOOO!", ["NOOO"]), ("WAIT!", ["WAIT"]),
                              ("Z 6ZZZ U Z BZZZ", ["Z", "6ZZZ", "U", "Z"]), ("I...", ["I"]), ("HE...", ["HE"])):
            self.assertEqual(quality.unchanged_english(source), words, source)
        # A name of the page or of the glossary is no English, even when it is also a word,
        # and a plain double letter is no held one ("VELLVET" is not "velvet").
        self.assertEqual(quality.unchanged_english("MAX!!!", {"Max"}), [])
        self.assertEqual(quality.unchanged_english("IRON PEAKS!", {"Iron Peaks"}), [])
        self.assertEqual(quality.unchanged_english("SHAGGY", ()), ["SHAGGY"])
        self.assertEqual(quality.unchanged_english("VELLVET!"), [])

    def test_unchanged_answer_with_english_asks_again(self):
        notes = quality.translation_problems(["Z 6ZZZ BZZZ", "WAIT FOR ME!"], ["Z 6ZZZ BZZZ", "Me espera!"])
        self.assertEqual(len(notes), 1)
        self.assertTrue(notes[0].startswith("<|1|>") and "unchanged" in notes[0])
        # What already reads the same in Portuguese costs no second request.
        for source, text in (("OH..", "Oh.."), ("GUHA- AAA!!!", "GUHA- AAA!!!"), ("ZORVAN!!", "Zorvan!!")):
            self.assertFalse(any("unchanged" in n for n in quality.translation_problems([source], [text])), text)
        notes = quality.translation_problems(["OH, MAX!!!", "MAX!!!"], ["Ah, Max!!!", "Max!!!"])
        self.assertFalse(any("unchanged" in n for n in notes))
        notes = quality.translation_problems(["MAX!"], ["Max!"], [{"source": "MAX", "target": "Max"}])
        self.assertFalse(any("unchanged" in n for n in notes))

    def test_lone_letter_answer_never_wins_the_second_try(self):
        # Grand Blue 106 p23: the vertical buzz came back as a lone "V", lettered big in the box.
        self.assertTrue(any("is a lone letter" in n for n in quality.translation_problems(["Z 6ZZZ BZZZ"], ["Z"])))
        for source, text in (("A...", "A..."), ("AND?", "E?"), ("OH!", "Ó!"), ("OOOH!", "Ô!"), ("Z!", "Z!")):
            self.assertFalse(any("is a lone letter" in n for n in quality.translation_problems([source], [text])), text)


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


class GrazedBubbleScanTest(unittest.TestCase):
    """Grand Blue 102 p20: "S... / SORRY / ..." in a bubble whose white leaks out of a gap in
    the outline and only grazes the line boxes of the bubble next to it."""

    NEIGHBOUR = (306, 100, 400, 130)

    def page(self, mark=True):
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (900, 1200), (120, 120, 120))
        d = ImageDraw.Draw(img)
        d.ellipse((100, 100, 260, 460), fill="white", outline="black", width=4)
        d.rectangle((215, 70, 300, 140), fill="white")  # the gap in the outline, open to a light patch
        font = LeakingBubbleScanTest.font(26)
        d.text((200, 150), "S", fill="black", font=font)  # stutter letter on its own, near the gap
        w = d.textlength("SORRY", font=font)
        d.text((180 - w / 2, 270), "SORRY", fill="black", font=font)
        d.text((165, 290), "...", fill="black", font=font)
        if mark:  # a stroke of the art inside the white
            d.line((235, 360, 238, 395), fill="black", width=3)
        return np.array(img)

    def test_bubble_that_only_grazes_a_neighbour_box_is_found(self):
        found = quality.bubble_text_lines(self.page(), [self.NEIGHBOUR])
        self.assertEqual(len(found), 1)
        _, rows, letters = found[0]
        self.assertEqual(len(rows), 2, rows)  # the word, then its dots: two rows of lettering
        (x0, y0, x1, y1), dots = rows
        self.assertTrue(130 < x0 < x1 < 230 and 270 < y0 < y1 < 305, rows)
        self.assertTrue(y1 <= dots[1] and x0 <= dots[0] < dots[2] <= x1, rows)
        self.assertTrue(letters[dots[1]:dots[3], dots[0]:dots[2]].any())  # the dots are cleaned too
        self.assertFalse(letters[355:400, 228:245].any())  # the art stroke stays

    def test_box_reaching_into_the_bubble_still_means_seen(self):
        self.assertEqual(quality.bubble_text_lines(self.page(), [(240, 90, 330, 130)]), [])


class TextBlockTest(unittest.TestCase):
    """Grand Blue 102 p3: a paragraph on the page beside a bubble's paragraph; the detector drew
    boxes across both ("I JUST  AS HE") and the two speeches were read and translated as one."""

    @staticmethod
    def lines(mask, texts, x, y, step=24, centre=False):
        boxes = []
        for i, text in enumerate(texts):
            (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
            left = x - w // 2 if centre else x
            cv2.putText(mask, text, (left, y + i * step), cv2.FONT_HERSHEY_SIMPLEX, 0.7, 255, 2)
            boxes.append((left - 1, y + i * step - h - 1, left + w + 1, y + i * step + 5))
        return boxes

    def page(self):
        mask = np.zeros((400, 520), np.uint8)
        # The last line of the page's paragraph runs under the bubble's: no straight gutter between them.
        left = self.lines(mask, ["I JUST", "KNOW IT", "COME BACK", "TO BITE", "IF WE GO AWAY"], 40, 140)
        right = self.lines(mask, ["LETS", "JUST DO", "AS HE", "SAYS."], 230, 92, centre=True)
        # The detector's boxes over the two rows the paragraphs share.
        merged = [(left[0][0], min(left[0][1], right[2][1]), right[2][2], max(left[0][3], right[2][3])),
                  (left[1][0], min(left[1][1], right[3][1]), right[3][2], max(left[1][3], right[3][3]))]
        return mask, left, right, [right[0], right[1]] + merged + left[2:]

    def test_box_across_two_paragraphs_is_cut(self):
        mask, left, right, boxes = self.page()
        cuts = quality.block_cuts(mask, boxes)
        self.assertEqual(sorted(cuts), [2, 3], cuts)
        for i, (l, r) in zip((2, 3), ((left[0], right[2]), (left[1], right[3]))):
            (a0, a1), (b0, b1) = cuts[i]
            self.assertTrue(abs(a0 - l[0]) <= 4 and abs(a1 - l[2]) <= 4 and abs(b0 - r[0]) <= 4 and abs(b1 - r[2]) <= 4,
                            (cuts[i], l, r))

    def test_lines_are_grouped_by_paragraph(self):
        mask, left, right, _ = self.page()
        groups = quality.block_groups(mask, left + right)
        self.assertEqual(sorted(sorted(g) for g in groups), [[0, 1, 2, 3, 4], [5, 6, 7, 8]])

    def test_wide_gap_in_one_paragraph_is_not_cut(self):
        # Spaced-out words in one bubble ("WAIT    WHAT"): one speech.
        mask = np.zeros((300, 520), np.uint8)
        boxes = self.lines(mask, ["HOLD ON,", "WAIT", "THIS IS", "TOO MUCH"], 200, 80, centre=True)
        (w, h), _ = cv2.getTextSize("WAIT", cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        cv2.putText(mask, "WHAT", (boxes[1][2] + 30, 104), cv2.FONT_HERSHEY_SIMPLEX, 0.7, 255, 2)
        boxes[1] = (boxes[1][0], boxes[1][1], boxes[1][2] + 32 + w, boxes[1][3])
        self.assertEqual(quality.block_cuts(mask, boxes), {})
        self.assertEqual(len(quality.block_groups(mask, boxes)), 1)

    def test_lone_line_beside_a_paragraph_is_not_cut(self):
        # One short line next to a paragraph (a name tag, a stray word): never split off on its own.
        mask = np.zeros((300, 520), np.uint8)
        boxes = self.lines(mask, ["THIS IS", "ONE SPEECH", "HERE."], 230, 80, centre=True)
        cv2.putText(mask, "OH", (60, 104), cv2.FONT_HERSHEY_SIMPLEX, 0.7, 255, 2)
        boxes[1] = (58, boxes[1][1], boxes[1][2], boxes[1][3])
        self.assertEqual(quality.block_cuts(mask, boxes), {})


class TextBlockRegionTest(unittest.TestCase):
    """The region the merge built over both paragraphs is split, and stays split, even in an open bubble."""

    class Block:
        def __init__(self, lines, texts, font_size=20, angle=0, prob=1.0, fg_color=None, bg_color=None):
            self.lines, self.texts = np.asarray(lines), list(texts)
            self.font_size, self.angle, self.prob = font_size, angle, prob
            self.fg_colors, self.bg_colors, self.horizontal = fg_color, bg_color, True
            pts = self.lines.reshape(-1, 2)
            self.xyxy = (*pts.min(axis=0), *pts.max(axis=0))

    def test_two_paragraphs_in_one_region_are_split(self):
        from engine_compat import join_split_blocks
        mask, left, right, _ = TextBlockTest().page()
        boxes = sorted(left + right, key=lambda b: b[1])
        texts = [f"L{i}" if b in left else f"R{i}" for i, b in enumerate(boxes)]
        block = self.Block([quad(*b) for b in boxes], texts)
        page = np.full((400, 520, 3), 255, np.uint8)  # one white page: the bubble is open to it
        out = join_split_blocks([block], page, mask)
        self.assertEqual(sorted(sorted(t[0] for t in b.texts) for b in out), [["L"] * 5, ["R"] * 4])
        self.assertEqual(len(join_split_blocks([block], page)), 1)  # without the mask: as before

    def test_pieces_of_one_paragraph_on_the_page_are_joined(self):
        # Grand Blue 102 p3: the text beside the bubble, written on the page (no bubble around it),
        # came out as "I JUST / KNOW IT'LL" and "COME BACK...", translated as two half sentences.
        from engine_compat import join_split_blocks
        mask, left, _, _ = TextBlockTest().page()
        mask[:, 200:] = 0
        page = noisy_art((520, 400))
        top = self.Block([quad(*b) for b in left[:2]], ["L0", "L1"])
        bottom = self.Block([quad(*b) for b in left[2:]], ["L2", "L3", "L4"])
        out = join_split_blocks([top, bottom], page, mask)
        self.assertEqual([b.texts for b in out], [["L0", "L1", "L2", "L3", "L4"]])
        self.assertEqual(len(join_split_blocks([top, bottom], page)), 2)  # without the mask: as before

    def test_pieces_of_one_paragraph_on_open_flat_page_are_joined(self):
        # Grand Blue 102 p3: the top piece sat on a flat, open gutter; the bubble search came back
        # with the piece's own box as if it were a bubble, so the rest of the paragraph stayed apart.
        from engine_compat import join_split_blocks
        mask, left, _, _ = TextBlockTest().page()
        mask[:, 200:] = 0
        page = np.full((400, 520, 3), 255, np.uint8)
        top = self.Block([quad(*b) for b in left[:2]], ["L0", "L1"])
        bottom = self.Block([quad(*b) for b in left[2:]], ["L2", "L3", "L4"])
        out = join_split_blocks([top, bottom], page, mask)
        self.assertEqual([b.texts for b in out], [["L0", "L1", "L2", "L3", "L4"]])

    def test_piece_in_a_closed_bubble_stays_apart_from_the_paragraph_outside(self):
        # The neighbour: a real bubble around the top piece still keeps the text below it apart.
        from engine_compat import join_split_blocks
        mask, left, _, _ = TextBlockTest().page()
        mask[:, 200:] = 0
        page = noisy_art((520, 400))
        cv2.ellipse(page, (90, 147), (85, 36), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(page, (90, 147), (85, 36), 0, 0, 360, (0, 0, 0), 3)
        top = self.Block([quad(*b) for b in left[:2]], ["L0", "L1"])
        bottom = self.Block([quad(*b) for b in left[2:]], ["L2", "L3", "L4"])
        self.assertEqual(len(join_split_blocks([top, bottom], page, mask)), 2)

    def test_pieces_in_a_tight_caption_box_stay_joined(self):
        # A narration box drawn close around its text: the bubble barely exceeds the lines, still one speech.
        from engine_compat import join_split_blocks
        mask, left, _, _ = TextBlockTest().page()
        mask[:, 200:] = 0
        page = noisy_art((520, 400))
        x0, y0 = min(b[0] for b in left) - 6, min(b[1] for b in left) - 6
        x1, y1 = max(b[2] for b in left) + 6, max(b[3] for b in left) + 6
        cv2.rectangle(page, (x0, y0), (x1, y1), (255, 255, 255), -1)
        cv2.rectangle(page, (x0, y0), (x1, y1), (0, 0, 0), 3)
        top = self.Block([quad(*b) for b in left[:2]], ["L0", "L1"])
        bottom = self.Block([quad(*b) for b in left[2:]], ["L2", "L3", "L4"])
        out = join_split_blocks([top, bottom], page, mask)
        self.assertEqual([b.texts for b in out], [["L0", "L1", "L2", "L3", "L4"]])
        self.assertEqual(len(join_split_blocks([top, bottom], page)), 1)  # the box alone joins them, as before

    def test_two_paragraphs_on_the_page_stay_apart(self):
        from engine_compat import join_split_blocks
        mask = np.zeros((400, 520), np.uint8)
        upper = TextBlockTest.lines(mask, ["ONE TEXT", "UP HERE"], 40, 100)
        lower = TextBlockTest.lines(mask, ["ANOTHER", "DOWN HERE"], 40, 178)  # a blank line and a half below
        a = self.Block([quad(*b) for b in upper], ["U0", "U1"])
        b = self.Block([quad(*b) for b in lower], ["D0", "D1"])
        self.assertEqual(len(join_split_blocks([a, b], noisy_art((520, 400)), mask)), 2)

    def test_one_paragraph_stays_one_region(self):
        from engine_compat import join_split_blocks
        mask, left, _, _ = TextBlockTest().page()
        mask[:, 200:] = 0
        block = self.Block([quad(*b) for b in left], [f"L{i}" for i in range(len(left))])
        out = join_split_blocks([block], np.full((400, 520, 3), 255, np.uint8), mask)
        self.assertEqual(len(out), 1)


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

    def narrow_gutter(self, left_rows, right_rows):
        """Two columns 10 px apart; the first row's box runs across both, as the detector drew it."""
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (420, 260), "white")
        d = ImageDraw.Draw(img)
        font = ImageFont.truetype(str(Path(__file__).resolve().parents[1] / "fonts" / "ComicNeue-Bold.ttf"), 20)
        boxes = []
        for words, x_right, rows in ((left_rows, True, None), (right_rows, False, None)):
            for i, (text, y) in enumerate(words):
                w = int(d.textlength(text, font=font))
                x = 200 - w if x_right else 210
                d.text((x, y), text, fill="black", font=font)
                boxes.append((x, y + 3, x + w, y + 23))
        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY), boxes

    def test_two_columns_with_a_narrow_gutter_are_cut(self):
        # Grand Blue 102 p33: "I'LL HAVE THE DRINKS..." in small letters beside "THERE'S BEEN A
        # LITTLE MIX-UP!"; a white outline closes the gutter to 9 px, and one box ran across both.
        left = [("DRINKS", 50), ("REPLACED", 80), ("RIGHT", 110)]
        right = [("BEEN A", 56), ("LITTLE", 86), ("MIX-UP!", 116)]
        gray, boxes = self.narrow_gutter(left, right)
        across = (min(boxes[0][0], boxes[3][0]), 20, max(boxes[0][2], boxes[3][2]), 44)
        from PIL import Image, ImageDraw, ImageFont
        img = Image.fromarray(gray)
        d = ImageDraw.Draw(img)
        font = ImageFont.truetype(str(Path(__file__).resolve().parents[1] / "fonts" / "ComicNeue-Bold.ttf"), 20)
        d.text((200 - int(d.textlength("HAVE THE", font=font)), 21), "HAVE THE", fill=0, font=font)
        d.text((210, 21), "THERE'S", fill=0, font=font)
        gray = np.array(img)
        cuts = quality.column_cuts(gray, [across] + boxes)
        self.assertIn(0, cuts)
        gx0, gx1 = cuts[0]
        self.assertTrue(200 <= gx1 and gx0 <= 210, cuts)

    def test_one_line_split_in_two_boxes_is_not_two_columns(self):
        # A speech whose middle line the detector boxed in two pieces: one pair side by side only.
        left = [("I KNOW", 50)]
        right = [("WHAT", 50)]
        gray, boxes = self.narrow_gutter(left, right)
        from PIL import Image, ImageDraw, ImageFont
        img = Image.fromarray(gray)
        d = ImageDraw.Draw(img)
        font = ImageFont.truetype(str(Path(__file__).resolve().parents[1] / "fonts" / "ComicNeue-Bold.ttf"), 20)
        for text, y in (("YOU MEAN, BUT", 20), ("IT IS TOO LATE", 80)):
            w = int(d.textlength(text, font=font))
            d.text((205 - w // 2, y), text, fill=0, font=font)
            boxes.append((205 - w // 2, y + 3, 205 - w // 2 + w, y + 23))
        self.assertEqual(quality.column_cuts(np.array(img), boxes), {})

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


class ThroughLineTest(unittest.TestCase):
    """Grand Blue 102 p3: text written on the page ran over the panel border and the outline of the
    bubble beside it; the cleaning erased both lines and the two panels ran into each other."""

    TEXTS = ["I JUST", "KNOW IT'LL", "COME BACK", "TO BITE US"]

    def page(self, border=True, outline=True, border_end=None):
        image = np.full((400, 300, 3), 255, np.uint8)
        art = np.zeros((400, 300), np.uint8)
        if border:
            cv2.line(art, (149, 0), (149, 399 if border_end is None else border_end), 255, 3)
        if outline:
            cv2.ellipse(art, (330, 200), (150, 260), 0, 0, 360, 255, 2)
        letters = np.zeros((400, 300), np.uint8)
        boxes = TextBlockTest.lines(letters, self.TEXTS, 100, 150)
        image[(art > 0) | (letters > 0)] = 0
        # The cleaning mask covers the letters and the bits of line between them, as the detector's does.
        mask = cv2.dilate(letters, np.ones((11, 11), np.uint8))
        box = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
        return image, mask, art > 0, letters > 0, box

    def test_border_through_the_text_is_found(self):
        image, mask, _, _, box = self.page()
        lines = quality.through_lines(image, mask, box, 18)
        self.assertEqual(len(lines), 1, lines)
        (xa, ya), (xb, yb), thick, grey = lines[0]
        self.assertTrue(abs(xa - 149) <= 1 and abs(xb - 149) <= 1, lines)
        rows = np.nonzero((mask > 0).any(axis=1))[0]
        self.assertTrue(min(ya, yb) <= rows.min() and max(ya, yb) >= rows.max(), (lines, rows.min(), rows.max()))
        self.assertTrue(4 <= thick <= 6 and grey < 60, lines)  # cv2 draws thickness 3 five pixels wide

    def test_border_is_drawn_back_beside_the_new_letters(self):
        image, mask, _, _, box = self.page()
        lines = quality.through_lines(image, mask, box, 18)
        clean = image.copy()
        clean[mask > 0] = 255
        rendered = clean.copy()
        cv2.putText(rendered, "NOVO", (120, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
        out = quality.redraw_lines(rendered, clean, mask, lines)
        changed = np.any(out != rendered, axis=2)
        self.assertTrue(changed[150:250, 147:152].mean() > 0.4)   # the border is back across the text
        self.assertFalse(changed[:, :140].any() or changed[:, 158:].any())
        letters = np.any(rendered != clean, axis=2)
        self.assertTrue(np.array_equal(out[letters], rendered[letters]))  # the new letters stay on top
        near = cv2.dilate(letters.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        self.assertFalse((changed & near).any())  # with a little paper around them, as around the original letters
        self.assertFalse((changed & (mask == 0)).any())  # only where the cleaning erased
        widths = [int(changed[y].sum()) for y in range(150, 250) if changed[y].any()]
        self.assertTrue(widths and max(widths) <= 5, widths)  # as wide as the border, not wider

    def test_each_line_keeps_its_own_grey(self):
        page = np.full((200, 200, 3), 255, np.uint8)
        clean, mask = page.copy(), np.full((200, 200), 255, np.uint8)
        lines = [((50, 10), (50, 190), 3, 0), ((150, 10), (150, 190), 3, 120)]
        out = quality.redraw_lines(page, clean, mask, lines)
        self.assertEqual((int(out[100, 50, 0]), int(out[100, 150, 0])), (0, 120))

    def test_parallel_hatching_across_the_text_is_not_rebuilt(self):
        # Hatching under the text: strokes on each side, but offset, never one line carried across.
        image, mask, _, _, box = self.page(border=False, outline=False)
        for x in range(60, 260, 12):
            cv2.line(image, (x, 60), (x, 134), (0, 0, 0), 1)
            cv2.line(image, (x + 5, 226), (x + 5, 300), (0, 0, 0), 1)
        image[mask > 0] = np.where(image[mask > 0] == 0, 0, 255)
        self.assertEqual(quality.through_lines(image, mask, box, 18), [])

    def test_text_without_lines_is_untouched(self):
        image, mask, _, _, box = self.page(border=False, outline=False)
        self.assertEqual(quality.through_lines(image, mask, box, 18), [])

    def test_curved_outline_is_not_rebuilt(self):
        # A curve is not rebuilt under the letters: a straight line would cut through them.
        image, mask, _, _, box = self.page(border=False)
        self.assertEqual(quality.through_lines(image, mask, box, 18), [])

    def test_stroke_ending_inside_the_text_is_not_rebuilt(self):
        # A line that stops among the letters may be part of them: nothing to draw back.
        image, mask, _, _, box = self.page(outline=False, border_end=175)
        self.assertEqual(quality.through_lines(image, mask, box, 18), [])
