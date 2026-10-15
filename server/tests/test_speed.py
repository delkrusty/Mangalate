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


if __name__ == "__main__":
    unittest.main()
