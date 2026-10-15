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
