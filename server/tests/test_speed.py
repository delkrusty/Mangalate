"""Step timings and cleaning while the AI translates (no engine, no network)."""
import asyncio
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import speed


def fake_engine(drop_region=False):
    calls = []

    class Engine:
        async def _run_detection(self, config, ctx): return None
        async def _run_ocr(self, config, ctx): return None
        async def _run_textline_merge(self, config, ctx): return ctx.text_regions
        async def _run_text_rendering(self, config, ctx): return None

        async def _run_text_translation(self, config, ctx):
            calls.append(("translate-start", time.monotonic()))
            await asyncio.sleep(0.3)  # the AI answering
            calls.append(("translate-end", time.monotonic()))
            return ctx.text_regions[1:] if drop_region else list(ctx.text_regions)

        async def _run_mask_refinement(self, config, ctx):
            calls.append(("mask", threading.current_thread().name, len(ctx.text_regions)))
            return object()

        async def _run_inpainting(self, config, ctx):
            calls.append(("inpaint-start", time.monotonic()))
            time.sleep(0.3)  # CPU work, blocks its own thread only
            calls.append(("inpaint-end", time.monotonic()))
            return "clean"

    speed.install(Engine)
    return Engine(), calls


async def run_page(engine, ctx):
    ctx.text_regions = await engine._run_text_translation(None, ctx)
    ctx.mask = await engine._run_mask_refinement(None, ctx)
    return await engine._run_inpainting(None, ctx)


def page():
    return SimpleNamespace(text_regions=[SimpleNamespace(text="A"), SimpleNamespace(text="B")],
                           img_rgb=None, mask_raw=None, mask=None)


class OverlapTest(unittest.TestCase):
    def test_cleaning_runs_while_the_ai_translates(self):
        engine, calls = fake_engine()
        ctx = page()
        started = time.monotonic()
        self.assertEqual(asyncio.run(run_page(engine, ctx)), "clean")
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 0.5)  # sequential would be 0.6 s
        self.assertEqual(sum(1 for c in calls if c[0] == "inpaint-start"), 1)
        self.assertIn("limpeza_antecipada", ctx.mangalate_timings)
        self.assertIn("traducao", ctx.mangalate_timings)

    def test_dropped_region_cleans_again_with_the_final_regions(self):
        engine, calls = fake_engine(drop_region=True)
        ctx = page()
        asyncio.run(run_page(engine, ctx))
        masks = [c for c in calls if c[0] == "mask"]
        self.assertEqual([m[2] for m in masks], [2, 1])  # prepared with 2, redone with 1
        self.assertEqual(sum(1 for c in calls if c[0] == "inpaint-start"), 2)

    def test_overlap_can_be_turned_off(self):
        import os
        os.environ["MANGALATE_OVERLAP"] = "false"
        try:
            engine, calls = fake_engine()
            asyncio.run(run_page(engine, page()))
            first = [c[0] for c in calls]
            self.assertLess(first.index("translate-end"), first.index("inpaint-start"))
        finally:
            del os.environ["MANGALATE_OVERLAP"]


class TwoPagesTest(unittest.TestCase):
    def test_two_pages_share_the_wait_and_heavy_steps_take_turns(self):
        engine, calls = fake_engine()

        async def both():
            return await asyncio.gather(run_page(engine, page()), run_page(engine, page()))

        started = time.monotonic()
        self.assertEqual(asyncio.run(both()), ["clean", "clean"])
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 0.85)  # one page after the other would be 1.2 s
        starts = sorted(c[1] for c in calls if c[0] == "inpaint-start")
        ends = sorted(c[1] for c in calls if c[0] == "inpaint-end")
        self.assertEqual(len(starts), 2)
        self.assertGreaterEqual(starts[1], ends[0] - 0.01)  # never two cleanings at once

    def test_one_page_at_a_time_keeps_the_steps_in_place(self):
        import os
        os.environ["MANGALATE_PAGES_AT_ONCE"] = "1"
        try:
            self.assertEqual(speed.pages_at_once(), 1)
            engine, calls = fake_engine()
            asyncio.run(run_page(engine, page()))
            masks = [c for c in calls if c[0] == "mask"]
            self.assertTrue(masks)
        finally:
            del os.environ["MANGALATE_PAGES_AT_ONCE"]


