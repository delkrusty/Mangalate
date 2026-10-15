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
