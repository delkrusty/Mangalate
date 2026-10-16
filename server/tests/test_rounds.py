"""Failures found in the manhwa test rounds on the owner's PC."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine_compat import is_credit, join_split_blocks
from quality import join_blocks, normalize_spacing, same_block


def region(x0, y0, x1, y1, text, line=None):
    line = line or (y1 - y0)
    lines, y = [], y0
    while y + line <= y1 + 1:
        lines.append([[x0, y], [x1, y], [x1, y + line], [x0, y + line]])
        y += line
    return SimpleNamespace(xyxy=np.array([x0, y0, x1, y1]), lines=np.array(lines), texts=[text], text=text,
                           font_size=line, angle=0, prob=0.9, fg_colors=(0, 0, 0), bg_colors=(255, 255, 255),
                           horizontal=True)


def merged(a, b):
    return region(min(a.xyxy[0], b.xyxy[0]), a.xyxy[1], max(a.xyxy[2], b.xyxy[2]), b.xyxy[3], a.text + " " + b.text)


class SplitSpeechTest(unittest.TestCase):
    """OF 237 p62: one oval bubble read as two regions, both drawn over each other."""

    def test_line_right_below_joins(self):
        top = region(100, 100, 400, 160, "ALRIGHT, LET'S START THE REAL", line=30)
        bottom = region(190, 165, 310, 195, "TRAINING.", line=30)
        self.assertTrue(same_block(top, bottom))
        joined = join_blocks([bottom, top], merged)
        self.assertEqual([r.text for r in joined], ["ALRIGHT, LET'S START THE REAL TRAINING."])

    def test_separate_speeches_stay_apart(self):
        top = region(100, 100, 400, 160, "WHO ARE YOU?", line=30)
        self.assertFalse(same_block(top, region(100, 260, 400, 290, "FAR BELOW", line=30)))
        self.assertFalse(same_block(top, region(500, 165, 700, 195, "SIDE BY SIDE", line=30)))
        self.assertFalse(same_block(top, region(100, 165, 400, 245, "BIG SHOUT", line=80)))
        self.assertFalse(same_block(top, region(190, 165, 310, 195, "OTHER BUBBLE", line=30), lambda a, b: False))

    def test_only_when_the_page_shows_one_bubble(self):
        page = np.full((400, 600, 3), 90, np.uint8)
        import cv2
        cv2.ellipse(page, (250, 150), (220, 110), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(page, (250, 150), (220, 110), 0, 0, 360, (0, 0, 0), 4)
        top = region(110, 105, 390, 165, "ALRIGHT, LET'S START THE REAL", line=30)
        bottom = region(200, 170, 300, 200, "TRAINING.", line=30)

        class Block(SimpleNamespace):
            def __init__(self, lines, texts, **kw):
                lines = np.asarray(lines)
                super().__init__(lines=lines, texts=texts, text=" ".join(texts), horizontal=True,
                                 xyxy=np.array([lines[..., 0].min(), lines[..., 1].min(),
                                                lines[..., 0].max(), lines[..., 1].max()]),
                                 fg_colors=kw["fg_color"], bg_colors=kw["bg_color"], **{
                                     k: kw[k] for k in ("font_size", "angle", "prob")})
        top, bottom = (Block(r.lines, r.texts, font_size=r.font_size, angle=0, prob=0.9,
                             fg_color=(0, 0, 0), bg_color=(255, 255, 255)) for r in (top, bottom))
        joined = join_split_blocks([top, bottom], page)
        self.assertEqual([r.text for r in joined], ["ALRIGHT, LET'S START THE REAL TRAINING."])
        self.assertEqual(len(joined[0].lines), 3)
        # Two bubbles, one right under the other: kept apart.
        page2 = np.full((400, 600, 3), 90, np.uint8)
        cv2.rectangle(page2, (90, 90), (410, 168), (255, 255, 255), -1)
        cv2.rectangle(page2, (90, 168), (410, 172), (0, 0, 0), -1)
        cv2.rectangle(page2, (90, 172), (410, 230), (255, 255, 255), -1)
        self.assertEqual(len(join_split_blocks([top, bottom], page2)), 2)


class Round2Test(unittest.TestCase):
    def test_last_word_beside_the_last_line_joins(self):
        # OF 237 p62, coordinates from the diagnostics of round 2.
        top = SimpleNamespace(xyxy=np.array([281, 443, 660, 584]), texts=["ALRIGHT LETS START THE REAL"],
                              lines=np.array([[[379, 443], [551, 450], [550, 485], [377, 478]],
                                              [[282, 489], [660, 494], [659, 541], [281, 536]],
                                              [[304, 541], [431, 541], [431, 584], [304, 584]]]))
        word = SimpleNamespace(xyxy=np.array([422, 542, 626, 584]), texts=["TRAINING"],
                               lines=np.array([[[422, 542], [626, 545], [625, 584], [422, 581]]]))
        self.assertTrue(same_block(top, word))
        # A word on the same row but far away is another speech.
        far = SimpleNamespace(xyxy=np.array([700, 542, 800, 584]), texts=["NO"],
                              lines=np.array([[[700, 542], [800, 542], [800, 584], [700, 584]]]))
        self.assertFalse(same_block(top, far))

    def test_caps_answer_keeps_the_names_it_kept(self):
        from quality import sentence_case, source_names
        names = source_names("QUEEN MERIAL!", "RAINHA MERIAL!")
        self.assertEqual(sentence_case("RAINHA MERIAL CHEGOU AQUI!", names), "Rainha Merial chegou aqui!")
        self.assertEqual(source_names("THE REAL TRAINING", "O TREINO REAL"), set())

    def test_line_below_a_credit_stays(self):
        from engine_compat import credit_followers
        credit = region(100, 100, 500, 130, "Original Art by: YOYO,")
        below = region(100, 135, 400, 165, "EternalUwU, chacha")
        speech = region(100, 400, 400, 430, "Where are you?")
        follow = credit_followers([credit, below, speech])
        self.assertEqual(follow, {id(below)})


class Round3Test(unittest.TestCase):
    def test_credits_page_keeps_everything(self):
        from engine_compat import credits_page
        page = [region(0, 0, 10, 10, t) for t in ("tapayoriginal", "FTERTHEEND", "Producedby:MGK-story",
                                                  "Story and adaptation by: TurtleMe", "Original Art by: YOY")]
        self.assertTrue(credits_page(page))
        self.assertFalse(credits_page([region(0, 0, 10, 10, t) for t in ("Read at asurascans.com", "Run!")]))
        self.assertTrue(is_credit("Producedby:MGK-story"))
        self.assertTrue(is_credit("tapa..origina"))

    def test_start_of_the_translation(self):
        from quality import tidy_start
        self.assertEqual(tidy_start("M-ME LIGA assim que descobrir, tá?"), "M-me liga assim que descobrir, tá?")
        self.assertEqual(tidy_start("NÃO faça isso!"), "Não faça isso!")
        self.assertEqual(tidy_start("ARTHUR VEIO aqui.", names={"Arthur"}), "Arthur veio aqui.")
        self.assertEqual(tidy_start("OK, vamos."), "OK, vamos.")
        self.assertEqual(tidy_start("...Sendo sonho ou não.", "..DREAM OR NO DREAM"), "...sendo sonho ou não.")
        self.assertEqual(tidy_start("...Arthur voltou.", "..ARTHUR CAME BACK", {"Arthur"}), "...Arthur voltou.")
        self.assertEqual(tidy_start("...Certo.", "OKAY."), "...Certo.")


class RoundFixesTest(unittest.TestCase):
    def test_credit_lines_stay_as_drawn(self):
        self.assertTrue(is_credit("Original Art by: YOYO,"))
        self.assertTrue(is_credit("TL: someone"))
        self.assertFalse(is_credit("Stand by me."))
        self.assertFalse(is_credit("He did it by himself: alone."))

    def test_double_hyphen_becomes_dash(self):
        self.assertEqual(normalize_spacing("Eu-- eu não sei"), "Eu— eu não sei")
        self.assertEqual(normalize_spacing("Espera---"), "Espera---")


if __name__ == "__main__":
    unittest.main()
