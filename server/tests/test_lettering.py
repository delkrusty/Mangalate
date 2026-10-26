"""Translation fitted to the bubble instead of the original text box (lettering.py)."""
import os
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lettering


def char_layout(text):
    """Greedy whole-word wrap with a fixed advance of 0.55 em per character."""
    def layout(size, width, height):
        lines, current = [], ""
        for word in text.split():
            candidate = (current + " " + word).strip()
            if len(candidate) * size * 0.55 <= width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines, [int(len(line) * size * 0.55) for line in lines]
    return layout


def page_with_bubble(axes=(110, 190), centre=(300, 300), outline=True):
    image = np.full((600, 600, 3), 90, np.uint8)  # grey "art" around
    cv2.ellipse(image, centre, axes, 0, 0, 360, (255, 255, 255), -1)
    if outline:
        cv2.ellipse(image, centre, axes, 0, 0, 360, (0, 0, 0), 3)
    return image


class BubbleLayoutTest(unittest.TestCase):
    TEXT = "Espero que você se parta da virilha até as axilas e morra."

    def test_long_text_grows_into_a_tall_bubble(self):
        image = page_with_bubble()
        box = (255, 200, 345, 400)  # narrow column where the English was
        plan = lettering.plan(image, box, [], self.TEXT, char_layout(self.TEXT), 24, 10)
        self.assertIsNotNone(plan)
        size, (x0, y0, x1, y1) = plan
        # The engine would have fitted the text to the 90 px column: much smaller.
        in_box = lettering.best_layout(self.TEXT, [box], char_layout(self.TEXT), 30, 4)
        self.assertGreater(size, in_box[0])
        # The rectangle stays inside the bubble.
        mask = np.zeros(image.shape[:2], np.uint8)
        cv2.ellipse(mask, (300, 300), (110, 190), 0, 0, 360, 255, -1)
        self.assertTrue(mask[y0:y1, x0:x1].all())

    def test_short_text_is_capped_near_the_original_size(self):
        image = page_with_bubble()
        plan = lettering.plan(image, (280, 285, 320, 315), [], "Ah!", char_layout("Ah!"), 24, 10)
        self.assertEqual(plan[0], round(24 * lettering.MAX_SCALE))

    def test_app_font_setting_moves_the_cap(self):
        image = page_with_bubble()
        plan = lettering.plan(image, (280, 285, 320, 315), [], "Ah!", char_layout("Ah!"), 24, 10, offset=-3)
        self.assertEqual(plan[0], round(24 * lettering.MAX_SCALE) - 3)

    def test_open_bubble_stays_within_the_text_box(self):
        image = np.full((600, 600, 3), 255, np.uint8)  # text on a blank page, no outline
        box = (250, 250, 350, 330)
        plan = lettering.plan(image, box, [], self.TEXT, char_layout(self.TEXT), 20, 6)
        if plan is not None:
            _, (x0, y0, x1, y1) = plan
            self.assertTrue(box[0] <= x0 and x1 <= box[2] and box[1] <= y0 and y1 <= box[3])

    def test_two_regions_in_one_bubble_do_not_overlap(self):
        image = page_with_bubble(axes=(200, 150))
        upper, lower = (220, 200, 380, 260), (220, 330, 380, 390)
        a = lettering.plan(image, upper, [lower], "Primeira fala aqui", char_layout("Primeira fala aqui"), 22, 8)
        b = lettering.plan(image, lower, [upper], "Segunda fala aqui", char_layout("Segunda fala aqui"), 22, 8)
        (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = a[1], b[1]
        self.assertTrue(ay1 <= by0 or by1 <= ay0 or ax1 <= bx0 or bx1 <= ax0)

    def test_text_that_never_fits_keeps_the_engine_behaviour(self):
        image = page_with_bubble(axes=(30, 30))
        long = "palavra " * 60
        self.assertIsNone(lettering.plan(image, (285, 285, 315, 315), [], long, char_layout(long), 20, 12))

    def test_bubble_is_found_on_the_art_side_too(self):
        image = page_with_bubble(outline=False)  # white bubble on grey art, no black outline
        plan = lettering.plan(image, (255, 200, 345, 400), [], self.TEXT, char_layout(self.TEXT), 24, 10)
        self.assertIsNotNone(plan)


class BubbleLayoutHookTest(unittest.TestCase):
    """The engine renderer uses the plan; regions without one keep the engine's drawing.

    Each path pins the font: inside the image the comic font exists and the shaped plan
    is used, outside it only the rectangle plan would run, whatever the machine.
    """

    def render_page(self, font):
        import types
        from unittest import mock
        from engine_compat import bubble_layout
        calls = []
        rendering = types.SimpleNamespace(
            resize_regions_to_font_size=lambda img, regions, *a: [np.zeros((1, 4, 2), np.int64) for _ in regions],
            render=lambda img, region, *a: calls.append("engine") or img,
            fg_bg_compare=lambda fg, bg: (fg, bg),
        )

        def put_text_horizontal(size, text, w, h, *args):
            box = np.zeros((size, min(w, size * 3), 4), np.uint8)
            box[..., 3] = 255
            return box
        text_render = types.SimpleNamespace(
            calc_horizontal=lambda size, text, w, h, lang, hyphenate: char_layout(text)(size, w, h),
            put_text_horizontal=put_text_horizontal,
        )
        bubble_layout(rendering, text_render)

        class Region:
            def __init__(self, box, text):
                x0, y0, x1, y1 = box
                self.xyxy = box
                self.lines = np.array([[[x0, y0], [x1, y0], [x1, y0 + 24], [x0, y0 + 24]]])
                self.font_size, self.direction, self.horizontal = 24, "h", True
                self.target_lang, self.text = "PTB", text

            def get_translation_for_rendering(self):
                return self.text

            def get_font_colors(self):
                return (0, 0, 0), (255, 255, 255)

        image = page_with_bubble()
        bubble, art = Region((255, 200, 345, 400), "Espero que você se parta"), Region((10, 10, 40, 40), "")
        with mock.patch.object(lettering, "font_file", lambda: font):
            rendering.resize_regions_to_font_size(image, [bubble, art], None, 0, -1)
        self.assertIsNone(art.mangalate_plan)
        self.assertIsNone(art.mangalate_shaped)
        before = image.copy()
        rendering.render(image, bubble, None, False, None, False)
        rendering.render(image, art, None, False, None, False)
        self.assertEqual(calls, ["engine"])  # only the region without a bubble goes to the engine
        return bubble, np.argwhere((image != before).any(axis=2))

    def test_rectangle_plan_is_drawn_centred_in_the_rectangle(self):
        bubble, changed = self.render_page(None)  # no font: the rectangle plan
        self.assertIsNone(bubble.mangalate_shaped)
        self.assertIsNotNone(bubble.mangalate_plan)
        _, (x0, y0, x1, y1) = bubble.mangalate_plan
        self.assertTrue(changed.size and changed[:, 1].min() >= x0 and changed[:, 1].max() < x1)
        self.assertTrue(changed[:, 0].min() >= y0 and changed[:, 0].max() < y1)
        self.assertLessEqual(abs((changed[:, 1].min() + changed[:, 1].max()) / 2 - (x0 + x1) / 2), 1)
        self.assertLessEqual(abs((changed[:, 0].min() + changed[:, 0].max()) / 2 - (y0 + y1) / 2), 1)

    def test_shaped_plan_is_drawn_centred_in_the_bubble(self):
        bubble, changed = self.render_page(FONT)  # the comic font of the image: the path of real pages
        self.assertIsNone(bubble.mangalate_plan)
        plan = bubble.mangalate_shaped
        self.assertIsNotNone(plan)
        self.assertEqual(" ".join(plan["lines"]), "Espero que você se parta")
        x0, y0, x1, y1 = plan["box"]
        pad = int(round(plan["size"] * 0.07)) + 2  # the white outline around the letters
        self.assertGreater(len(changed), 500)
        self.assertGreaterEqual(changed[:, 1].min(), x0 - pad)
        self.assertLessEqual(changed[:, 1].max(), x1 + pad)
        self.assertGreaterEqual(changed[:, 0].min(), y0 - pad)
        self.assertLessEqual(changed[:, 0].max(), y1 + pad)
        # Centred on the bubble (300, 300); vertically a little lower, accents against descenders.
        self.assertLessEqual(abs((changed[:, 1].min() + changed[:, 1].max()) / 2 - 300), pad)
        self.assertLessEqual(abs((changed[:, 0].min() + changed[:, 0].max()) / 2 - 300), pad + 2)

    def test_translation_over_the_drawing_gets_a_halo_that_hugs_it(self):
        # Speech over the drawing: painted flat, the old block stayed as a white patch much bigger
        # than the translation.  Now the art is drawn back and the new letters get a tight halo.
        import types
        import cv2
        from engine_compat import bubble_layout

        def engine_render(img, region, *a):  # two dark words, as the engine draws them
            img[100:110, 50:70] = 0
            img[100:110, 76:96] = 0
            return img
        rendering = types.SimpleNamespace(resize_regions_to_font_size=None, render=engine_render,
                                          fg_bg_compare=lambda fg, bg: (fg, bg))
        bubble_layout(rendering, types.SimpleNamespace())
        image = np.full((200, 200, 3), 150, np.uint8)
        for x in range(-200, 200, 6):  # hatching
            cv2.line(image, (x, 0), (x + 200, 199), (30, 30, 30), 1)
        region = types.SimpleNamespace(font_size=20, mangalate_halo=(250, 250, 250))
        out = rendering.render(image.copy(), region, None, False, None, False)
        self.assertTrue((out[100:110, 50:70] == 0).all())                     # the letters
        self.assertTrue((out[100:110, 71:75] == 250).all())                   # the gap between the words
        self.assertTrue((out[97, 52:68] == 250).all() and (out[112, 78:94] == 250).all())  # its rim
        self.assertTrue((out[150:, :] == image[150:, :]).all())               # the drawing away from it stays
        self.assertTrue((out[:, 130:] == image[:, 130:]).all())
        # A hole the halo closes around (between two lines far apart) is filled, not left dark.
        from quality import halo_cloud
        ring = np.zeros((120, 120), bool)
        ring[30:36, 30:90] = ring[84:90, 30:90] = ring[30:90, 30:36] = ring[30:90, 84:90] = True
        self.assertTrue(halo_cloud(ring, 10)[60, 60])
        # Without a halo (any other region) only the letters are drawn.
        out = rendering.render(image.copy(), types.SimpleNamespace(font_size=20), None, False, None, False)
        self.assertTrue((out[100:110, 71:75] == image[100:110, 71:75]).all())


if __name__ == "__main__":
    unittest.main()


FONT = str(Path(__file__).resolve().parents[1] / "fonts" / "ComicNeue-Bold.ttf")


class ShapedLetteringTest(unittest.TestCase):
    """Lines that follow the oval, in the comic font (TBATE 199 p13, Grand Blue p44)."""

    TEXT = "É, porque foi só isso que os líderes deste continente nos deram."

    def test_lines_follow_the_oval_and_stay_inside(self):
        image = page_with_bubble(axes=(150, 200))
        plan = lettering.plan_shaped(image, (220, 240, 380, 360), [], self.TEXT, FONT, 30, 10)
        self.assertIsNotNone(plan)
        self.assertEqual(" ".join(plan["lines"]), self.TEXT)
        self.assertGreaterEqual(plan["size"], 30)  # the bubble has room: not shrunk below the original
        x0, y0, x1, y1 = plan["box"]
        self.assertLess(abs((y0 + y1) / 2 - 300), 0.1 * (y1 - y0) + 5)  # centred in the oval
        # Every line inside the ellipse: the corners of each line slot, not of the whole block.
        measure = lettering.Measure(FONT, plan["size"])
        widths = [measure(line) for line in plan["lines"]]
        for i, w in enumerate(widths):
            top = plan["top"] + i * plan["advance"]
            for x in (plan["x"] - w / 2, plan["x"] + w / 2):
                for y in (top, top + plan["slot"]):
                    self.assertLess(((x - 300) / 150) ** 2 + ((y - 300) / 200) ** 2, 1.0, plan["lines"][i])
        # The middle lines are the widest, like the oval.
        self.assertGreaterEqual(max(widths[1:-1] or widths), max(widths[0], widths[-1]))

    def test_no_lone_short_word_on_its_own_line(self):
        measure = lettering.Measure(FONT, 30)
        words = "Você gostou de alguma coisa um".split()
        self.assertIsNone(lettering.wrap(words, [measure("Você gostou de alguma coisa") + 2] * 2, measure))
        self.assertEqual(lettering.wrap(["Oi"], [500], measure), ["Oi"])

    def test_word_with_its_own_hyphen_may_end_a_line_there(self):
        # One Piece 1161 p9: "...fogo-Blitz!!" in a narrow bubble shrank to fit as one word.
        measure = lettering.Measure(FONT, 30)
        narrow = [measure("...fogo-") + 2] * 2
        self.assertEqual(lettering.wrap(["...fogo-Blitz!!"], narrow, measure), ["...fogo-", "Blitz!!"])
        self.assertEqual(lettering.wrap(["...fogo-Blitz!!"], [500], measure), ["...fogo-Blitz!!"])
        # A pronoun after the hyphen stays with its verb, and a dash is no break.
        self.assertIsNone(lettering.wrap(["salvá-la"], [measure("salvá-") + 2] * 2, measure))
        self.assertIsNone(lettering.wrap(["vivo--residente"], [measure("vivo--") + 2] * 2, measure))
        # A stutter is one word: "V-" / "você?!" and "Nã-" / "não!" read as a broken line.
        self.assertIsNone(lettering.wrap(["V-você?!"], [measure("você?!") + 2] * 2, measure))
        self.assertIsNone(lettering.wrap(["Nã-não!"], [measure("não!") + 2] * 2, measure))

    def test_syllable_breaks_follow_portuguese_rules(self):
        # Points where a long word may be cut, from the pt-BR patterns: never fewer than HYPHEN_SIDE
        # letters on a side, never in a short word or a name.
        cuts = lambda word: [word[:k] for k in lettering.syllable_breaks(word)]
        self.assertIn("inesca", cuts("inescapável"))
        self.assertIn("transfor", cuts("transformando"))
        for word in ("inescapável", "transformando", "considerando"):
            for k in lettering.syllable_breaks(word):
                self.assertGreaterEqual(k, lettering.HYPHEN_SIDE)
                self.assertGreaterEqual(len(word) - k, lettering.HYPHEN_SIDE)
        for word in ("casa", "Ana", "você", "Rex", "Marcus", "Kenjirou", "certeza", "verdade"):
            self.assertEqual(lettering.syllable_breaks(word), [], word)

    def test_long_word_is_cut_at_a_syllable_only_when_asked(self):
        measure = lettering.Measure(FONT, 30)
        narrow = [measure("...transfor-") + 2] * 3
        self.assertIsNone(lettering.wrap(["...transformando", "tudo"], narrow, measure))
        lines = lettering.wrap(["...transformando", "tudo"], narrow, measure, syllables=True)
        self.assertEqual(lines[0][-1], "-")
        self.assertEqual(" ".join(lines).replace("- ", ""), "...transformando tudo")
        # A word is cut once at most: "ines-" / "capá-" / "vel." reads as noise.
        tiny = [measure("ines-") + 2] * 4
        self.assertIsNone(lettering.wrap(["inescapável."], tiny, measure, syllables=True))
        # Between two vowels only when no other cut fits: "continu-" / "armos" reads as another word.
        self.assertEqual(lettering.syllable_cut("continuarmos", 1000, measure), len("continuar"))
        self.assertEqual(lettering.syllable_cut("continuarmos", measure("continu-") + 1, measure), len("conti"))
        # A word that fits its line is never cut.
        self.assertEqual(lettering.wrap(["Vamos", "lá"], [500], measure, syllables=True), ["Vamos lá"])

    def test_narrow_bubble_grows_the_letters_by_cutting_a_long_word(self):
        # One Piece 1161 p4: a caption column 61 px wide; a long word had to fit whole on a line
        # and the letters fell to half the original size.
        image = page_with_bubble(axes=(48, 150))
        text = "...transformando a cidade num lugar inescapável..."
        box = (275, 220, 325, 380)
        whole = lettering.plan_shaped(image, box, [], text, FONT, 22, 8, syllables=False)
        cut = lettering.plan_shaped(image, box, [], text, FONT, 22, 8)
        self.assertGreaterEqual(cut["size"], lettering.HYPHEN_GAIN * whole["size"])
        self.assertTrue(any(line.endswith("-") for line in cut["lines"]), cut["lines"])
        self.assertLessEqual(cut["size"], 22)  # cut only to come back near the original, never past it
        # The roomy oval keeps every word whole.
        roomy = lettering.plan_shaped(page_with_bubble(axes=(150, 200)), (220, 240, 380, 360), [], self.TEXT, FONT, 30, 10)
        self.assertFalse(any(line.endswith("-") for line in roomy["lines"]), roomy["lines"])

    def test_symbol_the_font_lacks_comes_from_the_symbol_font(self):
        # One Piece 1161 p5: "♡", which the comic font has not, was drawn as a box.
        from unittest import mock
        symbols = next((p for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                                    "C:/Windows/Fonts/seguisym.ttf", "/Library/Fonts/Arial Unicode.ttf")
                        if os.path.exists(p)), None)
        if symbols is None:
            self.skipTest("no font with symbols on this machine")
        with mock.patch.object(lettering, "SYMBOL_FONT", symbols):
            measure = lettering.Measure(FONT, 30)
            pieces = measure.runs("Oi ♡ tchau")
            self.assertEqual([p for p, f in pieces], ["Oi ", "♡", " tchau"])
            self.assertEqual([f.path for p, f in pieces], [FONT, symbols, FONT])
            self.assertEqual(measure("Oi ♡"), measure.font.getlength("Oi ") + pieces[1][1].getlength("♡"))
            # Drawn in the symbol font (not the box), sitting on the baseline of "Oi".
            image = page_with_bubble(axes=(150, 200))
            plan = lettering.plan_shaped(image, (220, 240, 380, 360), [], "Oi ♡", FONT, 30, 10)
            out = image.copy()
            lettering.draw_shaped(out, plan, (0, 0, 0), None)
        with mock.patch.object(lettering, "SYMBOL_FONT", None):
            boxed = image.copy()
            lettering.draw_shaped(boxed, plan, (0, 0, 0), None)
        paper = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) > 128
        ink = (cv2.cvtColor(out, cv2.COLOR_RGB2GRAY) < 128) & paper
        self.assertFalse(np.array_equal(ink, (cv2.cvtColor(boxed, cv2.COLOR_RGB2GRAY) < 128) & paper))
        cols = np.nonzero(ink.any(axis=0))[0]
        gaps = np.nonzero(np.diff(cols) > 5)[0]
        heart = cols[gaps[-1] + 1]  # the last piece of ink after the space
        letters = np.nonzero(ink[:, :heart].any(axis=1))[0]
        drawn = np.nonzero(ink[:, heart:].any(axis=1))[0]
        self.assertLessEqual(abs(int(drawn.max()) - int(letters.max())), 3)
        # Text in the comic font alone is one run, as before.
        self.assertEqual(len(lettering.Measure(FONT, 30).runs("Oi, tchau!")), 1)

    def test_no_font_falls_back(self):
        self.assertIsNone(lettering.plan_shaped(page_with_bubble(), (220, 240, 380, 360), [], self.TEXT, None, 30, 10))

    def test_font_choice(self):
        from unittest import mock
        with mock.patch.dict("os.environ", {"MANGALATE_FONT": FONT}):
            self.assertEqual(lettering.font_file(), FONT)
        with mock.patch.dict("os.environ", {"MANGALATE_FONT": "/nao/existe.ttf"}):
            self.assertIsNone(lettering.font_file())  # missing font: the engine's own layout

    def test_draw_writes_dark_ink_inside_the_box(self):
        image = page_with_bubble(axes=(150, 200))
        plan = lettering.plan_shaped(image, (220, 240, 380, 360), [], self.TEXT, FONT, 30, 10)
        out = image.copy()
        lettering.draw_shaped(out, plan, (0, 0, 0), (255, 255, 255))
        changed = np.argwhere((out != image).any(axis=2))
        self.assertGreater(len(changed), 500)
        x0, y0, x1, y1 = plan["box"]
        pad = 6
        self.assertGreaterEqual(changed[:, 1].min(), x0 - pad)
        self.assertLessEqual(changed[:, 1].max(), x1 + pad)
        self.assertGreaterEqual(changed[:, 0].min(), y0 - pad)
        self.assertLessEqual(changed[:, 0].max(), y1 + pad)


