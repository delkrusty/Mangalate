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

    def haloed_page(self, over_art, tone=170, dots=False):
        """Dark letters with a white halo over cross-hatched shading (or screentone), as a "tracos" block."""
        import cv2
        import numpy as np
        image = np.full((260, 420, 3), tone, np.uint8)
        if dots:
            image[1::4, 1::4] = 40
            image[2::4, 1::4] = 40
        else:
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

    def test_drawing_between_the_lines_of_a_block_marked_whole_stays(self):
        # BC374 p13, Grand Blue 106 p31: the detector marked the block over the drawing as one
        # patch; cleaned whole, the speed lines and screentone between the lines came back as a
        # smear, and the black beside a light part spread over it.
        import cv2
        import numpy as np
        for dots in (False, True):
            image, mask, raw, region = self.haloed_page(over_art=True, dots=dots)
            letters = raw > 0
            whole = np.zeros_like(raw)
            whole[45:130, 92:280] = 255                       # the detector's patch over the block
            page, left = speed.paint_halos(image, mask, [region], whole)
            self.assertTrue((left[letters] > 0).all())       # every letter, dots of "..." too, is cleaned
            # Past the halo (3 px), the letters' rim and the model's soft edge around them.
            between = (image.max(axis=2) < 100) & (cv2.dilate(raw, np.ones((19, 19), np.uint8)) == 0)
            between[:45] = between[130:] = False
            between[:, :92] = between[:, 280:] = False
            self.assertTrue(between.any())
            self.assertFalse(left[between].any())            # the drawing between the lines stays
            self.assertTrue((page[between] == image[between]).all())
            # The room of the translation is still the whole block (engine_compat.bubble_layout).
            from quality import halo_paint
            self.assertTrue(np.array_equal(region.mangalate_halo_area, halo_paint(image, whole, region.lines)[0]))

    def test_a_dot_with_a_thin_halo_on_a_line_of_a_block_marked_whole_is_cleaned(self):
        # BC374 p6 and p13: the halo around the dots of a colon and a full stop was a pixel or two,
        # thinner than where it is read; taken for screentone, the dots stayed over the translation.
        import cv2
        import numpy as np
        for dots in (False, True):
            image, mask, raw, region = self.haloed_page(over_art=True, dots=dots)
            dot = np.zeros_like(raw)
            cv2.circle(dot, (220, 96), 2, 255, -1)                # after "I DESERVE", on its line
            image[(cv2.dilate(dot, np.ones((3, 3), np.uint8)) > 0) & (dot == 0)] = 255   # a 1 px halo
            image[dot > 0] = 0
            region.lines[1][1][0] = region.lines[1][2][0] = 226   # the line box takes the dot in
            whole = np.zeros_like(raw)
            whole[45:130, 92:280] = 255
            page, left = speed.paint_halos(image, mask, [region], whole)
            self.assertTrue((left[dot > 0] > 0).all())
            self.assertTrue((left[raw > 0] > 0).all())

    def test_letter_of_a_bubble_running_past_its_box_beside_a_haloed_speech_stays_with_the_model(self):
        # Grand Blue 102 p33: the "T" of the bubble beside "I'LL HAVE THE DRINKS" ran 4 px left of
        # its box, into the margin of the haloed speech; that edge was left out of the model's mask,
        # and the model drew a grey ghost of it.  The drawing beyond the other box stays, and so does
        # the outline of a bubble just past its box (manga p15, "LET'S DO IT!").
        import numpy as np
        image, mask, raw, region = self.haloed_page(over_art=True)
        image[45:130, 274:420] = 255                          # the bubble beside it
        image[62:78, 276:300] = 0                             # its first letter, 4 px out of its box
        image[80:130, 277:279] = 0                            # its outline, 2 px from its box, under the letter
        mask[78:130, 275:281] = 255
        mask[58:82, 274:304] = 255
        bubble = SimpleNamespace(lines=np.array([[[280, 60], [400, 60], [400, 80], [280, 80]]]),
                                 xyxy=(280, 60, 400, 80), font_size=18, mangalate_background={"kind": "interior"})
        left = speed.paint_halos(image, mask, [region, bubble], raw)[1]
        self.assertTrue((left[62:78, 276:280] > 0).all())
        hatching = image[22:34, 276:285].max(axis=2) < 100   # above the bubble, in the speech's margin
        self.assertTrue(hatching.any())
        self.assertFalse(left[22:34, 276:285][hatching].any())
        self.assertFalse(left[80:86, 277:279].any())

    def test_the_translation_of_a_haloed_speech_takes_the_colour_of_its_letters(self):
        # Grand Blue 106 p31, BC374 p6: the engine's guess for letters with a halo came out grey
        # (115 for black letters), or with a grey rim around them, and the translation was written so.
        import numpy as np
        image, mask, raw, region = self.haloed_page(over_art=True)
        image[raw > 0] = (20, 30, 90)                          # dark blue letters
        region.fg_colors, region.bg_colors = np.array([115, 115, 115]), np.array([157, 157, 157])
        speed.paint_halos(image, mask, [region], raw)
        self.assertEqual(tuple(region.fg_colors), (20, 30, 90))
        self.assertEqual(tuple(region.bg_colors), (255, 255, 255))   # its border, the halo
        # A speech not over the drawing keeps the engine's colours.
        image, mask, raw, region = self.haloed_page(over_art=False)
        region.fg_colors, region.bg_colors = np.array([115, 115, 115]), np.array([157, 157, 157])
        speed.paint_halos(image, mask, [region], raw)
        self.assertEqual(tuple(region.fg_colors), (115, 115, 115))
        self.assertEqual(tuple(region.bg_colors), (157, 157, 157))

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