class FlatFillTest(unittest.TestCase):
    """Text in a plain bubble is covered with the bubble colour; text over art goes to the model."""

    def engine(self):
        seen = []

        class Engine:
            async def _run_inpainting(self, config, ctx):
                seen.append((ctx.img_rgb.shape, int((ctx.mask > 0).sum())))
                out = ctx.img_rgb.copy()
                out[ctx.mask > 0] = (1, 2, 3)  # what the model would paint
                return out

        Engine._run_inpainting = speed.flat_first(Engine._run_inpainting)
        return Engine(), seen

    def page(self):
        import numpy as np
        image = np.full((600, 400, 3), 120, np.uint8)
        image[50:250, 50:350] = (250, 248, 245)              # plain bubble
        rng = np.random.default_rng(1)
        image[400:560, 40:360] = rng.integers(0, 255, (160, 320, 3))  # art
        mask = np.zeros((600, 400), np.uint8)
        image[120:140, 100:300] = 0                           # letters in the bubble
        mask[116:144, 96:304] = 255
        mask[460:480, 120:280] = 255                          # letters over the art
        return image, mask

    def test_bubble_is_filled_without_model_and_art_goes_to_model_in_a_crop(self):
        engine, seen = self.engine()
        image, mask = self.page()
        out = asyncio.run(engine._run_inpainting(None, SimpleNamespace(img_rgb=image, mask=mask, text_regions=[])))
        self.assertTrue((out[116:144, 96:304] == (250, 248, 245)).all())   # bubble colour, no letters left
        self.assertEqual(len(seen), 1)
        shape, painted = seen[0]
        self.assertEqual(painted, 20 * 160)                                 # only the text over art
        self.assertLess(shape[0] * shape[1], 600 * 400)                     # a crop, not the page
        self.assertTrue((out[460:480, 120:280] == (1, 2, 3)).all())
        self.assertTrue((out[0:40] == image[0:40]).all())                   # untouched elsewhere

    def test_only_bubbles_skips_the_model(self):
        engine, seen = self.engine()
        image, mask = self.page()
        mask[460:480] = 0
        asyncio.run(engine._run_inpainting(None, SimpleNamespace(img_rgb=image, mask=mask)))
        self.assertEqual(seen, [])

    def outlined_bubble(self, gap):
        """Plain bubble whose outline runs `gap` px above the text mask, inside the measuring ring."""
        import numpy as np
        image = np.full((300, 400, 3), 255, np.uint8)
        mask = np.zeros((300, 400), np.uint8)
        image[120:140, 100:300] = 0                           # letters
        mask[116:144, 96:304] = 255
        top = 116 - gap
        image[top - 2:top, 60:340] = 0                        # outline, 2 px thick
        return image, mask, (slice(top - 2, top), slice(60, 340))

    def test_outline_near_the_text_does_not_send_a_plain_bubble_to_the_model(self):
        # Seen in white bubbles: the ring caught the outline, the model left a smudge of the letters.
        engine, seen = self.engine()
        image, mask, outline = self.outlined_bubble(gap=3)
        out = asyncio.run(engine._run_inpainting(None, SimpleNamespace(img_rgb=image, mask=mask)))
        self.assertEqual(seen, [])
        self.assertTrue((out[116:144, 96:304] == 255).all())
        self.assertTrue((out[outline] == 0).all())                          # outline intact

    def test_drawing_kept_next_to_the_text_does_not_send_the_bubble_to_the_model(self):
        # One Piece 1161 p16: an anger vein read as "JJJJ" stays whole right under the mask;
        # it spoiled the ring, and the model smeared grey over the bubble.
        import numpy as np
        engine, seen = self.engine()
        image = np.full((300, 400, 3), 255, np.uint8)
        mask = np.zeros((300, 400), np.uint8)
        image[120:140, 100:300] = 0                           # letters
        mask[116:144, 96:304] = 255
        image[145:166, 130:150] = image[145:166, 175:195] = image[145:166, 220:240] = 0  # the drawing, 1 px under the mask
        drawn = [[125, 145, 255, 167]]
        out = asyncio.run(engine._run_inpainting(None, SimpleNamespace(img_rgb=image, mask=mask, mangalate_drawn=drawn)))
        self.assertEqual(seen, [])
        self.assertTrue((out[116:144, 96:304] == 255).all())
        self.assertTrue((out[145:166, 130:150] == 0).all())                  # drawing intact
        engine, seen = self.engine()
        asyncio.run(engine._run_inpainting(None, SimpleNamespace(img_rgb=image, mask=mask)))
        self.assertEqual(len(seen), 1)                        # without it, the model was used

    def test_outline_running_under_the_mask_still_goes_to_the_model(self):
        engine, seen = self.engine()
        image, mask, _ = self.outlined_bubble(gap=0)
        image[116:144, 60:62] = 0                             # outline side crossing into the mask
        mask[116:144, 60:96] = 255
        asyncio.run(engine._run_inpainting(None, SimpleNamespace(img_rgb=image, mask=mask)))
        self.assertEqual(len(seen), 1)

    def test_text_on_screentone_still_goes_to_the_model(self):
        import numpy as np
        engine, seen = self.engine()
        image, mask, _ = self.outlined_bubble(gap=3)
        tone = np.full((60, 240), 255, np.uint8)
        tone[::3, ::3] = 0                                    # dots every 3 px
        image[100:160, 80:320] = np.where(mask[100:160, 80:320, None] > 0, image[100:160, 80:320], tone[..., None])
        asyncio.run(engine._run_inpainting(None, SimpleNamespace(img_rgb=image, mask=mask)))
        self.assertEqual(len(seen), 1)

    def test_can_be_turned_off(self):
        import os
        engine, seen = self.engine()
        image, mask = self.page()
        os.environ["MANGALATE_FLAT_FILL"] = "false"
        try:
            asyncio.run(engine._run_inpainting(None, SimpleNamespace(img_rgb=image, mask=mask)))
        finally:
            del os.environ["MANGALATE_FLAT_FILL"]
        self.assertEqual(seen[0], ((600, 400, 3), int((mask > 0).sum())))


if __name__ == "__main__":
    unittest.main()
