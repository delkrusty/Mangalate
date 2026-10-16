"""Translation fitted to the bubble instead of the original text box (lettering.py)."""
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
    """The engine renderer uses the plan; regions without one keep the engine's drawing."""

    def test_planned_region_is_drawn_centred_in_the_rectangle(self):
        import types
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
        rendering.resize_regions_to_font_size(image, [bubble, art], None, 0, -1)
        self.assertIsNotNone(bubble.mangalate_plan)
        self.assertIsNone(art.mangalate_plan)
        before = image.copy()
        rendering.render(image, bubble, None, False, None, False)
        rendering.render(image, art, None, False, None, False)
        self.assertEqual(calls, ["engine"])
        changed = np.argwhere((image != before).any(axis=2))
        _, (x0, y0, x1, y1) = bubble.mangalate_plan
        self.assertTrue(changed.size and changed[:, 1].min() >= x0 and changed[:, 1].max() < x1)


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
