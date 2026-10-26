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

    def haloed_page(self, over_art, tone=170):
        """Dark letters with a white halo over cross-hatched shading, as a "tracos" block."""
        import cv2
        import numpy as np
        image = np.full((260, 420, 3), tone, np.uint8)
        for x in range(-260, 420, 7):
            cv2.line(image, (x, 0), (x + 260, 259), (40, 40, 40), 1)
            cv2.line(image, (x + 260, 0), (x, 259), (40, 40, 40), 1)
        raw = np.zeros((260, 420), np.uint8)
        quads = []
        for i, text in enumerate(("WELL, I GUESS", "I DESERVE", "THIS TOO...")):
            y = 70 + 30 * i
            cv2.putText(raw, text, (100, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, 255, 2)
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
            quads.append([[98, y - th - 3], [102 + tw, y - th - 3], [102 + tw, y + 4], [98, y + 4]])
        image[cv2.dilate(raw, np.ones((7, 7), np.uint8)) > 0] = 255
        image[raw > 0] = 0
        mask = cv2.dilate(raw, np.ones((21, 21), np.uint8))  # the engine's mask, grown
        background = {"kind": "tracos", "fala": True, **({"sobre_arte": True} if over_art else {})}
        region = SimpleNamespace(lines=np.array(quads), xyxy=(98, 40, 270, 134), font_size=18,
                                 mangalate_background=background)
        return image, mask, raw, region

    def test_haloed_speech_over_the_drawing_sends_only_letters_and_halo_to_the_model(self):
        # The model smeared the whole block (bars, bricks, hair); painted flat with the halo, the
        # old block stayed as a white patch bigger than the translation.  Only the letters and
        # their halo are drawn back by the model.
        import cv2
        import numpy as np
        engine, seen = self.engine()
        image, mask, raw, region = self.haloed_page(over_art=True)
        out = asyncio.run(engine._run_inpainting(None, SimpleNamespace(img_rgb=image, mask=mask, mask_raw=raw,
                                                                       text_regions=[region])))
        self.assertEqual(len(seen), 1)
        self.assertTrue((out[raw > 0] == (1, 2, 3)).all())                  # letters drawn back by the model
        self.assertEqual(region.mangalate_halo, (255, 255, 255))            # the halo, for the new text
        # The drawing past the halo and its soft rim stays.
        hatching = (image.max(axis=2) < 100) & (cv2.dilate(raw, np.ones((15, 15), np.uint8)) == 0)
        self.assertTrue((out[hatching] == image[hatching]).all())
        self.assertTrue((out[mask == 0] == image[mask == 0]).all())
        # A light tone of the drawing (hair, a pale screentone) inside the line boxes stays: only
        # the halo right around the letters goes to the model.
        image, mask, raw, region = self.haloed_page(over_art=True, tone=225)
        left = speed.paint_halos(image, mask, [region], raw)[1]
        away = cv2.dilate(raw, np.ones((25, 25), np.uint8)) == 0
        self.assertFalse(left[away].any())
        # The same block not listed as over the drawing goes to the model with its whole mask.
        engine, seen = self.engine()
        image, mask, raw, region = self.haloed_page(over_art=False)
        asyncio.run(engine._run_inpainting(None, SimpleNamespace(img_rgb=image, mask=mask, mask_raw=raw,
                                                                 text_regions=[region])))
        self.assertEqual(seen[0][1], int((mask > 0).sum()))
        self.assertFalse(hasattr(region, "mangalate_halo"))

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

    def vein(self, size, under=None):
        """Plain bubble whose mask cut into a drawing ``size`` px wide beside the text, ``under`` px of it."""
        import numpy as np
        under = size // 2 if under is None else under
        image = np.full((300, 400, 3), 255, np.uint8)
        mask = np.zeros((300, 400), np.uint8)
        image[120:140, 120:200] = 0                           # letters (one short line)
        mask[116:144, 96:204] = 255
        for top in range(116, 144, 4):                        # strokes of the drawing, 1 px apart
            image[top:top + 3, 96 + under - size:96 + under] = 0
        return image, mask

    def test_drawing_cut_by_the_mask_does_not_send_the_bubble_to_the_model(self):
        # One Piece 1161 p8: the mask took half an anger vein beside "HIM?!"; the rest spoiled
        # the ring, and the model painted a ghost of the letters over the bubble.  The bubble is
        # filled, and the rest of the small drawing goes with the letters.
        engine, seen = self.engine()
        image, mask = self.vein(36)
        out = asyncio.run(engine._run_inpainting(None, SimpleNamespace(img_rgb=image, mask=mask)))
        self.assertEqual(seen, [])
        self.assertTrue((out[100:160, 60:220] == 255).all())  # no letter, no half drawing

    def test_drawing_the_mask_only_grazes_stays(self):
        # Grand Blue 102 p34: the tip of a sound effect beside the bubble touched the mask by a
        # pixel or two; it is art, not a drawing cut by the mask.
        engine, seen = self.engine()
        image, mask = self.vein(36, under=2)
        out = asyncio.run(engine._run_inpainting(None, SimpleNamespace(img_rgb=image, mask=mask)))
        self.assertTrue((out[mask == 0] == image[mask == 0]).all())

    def test_speck_of_mask_does_not_take_a_letter_of_the_art(self):
        # Seen on an old mask of a form kept as art: loose specks of mask touched its letters,
        # and a whole letter would go with a speck smaller than itself.
        import numpy as np
        image = np.full((120, 120, 3), 255, np.uint8)
        image[50:66, 50:60] = 0                               # a letter of the art, 160 px
        speck = np.zeros((120, 120), bool)
        speck[50:58, 54:60] = True                            # a speck of mask over 48 px of it
        self.assertFalse(speed.cut_marks(image, speck, speck, np.array([255, 255, 255])).any())
        bigger = np.zeros((120, 120), bool)
        bigger[44:66, 54:70] = True                           # text being cleaned that cut the letter
        self.assertTrue(speed.cut_marks(image, bigger, bigger, np.array([255, 255, 255]))[50:66, 50:54].all())

    def test_letter_of_a_word_kept_as_drawn_is_not_taken(self):
        # Grand Blue 102 p4: the mask of a title ran onto words of the small print under it;
        # the letters it cut have neighbours of their word right beside them: nothing is taken.
        import numpy as np
        image = np.full((120, 160, 3), 255, np.uint8)
        for x in (40, 52, 64, 76):                            # a word of small print, letters 2 px apart
            image[50:62, x:x + 10] = 0
        cleaned = np.zeros((120, 160), bool)
        cleaned[40:66, 56:100] = True                         # the title's mask, over the last letters
        self.assertFalse(speed.cut_marks(image, cleaned, cleaned, np.array([255, 255, 255])).any())

    def test_large_drawing_touching_the_mask_stays(self):
        engine, seen = self.engine()
        image, mask = self.vein(2 * speed.MARK_SIZE + 20)
        out = asyncio.run(engine._run_inpainting(None, SimpleNamespace(img_rgb=image, mask=mask)))
        self.assertTrue((out[mask == 0] == image[mask == 0]).all())  # the drawing outside the mask stays

    def test_outline_running_under_the_mask_still_goes_to_the_model(self):
        engine, seen = self.engine()
        image, mask, _ = self.outlined_bubble(gap=0)
        image[116:144, 60:62] = 0                             # outline side crossing into the mask
        mask[116:144, 60:96] = 255
        asyncio.run(engine._run_inpainting(None, SimpleNamespace(img_rgb=image, mask=mask)))
        self.assertEqual(len(seen), 1)

    def test_specks_of_dust_beside_the_text_do_not_send_the_bubble_to_the_model(self):
        # Grand Blue 106 p22: a few specks of the scan's dust next to the letters spoiled the band
        # beside them; the model painted a grey ghost of the whole speech over the bubble.
        import numpy as np
        engine, seen = self.engine()
        image, mask, outline = self.outlined_bubble(gap=3)
        for x in range(100, 300, 14):                         # isolated specks, 1 px from the mask
            image[145, x] = image[114, x + 7] = 90
        image[144:146, 120:132] = image[114:116, 200:210] = 244  # and the scan's faint noise beside the letters
        out = asyncio.run(engine._run_inpainting(None, SimpleNamespace(img_rgb=image, mask=mask)))
        self.assertEqual(seen, [])
        self.assertTrue((out[116:144, 96:304] == 255).all())
        self.assertTrue((out[145, 100] == 90).all())          # the dust outside the mask is left as it is

    def test_light_screentone_still_goes_to_the_model(self):
        import numpy as np
        engine, seen = self.engine()
        image, mask, _ = self.outlined_bubble(gap=3)
        tone = np.full((60, 240), 255, np.uint8)
        tone[::4, ::4] = 0                                    # a light tone, 1 dot in 16 px
        image[100:160, 80:320] = np.where(mask[100:160, 80:320, None] > 0, image[100:160, 80:320], tone[..., None])
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