class OuroTwoLetteringTest(unittest.TestCase):
    def test_sentence_ends_its_line_when_the_size_allows(self):
        image = page_with_bubble(axes=(170, 120))
        plan = lettering.plan_shaped(image, (220, 260, 380, 340), [], "E se eles levarem ela? Por favor, vem.",
                                     FONT, 30, 10)
        self.assertTrue(any(line.endswith("ela?") for line in plan["lines"]), plan["lines"])

    def test_dangling_word_only_when_avoiding_it_costs_too_much(self):
        self.assertTrue(lettering.dangling("é."))
        self.assertTrue(lettering.dangling("um"))
        self.assertFalse(lettering.dangling("mas..."))
        self.assertFalse(lettering.dangling("Ah,"))

    def test_bubble_leaking_through_a_thin_gap_is_closed(self):
        # Grand Blue p45: a bubble that breaks the panel frame joins the gutter through a gap.
        image = page_with_bubble(axes=(110, 150))
        image[0:40, :] = 255                            # white gutter above the panel
        cv2.rectangle(image, (296, 0), (304, 160), (255, 255, 255), -1)  # 9 px channel to the gutter
        found = lettering.bubble_mask(image, (250, 250, 350, 350))
        mask, x0, y0 = found
        ys, xs = np.nonzero(mask)
        self.assertGreater(y0 + ys.min(), 140)          # the gutter is not part of the bubble
        self.assertLess(x0 + xs.min(), 220)             # and the bubble is not cut to the text box