class GhostTest(unittest.TestCase):
    """Manga teste 2 p4, p7: the model left a grey ghost of the letters in narrow white bubbles.

    The mask reached the outline of the bubble, so the bubble was not filled flat
    (split_flat), and the model drew faint letters back where "I'LL / TALK / TO THE /
    CAFE- / -TERIA..." was.  Inside the bubble, what the model left light is paper.
    """

    @staticmethod
    def page():
        import cv2
        import numpy as np
        image = np.full((300, 300, 3), 140, np.uint8)               # grey drawing around
        cv2.ellipse(image, (150, 150), (40, 110), 0, 0, 360, (252, 252, 252), -1)
        cv2.ellipse(image, (150, 150), (40, 110), 0, 0, 360, (0, 0, 0), 3)
        for y in range(70, 230, 20):
            cv2.putText(image, "ABC", (125, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)
        mask = np.zeros((300, 300), np.uint8)
        mask[55:235, 105:196] = 255                                  # up to the outline and past it
        region = SimpleNamespace(xyxy=(120, 55, 180, 235), lines=np.array([[[120, 55], [180, 55], [180, 235], [120, 235]]]),
                                 mangalate_background={"kind": "interior"})
        return image, mask, region

    def test_light_ghost_in_the_bubble_becomes_paper(self):
        import numpy as np
        image, mask, region = self.page()
        cleaned = image.copy()
        cleaned[mask > 0] = 200                                      # the model's faint letters
        cleaned[60:240, 108:112] = 0                                 # and the outline it drew back
        out = speed.settle_ghosts(cleaned, image, mask, [region])
        inside = np.zeros(mask.shape, bool)
        inside[80:220, 130:170] = True
        self.assertTrue((out[inside] == 252).all())
        self.assertTrue((out[60:240, 108:112] == 0).all())          # dark strokes stay
        self.assertTrue((out[150, 105:107] == 200).all())          # past the outline: the drawing, as the model left it

    def test_ghost_on_the_last_line_of_an_open_bubble_becomes_paper(self):
        # Manga teste 2 p6: a white flash bubble open into the gutter; the interior stopped at the
        # text box, and "CLOSER", touching its bottom edge, was no hole of the interior: the grey
        # the model drew there stayed and split the room of the translation.
        import cv2
        import numpy as np
        image = np.full((300, 300, 3), 140, np.uint8)
        image[:, 60:240] = 252                                       # white down to the page edge
        lines = []
        for k, y in enumerate((100, 130, 160)):
            cv2.putText(image, "WORD", (110, y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 3)
            lines.append([[105, y - 22], [195, y - 22], [195, y + 3], [105, y + 3]])
        region = SimpleNamespace(xyxy=(105, 78, 195, 162), lines=np.array(lines),
                                 mangalate_background={"kind": "interior"})
        mask = np.zeros((300, 300), np.uint8)
        mask[74:168, 100:200] = 255
        cleaned = image.copy()
        cleaned[mask > 0] = 252
        cleaned[140:165, 115:185] = 180                              # the ghost of the last line
        out = speed.settle_ghosts(cleaned, image, mask, [region])
        self.assertTrue((out[140:162, 115:185] == 252).all())
        self.assertTrue((out[:, :55] == 140).all())                  # the drawing beside stays

    def test_text_over_the_drawing_is_left_to_the_model(self):
        import numpy as np
        image, mask, region = self.page()
        region.mangalate_background = {"kind": "tracos"}
        cleaned = image.copy()
        cleaned[mask > 0] = 200
        self.assertTrue((speed.settle_ghosts(cleaned, image, mask, [region]) == cleaned).all())

    def test_speech_in_a_bubble_cut_by_the_frame_gets_paper(self):
        # Manga teste 2 p6: "AND AFTER THAT..." in a bubble the panel frame cuts read as strokes
        # ("tracos", a speech), was cleaned by the model and kept grey specks of its letters.
        image, mask, region = self.page()
        region.mangalate_background = {"kind": "tracos", "fala": True}
        cleaned = image.copy()
        cleaned[mask > 0] = 200
        out = speed.settle_ghosts(cleaned, image, mask, [region])
        self.assertFalse((out == cleaned).all())


class HaloKeptTest(unittest.TestCase):
    """A sticker caption or a turned or stacked column is painted flat with its halo: the model
    drew the art back under it as smears where the halo crossed the drawing (hair, a jacket)."""

    def test_sticker_and_turned_columns_are_painted_flat(self):
        for marks in ({"mangalate_sticker": ((255, 255, 255), (0, 0, 0))}, {"mangalate_turn": "cw"},
                      {"mangalate_turn": "ccw"}, {"mangalate_turn": "stack"}, {"mangalate_turn": "arc"}):
            self.assertTrue(speed.halo_kept(SimpleNamespace(**marks)), marks)
        # A line along a curve too (Manga teste 2 p3): its block is the band under the curve's
        # chord, and the model drew a hand inside it back as a smear.
        for marks in ({}, {"mangalate_turn": None}, {"mangalate_sticker": None}):
            self.assertFalse(speed.halo_kept(SimpleNamespace(**marks)), marks)

    def test_a_flat_halo_sends_nothing_to_the_model(self):
        import numpy as np
        image, mask, raw, region = FlatFillTest.haloed_page(None, over_art=True)
        region.mangalate_turn = "stack"
        page, left = speed.paint_halos(image, mask, [region], raw)
        self.assertFalse(left[40:135, 90:280].any())              # nothing of it left to the model
        self.assertTrue((page[raw > 0] == 255).all())            # the old letters painted with the halo
        # The same speech not turned: its letters and halo go to the model.
        image, mask, raw, region = FlatFillTest.haloed_page(None, over_art=True)
        left = speed.paint_halos(image, mask, [region], raw)[1]
        self.assertTrue((left[raw > 0] > 0).all())


class FlatHaloTest(unittest.TestCase):
    def test_a_turned_word_keeps_a_light_pattern_away_from_its_letters(self):
        # A stacked word over paper with a light drawn pattern (small animals, flowers): painted
        # flat to the whole light ground, the pattern was wiped white far past the letters.
        import cv2
        import numpy as np
        image = np.full((300, 200, 3), 255, np.uint8)
        image[::14, :] = 215                                      # pale pattern lines on the paper
        raw = np.zeros((300, 200), np.uint8)
        for k, ch in enumerate("ABC"):
            cv2.putText(raw, ch, (85, 70 + 70 * k), cv2.FONT_HERSHEY_DUPLEX, 1.6, 255, 5)
        halo = cv2.dilate(raw, np.ones((9, 9), np.uint8)) > 0
        image[halo] = 255
        image[raw > 0] = 0
        mask = cv2.dilate(raw, np.ones((11, 11), np.uint8))
        region = SimpleNamespace(lines=np.array([[[75, 25], [125, 25], [125, 230], [75, 230]]]), xyxy=(75, 25, 125, 230),
                                 font_size=40, mangalate_background={"kind": "tracos", "fala": True, "sobre_arte": True},
                                 mangalate_turn="stack")
        page = speed.paint_halos(image, mask, [region], raw)[0]
        far = (image.min(axis=2) == 215) & (cv2.dilate(raw, np.ones((41, 41), np.uint8)) == 0)
        self.assertTrue(far.any())
        self.assertTrue((page[far] == image[far]).all())          # the pattern away from the letters stays
        self.assertTrue((page[raw > 0] == 255).all())             # the old letters go

    def test_a_stacked_letter_touching_a_strand_of_hair_goes_too(self):
        # Manga teste 2 p11: the "S" of a stacked word over hair, its halo crossed by a dark strand,
        # was taken for the drawing (quality.halo_drawing) and left whole under the translation.
        import cv2
        import numpy as np
        image = np.full((300, 200, 3), 120, np.uint8)             # grey hair
        raw = np.zeros((300, 200), np.uint8)
        for k, ch in enumerate("ABS"):
            cv2.putText(raw, ch, (85, 70 + 70 * k), cv2.FONT_HERSHEY_DUPLEX, 1.6, 255, 5)
        halo = cv2.dilate(raw, np.ones((9, 9), np.uint8)) > 0
        image[halo] = 255
        image[raw > 0] = 0
        cv2.line(image, (40, 215), (160, 185), (0, 0, 0), 4)       # a strand across the last letter
        mask = cv2.dilate(raw, np.ones((11, 11), np.uint8))
        region = SimpleNamespace(lines=np.array([[[75, 25], [125, 25], [125, 230], [75, 230]]]), xyxy=(75, 25, 125, 230),
                                 font_size=40, mangalate_background={"kind": "tracos", "fala": True, "sobre_arte": True},
                                 mangalate_turn="stack")
        page = speed.paint_halos(image, mask, [region], raw)[0]
        self.assertTrue((page[raw > 0] == 255).all())             # every old letter goes
        self.assertTrue((page[10:20, 30:60] == 120).all())        # the hair away from them stays

    def test_a_sticker_loses_the_grey_rims_of_its_old_letters(self):
        import cv2
        import numpy as np
        image = np.full((200, 400, 3), 20, np.uint8)               # a dark jacket
        cv2.rectangle(image, (60, 60), (340, 140), (255, 255, 255), -1)
        raw = np.zeros((200, 400), np.uint8)
        cv2.putText(raw, "SERIES", (100, 115), cv2.FONT_HERSHEY_DUPLEX, 1.5, 255, 5)
        outline = (cv2.dilate(raw, np.ones((5, 5), np.uint8)) > 0) & (raw == 0)
        rim = (cv2.dilate(raw, np.ones((7, 7), np.uint8)) > 0) & (raw == 0) & ~outline
        image[outline] = 25                                        # the dark outline of light capitals...
        image[rim] = (190, 190, 190)                               # ...and its soft grey rim
        image[raw > 0] = 240
        mask = cv2.dilate(raw, np.ones((5, 5), np.uint8))
        quads = np.array([[[95, 80], [310, 80], [310, 122], [95, 122]]])
        region = SimpleNamespace(lines=quads, xyxy=(95, 80, 310, 122), font_size=30,
                                 mangalate_background={"kind": "tracos", "fala": True, "sobre_arte": True},
                                 mangalate_sticker=((255, 255, 255), (0, 0, 0)))
        page = speed.paint_halos(image, mask, [region], raw)[0]
        self.assertFalse((page[rim] == 190).all(axis=1).any())     # no grey rim left
        self.assertTrue((page[:40] == 20).all())                   # the jacket stays
