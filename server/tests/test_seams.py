"""Bubbles cut between webtoon slices: stitching, cropping and matching halves."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from seams import SeamCache, Strip, finish

RNG = np.random.default_rng(65)


def long_strip(height=1600, width=400):
    """Textured art with a white bubble and black lettering across y=800."""
    art = RNG.integers(40, 220, (height // 8, width // 8, 3), dtype=np.uint8)
    image = Image.fromarray(np.kron(art, np.ones((8, 8, 1), np.uint8)))
    draw = ImageDraw.Draw(image)
    draw.ellipse((60, 700, 340, 900), fill="white", outline="black", width=4)
    for y in range(740, 870, 26):
        draw.text((120, y), "WHAT IF THEY ARE CAUGHT", fill="black")
    return image


def slices(image, cut=800):
    return image.crop((0, 0, image.width, cut)), image.crop((0, cut, image.width, image.height))


class StripTest(unittest.TestCase):
    def test_true_neighbours_are_stitched_and_cropped_back_exactly(self):
        upper, lower = slices(long_strip())
        strip = Strip(upper, below=lower)
        self.assertTrue(strip.stitched)
        self.assertEqual(strip.image.height, 800 + int(800 * 0.35))
        self.assertEqual(strip.crop(strip.image).tobytes(), upper.tobytes())
        strip = Strip(lower, above=upper)
        self.assertEqual(strip.top, int(800 * 0.35))
        self.assertEqual(strip.crop(strip.image).tobytes(), lower.tobytes())

    def test_wrong_neighbour_blank_seam_or_other_width_is_ignored(self):
        upper, _ = slices(long_strip())
        unrelated = Image.fromarray(RNG.integers(0, 255, (800, 400, 3), dtype=np.uint8))
        self.assertFalse(Strip(upper, below=unrelated).stitched)
        blank = Image.new("RGB", (400, 800), "white")
        self.assertFalse(Strip(blank, below=blank).stitched)
        self.assertFalse(Strip(upper, below=upper.resize((300, 800))).stitched)
        self.assertEqual(Strip(upper).image.tobytes(), upper.tobytes())


class MatchingHalvesTest(unittest.TestCase):
    """Each request renders the cut bubble on its own; the halves must still match."""

    def render(self, strip, colour, shift):
        # Stand-in for the engine: paints the "translation" over the bubble area,
        # with a different colour and position in each request.
        image = strip.image.copy()
        y0 = 720 - (800 - strip.top) if strip.below is None else 720
        box = (90 + shift, y0 + shift, 310 + shift, y0 + 160 + shift)
        ImageDraw.Draw(image).rectangle(box, fill=colour)
        return image, [SimpleNamespace(xyxy=box)]

    def test_second_page_reuses_the_first_pages_half(self):
        upper, lower = slices(long_strip())
        cache = SeamCache()
        first = Strip(upper, below=lower)
        rendered, regions = self.render(first, (200, 30, 30), 0)
        top_page = np.asarray(finish(first, rendered, regions, cache, "cfg"))
        second = Strip(lower, above=upper)
        rendered, regions = self.render(second, (30, 30, 200), 7)
        bottom_page = np.asarray(finish(second, rendered, regions, cache, "cfg"))
        self.assertEqual(top_page.shape, (800, 400, 3))
        self.assertEqual(bottom_page.shape, (800, 400, 3))
        # Across the seam, the bubble continues with the first request's rendering.
        np.testing.assert_array_equal(top_page[-1, 100:300], bottom_page[0, 100:300])
        self.assertTrue((bottom_page[0, 100:300] == (200, 30, 30)).all())

    def test_own_bubble_next_to_the_cut_one_keeps_its_translation(self):
        # The stored half is a rectangle with a margin: it covered a bubble of the second page right
        # under the cut one, which the first request saw only as context, still in English (Manhwa
        # teste p37 "AREN'T YOU?" over its translation, p38 "WAS I").
        upper, lower = slices(long_strip())
        cache = SeamCache()
        first = Strip(upper, below=lower)
        rendered, regions = self.render(first, (200, 30, 30), 0)
        finish(first, rendered, regions, cache, "cfg")
        second = Strip(lower, above=upper)
        rendered, regions = self.render(second, (30, 30, 200), 7)
        own = (150, second.top + 100, 250, second.top + 125)  # wholly in the second page
        ImageDraw.Draw(rendered).rectangle(own, fill=(30, 200, 30))
        regions.append(SimpleNamespace(xyxy=own))
        bottom_page = np.asarray(finish(second, rendered, regions, cache, "cfg"))
        self.assertTrue((bottom_page[100:126, 150:251] == (30, 200, 30)).all())
        # The cut bubble still continues with the first request's rendering.
        self.assertTrue((bottom_page[0, 100:300] == (200, 30, 30)).all())

    def test_own_bubble_touching_the_cut_one_never_mixes_its_letters(self):
        # The own bubble's box (with its margin) runs onto the cut bubble: there the cut bubble keeps
        # the stored half, so its letters are never half of one request and half of the other.
        upper, lower = slices(long_strip())
        cache = SeamCache()
        first = Strip(upper, below=lower)
        rendered, regions = self.render(first, (200, 30, 30), 0)
        finish(first, rendered, regions, cache, "cfg")
        second = Strip(lower, above=upper)
        rendered, regions = self.render(second, (30, 30, 200), 7)
        cut_bottom = regions[0].xyxy[3] - second.top  # the cut bubble ends here in the page
        own = (150, second.top + cut_bottom + 4, 250, second.top + cut_bottom + 30)
        ImageDraw.Draw(rendered).rectangle(own, fill=(30, 200, 30))
        regions.append(SimpleNamespace(xyxy=own))
        bottom_page = np.asarray(finish(second, rendered, regions, cache, "cfg"))
        self.assertTrue((bottom_page[0:cut_bottom - 7, 100:300] == (200, 30, 30)).all())
        self.assertTrue((bottom_page[cut_bottom + 4:cut_bottom + 31, 150:251] == (30, 200, 30)).all())

    def test_settings_change_does_not_reuse_old_halves(self):
        upper, lower = slices(long_strip())
        cache = SeamCache()
        first = Strip(upper, below=lower)
        rendered, regions = self.render(first, (200, 30, 30), 0)
        finish(first, rendered, regions, cache, "groq")
        second = Strip(lower, above=upper)
        rendered, regions = self.render(second, (30, 30, 200), 0)
        bottom_page = np.asarray(finish(second, rendered, regions, cache, "gemini"))
        self.assertTrue((bottom_page[0, 100:300] == (30, 30, 200)).all())

    def test_page_without_neighbours_is_unchanged_path(self):
        upper, _ = slices(long_strip())
        strip = Strip(upper)
        self.assertEqual(finish(strip, upper, None, SeamCache()).tobytes(), upper.tobytes())


if __name__ == "__main__":
    unittest.main()