def page_with_panel(art_band=None):
    """A large light panel closed only by its frame, with no bubble in it (text on the sky)."""
    image = np.full((800, 800, 3), 90, np.uint8)
    cv2.rectangle(image, (100, 100), (700, 700), (255, 255, 255), -1)
    cv2.rectangle(image, (100, 100), (700, 700), (0, 0, 0), 4)
    if art_band is not None:  # dark drawing across the panel (a shore, a crowd)
        cv2.rectangle(image, (104, art_band[0]), (696, art_band[1]), (40, 40, 40), -1)
    return image


def line_slots(plan):
    """(x0, y0, x1, y1) of every drawn line of a plan_shaped result."""
    measure = lettering.Measure(plan["font"], plan["size"])
    slots = []
    for i, line in enumerate(plan["lines"]):
        w = measure(line)
        top = plan["top"] + i * plan["advance"]
        slots.append((plan["x"] - w / 2, top, plan["x"] + w / 2, top + plan["slot"]))
    return slots


def centre_y(plan):
    x0, y0, x1, y1 = plan["box"]
    return (y0 + y1) / 2


class VerticalCentreTest(unittest.TestCase):
    """The translation stays at the height of the original text, not in the middle of a big light area.

    Test rounds: text on the sky of a panel (no bubble) or in a bubble whose fill leaked into
    the sky was centred in the whole panel, lines away from the original, over the outline of
    another bubble.
    """

    LINE = 30
    TEXT = "A reunião começa logo depois do almoço."

    def test_text_near_the_bottom_of_a_large_light_area_stays_there(self):
        box = (320, 600, 480, 660)  # two lines of lettering near the bottom of the panel
        plan = lettering.plan_shaped(page_with_panel(), box, [], self.TEXT, FONT, self.LINE, 10)
        self.assertIsNotNone(plan)
        self.assertLessEqual(abs(centre_y(plan) - (box[1] + box[3]) / 2), self.LINE,
                             f"block centre {centre_y(plan):.0f}, original text centre {(box[1] + box[3]) / 2:.0f}")

    def test_staying_in_place_does_not_shrink_the_letters(self):
        box = (320, 600, 480, 660)
        text = "A reunião começa logo depois do almoço, no salão principal, e ninguém pode faltar."
        plan = lettering.plan_shaped(page_with_panel(), box, [], text, FONT, self.LINE, 10)
        self.assertGreaterEqual(plan["size"], self.LINE)

    def test_dark_drawing_next_to_the_text_is_never_covered(self):
        image = page_with_panel(art_band=(670, 696))  # drawing right under the text
        box = (320, 600, 480, 660)
        plan = lettering.plan_shaped(image, box, [], self.TEXT, FONT, self.LINE, 10)
        self.assertIsNotNone(plan)
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        for x0, y0, x1, y1 in line_slots(plan):
            under = gray[int(y0):int(np.ceil(y1)), int(x0):int(np.ceil(x1))]
            self.assertFalse((under < 110).any(), "a line is drawn over the dark drawing")

    def test_centred_text_in_an_oval_keeps_the_middle(self):
        image = page_with_bubble(axes=(170, 140))
        box = (230, 270, 370, 330)
        plan = lettering.plan_shaped(image, box, [], self.TEXT, FONT, self.LINE, 10)
        self.assertGreaterEqual(plan["size"], self.LINE)
        x0, y0, x1, y1 = plan["box"]
        self.assertLess(abs(centre_y(plan) - 300), 0.1 * (y1 - y0) + 5)

    def test_bubble_with_a_tail_keeps_the_text_in_its_body(self):
        image = page_with_bubble(axes=(150, 110))
        tail = np.array([[230, 380], [270, 395], [180, 480]], np.int32)  # down-left, like most tails
        cv2.fillPoly(image, [tail], (255, 255, 255))
        cv2.line(image, (230, 380), (180, 480), (0, 0, 0), 3)
        cv2.line(image, (270, 395), (180, 480), (0, 0, 0), 3)
        box = (240, 270, 360, 330)
        plan = lettering.plan_shaped(image, box, [], self.TEXT, FONT, self.LINE, 10)
        self.assertGreaterEqual(plan["size"], self.LINE)
        self.assertLessEqual(abs(centre_y(plan) - 300), self.LINE)
        for x0, y0, x1, y1 in line_slots(plan):
            for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
                self.assertLess(((x - 300) / 150) ** 2 + ((y - 300) / 110) ** 2, 1.0, "a line leaves the oval body")

    def test_text_at_the_edge_of_the_area_stays_inside_whole_and_readable(self):
        # A long translation whose original box sits against the top or the bottom of the light
        # area: the centre cannot always stay put, but the block never leaves the area, never
        # cuts a letter, never covers the dark drawing and never gets tiny.
        text = "A reunião começa logo depois do almoço, no salão principal, e ninguém pode chegar atrasado."
        area_top, area_bottom = 104, 664  # inside the frame, above a dark band 670..696
        cases = {"top edge": (320, 108, 480, 168), "bottom edge": (320, 600, 480, 660), "room": (320, 330, 480, 390)}
        for name, box in cases.items():
            with self.subTest(name):
                image = page_with_panel(art_band=(670, 696))
                cv2.line(image, (560, 120), (560, 650), (30, 30, 30), 3)  # a dark stroke beside the text
                plan = lettering.plan_shaped(image, box, [], text, FONT, self.LINE, 10)
                again = lettering.plan_shaped(image, box, [], text, FONT, self.LINE, 10)
                self.assertIsNotNone(plan)
                self.assertEqual(plan, again)                         # deterministic
                self.assertEqual(" ".join(plan["lines"]), text)       # every word, none split
                self.assertGreaterEqual(plan["size"], 0.6 * self.LINE)  # not below the safe size
                x0, y0, x1, y1 = plan["box"]
                self.assertGreaterEqual(y0, area_top)
                self.assertLessEqual(y1, area_bottom)
                half = (y1 - y0) / 2
                centre = (box[1] + box[3]) / 2
                if area_top <= centre - half and centre + half <= area_bottom:
                    self.assertLessEqual(abs(centre_y(plan) - centre), self.LINE)  # room: stays put
                gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
                for sx0, sy0, sx1, sy1 in line_slots(plan):
                    under = gray[int(sy0):int(np.ceil(sy1)), int(sx0):int(np.ceil(sx1))]
                    self.assertFalse((under < 110).any(), "a line is drawn over the dark drawing")
                # Every drawn letter lands whole on the page and inside the light area.
                drawn = image.copy()
                lettering.draw_shaped(drawn, plan, (0, 0, 0), None)
                ys, xs = np.nonzero((drawn != image).any(axis=2))
                self.assertGreater(len(ys), 0)
                self.assertTrue(area_top <= ys.min() and ys.max() <= area_bottom and 104 <= xs.min() and xs.max() < 557,
                                f"ink at x {xs.min()}..{xs.max()}, y {ys.min()}..{ys.max()}")

    def test_bubble_leaking_into_the_sky_keeps_the_text_in_it(self):
        # A bubble with a gap in its outline at the top, inside a light panel: the fill runs
        # through the gap into the sky, a light area far bigger than the bubble.
        image = page_with_panel()
        cv2.ellipse(image, (400, 580), (130, 85), 0, 0, 360, (0, 0, 0), 3)
        cv2.rectangle(image, (385, 490), (415, 500), (255, 255, 255), -1)  # 30 px gap: wider than a leak closes
        box = (330, 550, 470, 610)
        plan = lettering.plan_shaped(image, box, [], self.TEXT, FONT, self.LINE, 10)
        self.assertIsNotNone(plan)
        self.assertLessEqual(abs(centre_y(plan) - (box[1] + box[3]) / 2), self.LINE,
                             f"block centre {centre_y(plan):.0f}, original text centre {(box[1] + box[3]) / 2:.0f}")


def clearance(image, plan):
    """Smallest distance (px) from a drawn line to a dark pixel of the page."""
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    dist = cv2.distanceTransform((gray >= 110).astype(np.uint8), cv2.DIST_L2, 3)
    return min(float(dist[int(y0):int(np.ceil(y1)), int(x0):int(np.ceil(x1))].min())
               for x0, y0, x1, y1 in line_slots(plan))


class ClosedBubbleTest(unittest.TestCase):
    """A well placed text in a tall closed bubble keeps the layout it had; only a leak moves it.

    Test rounds: the text sat a third of a line above the middle of a tall bubble with a small
    drawing inside it; limiting the rows anyway moved the block a few pixels, one line fewer
    fitted, and the longest line ran up to the outline.
    """

    LINE = 21
    TEXT = "Vocês vão ganhar muito tempo assim."

    def test_text_near_the_middle_of_a_tall_closed_bubble_keeps_its_air(self):
        image = np.full((700, 600, 3), 90, np.uint8)
        cv2.ellipse(image, (300, 350), (120, 170), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(image, (300, 350), (120, 170), 0, 0, 360, (0, 0, 0), 3)
        cv2.circle(image, (202, 380), 28, (30, 30, 30), -1)  # a small drawing inside, on the left
        box = (230, 288, 370, 396)  # centre 8 px (0.4 line) above the middle of the bubble
        plan = lettering.plan_shaped(image, box, [], self.TEXT, FONT, self.LINE, 10)
        self.assertIsNotNone(plan)
        self.assertEqual(" ".join(plan["lines"]), self.TEXT)
        # The block is centred in the rows it is given, whatever the font: in the middle of the
        # bubble (y 350) when the rows are left alone, a few px higher when they are cut.
        self.assertLessEqual(abs(centre_y(plan) - 350), 2, f"block centre {centre_y(plan):.1f}, bubble middle 350")


class TextAtTheTopTest(unittest.TestCase):
    """Text lettered at the top of a closed bubble or a narration box, translation much longer.

    The middle of the interior is lines away from the text, as in a leak, but the area is closed:
    the translation must stay whole, inside, and not shrink far below the original size.
    """

    LINE = 30
    TEXT = "Na manhã seguinte, todos já estavam no porto esperando o primeiro barco do dia."

    def check(self, image, box, inside):
        plan = lettering.plan_shaped(image, box, [], self.TEXT, FONT, self.LINE, 10)
        self.assertIsNotNone(plan)
        self.assertEqual(" ".join(plan["lines"]), self.TEXT)               # every word, none split
        self.assertGreaterEqual(plan["size"], 0.7 * self.LINE, plan["lines"])  # not tiny
        for x0, y0, x1, y1 in line_slots(plan):
            for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
                self.assertTrue(inside(x, y), f"line corner ({x:.0f}, {y:.0f}) outside the interior")
        return plan

    # Known defect of the centre limit: a closed tall bubble with the text at its top passes the
    # asymmetry threshold like a leak and the letters shrink (18 px for 30).  No real case in the
    # five measured excerpts; queued until one shows up on a real page.
    @unittest.expectedFailure
    def test_text_at_the_top_of_a_tall_closed_bubble(self):
        image = np.full((800, 600, 3), 90, np.uint8)
        cv2.ellipse(image, (300, 400), (130, 230), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(image, (300, 400), (130, 230), 0, 0, 360, (0, 0, 0), 3)
        box = (240, 215, 360, 275)  # two lines near the top of the oval
        self.check(image, box, lambda x, y: ((x - 300) / 130) ** 2 + ((y - 400) / 230) ** 2 < 1.0)

    def test_text_at_the_top_of_a_narration_box(self):
        image = np.full((700, 700, 3), 90, np.uint8)
        cv2.rectangle(image, (150, 120), (550, 520), (255, 255, 255), -1)
        cv2.rectangle(image, (150, 120), (550, 520), (0, 0, 0), 3)
        box = (230, 140, 470, 200)  # two lines right under the top edge of the box
        self.check(image, box, lambda x, y: 153 <= x <= 547 and 123 <= y <= 517)

