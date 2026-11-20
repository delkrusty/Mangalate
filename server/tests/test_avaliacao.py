"""Automatic round scoring (avaliacao.py) on synthetic rounds shaped like batch.py's output."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import avaliacao
from avaliacao import compare, corpus_commands, load_corpus, measure, problems, stayed_english, strip_offset

RNG = np.random.default_rng(7)
BOX = [120, 100, 280, 160]           # original text box inside the bubble
LINES = [[[130, 110], [270, 110], [270, 125], [130, 125]], [[130, 135], [270, 135], [270, 150], [130, 150]]]


def art_page(height=600, width=400):
    """Textured art with a white bubble around BOX and black letters on its two lines."""
    # Same art on every call, so two rounds of the same page only differ where a test says.
    art = np.random.default_rng(7).integers(40, 220, (height // 8, width // 8, 3), dtype=np.uint8)
    page = np.kron(art, np.ones((8, 8, 1), np.uint8))
    cv2.ellipse(page, (200, 130), (110, 60), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(page, (200, 130), (110, 60), 0, 0, 360, (0, 0, 0), 2)
    return page


def letters_on(page, color=(0, 0, 0)):
    out = page.copy()
    for quad in LINES:
        (x0, y0), (x1, y1) = quad[0], quad[2]
        for x in range(x0 + 2, x1 - 6, 12):
            cv2.rectangle(out, (x, y0 + 2), (x + 6, y1 - 2), color, -1)
    return out


def write(path, image):
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), image)


def build_run(folder, *, erase_far=False, draw_far_on_flat=False, ghost=False,
              original_text="WHERE ARE YOU GOING", translation="Aonde você vai?", font_size=20, borrowed=0):
    """One-page round: originals/, translated/, review.json and diagnostico/0001/."""
    blank = art_page()
    original = letters_on(blank)
    clean = blank.copy()
    if ghost:
        clean = letters_on(blank, color=(150, 150, 150))
    translated = letters_on(blank, color=(30, 30, 30))   # the translation, drawn in the bubble
    if erase_far:
        translated[420:470, 40:110] = 255                 # white patch over the art, far from text
    if draw_far_on_flat:
        original[500:560, 250:390] = 0
        translated[500:560, 250:390] = 0
        cv2.putText(translated, "Kim!", (260, 545), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)
    write(folder / "originals" / "0001.png", original)
    write(folder / "translated" / "0001.png", translated)
    diag = folder / "diagnostico" / "0001"
    above = RNG.integers(0, 255, (borrowed, original.shape[1], 3), dtype=np.uint8)
    shift = lambda image: np.concatenate([above, image]) if borrowed else image
    write(diag / "1-original.png", shift(original))
    write(diag / "5-limpa.png", shift(clean))
    x0, y0, x1, y1 = BOX
    rows = [{"regiao": 1, "estado": "traduzida", "caixa": [x0, y0 + borrowed, x1, y1 + borrowed],
             "linhas": [[[x, y + borrowed] for x, y in quad] for quad in LINES],
             "fundo": {"kind": "interior"}, "ocr": original_text, "textos": [], "traducao": translation,
             "letra": {"tamanho": font_size, "original": 15}}]
    (diag / "regioes.json").write_text(json.dumps(rows), encoding="utf-8")
    entry = {"page": "0001.png", "status": "review", "seconds": 3.0,
             "regions": [{"original": original_text, "translation": translation}]}
    (folder / "review.json").write_text(json.dumps([entry]), encoding="utf-8")
    return folder


class StayedEnglish(unittest.TestCase):
    def test_translated_line_passes(self):
        self.assertFalse(stayed_english("WHERE ARE YOU GOING?", "Aonde você vai?"))

    def test_identical_or_empty_is_flagged(self):
        self.assertTrue(stayed_english("WHAT?", "WHAT?"))
        self.assertTrue(stayed_english("I KNEW IT", ""))

    def test_mostly_english_answer_is_flagged(self):
        self.assertTrue(stayed_english("WHERE ARE YOU GOING", "Where are you going, Kai?"))

    def test_words_shared_by_both_languages_pass(self):
        # Sound effects, laughs and names are written the same in Portuguese.
        self.assertFalse(stayed_english("BLA", "BLA"))
        self.assertFalse(stayed_english("HA HA", "HA HA"))
        self.assertFalse(stayed_english("MARCUS!", "MARCUS!"))
        self.assertFalse(stayed_english("...!?", ""))


class ScorePage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def score(self, **kwargs):
        run = build_run(self.root / "r", **kwargs)
        return measure(self.root)["trechos"]["r"][0]

    def test_good_page_has_no_problems(self):
        page = self.score()
        self.assertEqual(problems(page), dict.fromkeys(problems(page), 0))

    def test_art_erased_far_from_text_is_flagged(self):
        page = self.score(erase_far=True)
        self.assertEqual(page["arte_longe"]["manchas"], 1)
        x0, y0, x1, y1 = page["arte_longe"]["caixas"][0]
        self.assertTrue(x0 <= 40 + 2 and y0 <= 420 + 2 and x1 >= 110 - 2 and y1 >= 470 - 2)

    def test_text_drawn_on_flat_background_is_not_lost_art(self):
        self.assertEqual(self.score(draw_far_on_flat=True)["arte_longe"]["manchas"], 0)

    def test_ghost_letters_after_cleaning_are_flagged(self):
        self.assertEqual(len(self.score(ghost=True)["restos"]), 1)

    def test_clean_gradient_window_has_no_leftovers(self):
        # A system window fading from light to dark blue, cleaned perfectly.
        clean = np.zeros((200, 300, 3), np.uint8)
        clean[:, :, 0] = np.linspace(250, 90, 200, dtype=np.uint8)[:, None]
        row = {"caixa": [0, 0, 300, 200], "linhas": [[[20, 20], [280, 20], [280, 180], [20, 180]]]}
        self.assertLess(avaliacao.leftover_share(clean, row), avaliacao.LEFTOVER_SHARE)

    def test_speech_left_in_english_is_flagged(self):
        page = self.score(translation="Where are you going?")
        self.assertEqual(page["fala_ingles"], ["WHERE ARE YOU GOING"])

    def test_small_lettering_is_flagged_and_close_size_is_not(self):
        self.assertEqual(len(self.score(font_size=12)["letra_pequena"]), 1)   # 0.7*12/15 = 0.56

    def test_close_size_passes(self):
        self.assertEqual(self.score(font_size=20)["letra_pequena"], [])       # 0.7*20/15 = 0.93

    def test_seam_rows_borrowed_above_are_found(self):
        # A stitched webtoon strip starts with rows of the page above; boxes use strip rows.
        page = self.score(borrowed=90, erase_far=True)
        self.assertEqual(page["arte_longe"]["manchas"], 1)
        self.assertEqual(problems(page)["restos"], 0)

    def test_strip_offset(self):
        page = art_page()
        strip = np.concatenate([np.zeros((37, page.shape[1], 3), np.uint8), page])
        self.assertEqual(strip_offset(strip, page), 37)
        self.assertEqual(strip_offset(page, page), 0)

    def test_failed_page_counts_once(self):
        run = build_run(self.root / "r")
        entries = json.loads((run / "review.json").read_text())
        entries[0]["status"] = "blocked_original_preserved"
        (run / "review.json").write_text(json.dumps(entries))
        self.assertEqual(problems(measure(self.root)["trechos"]["r"][0]), {"falhou": 1})


class Compare(unittest.TestCase):
    def test_regression_and_totals_over_shared_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            before, after = Path(tmp) / "antes", Path(tmp) / "depois"
            build_run(before / "manga")
            build_run(before / "so-antes", ghost=True)       # stretch missing from the new round
            build_run(after / "manga", erase_far=True)
            diff = compare(before, after)
        self.assertEqual(diff["piorou"], ["manga/0001.png"])
        self.assertEqual(diff["antes"]["restos"], 0)        # the missing stretch is not a gain
        self.assertEqual(diff["depois"]["arte_longe"], 1)
        self.assertEqual(diff["faltando"], ["so-antes"])
        self.assertGreater(diff["paginas"][0]["mudou"], 0)

    def test_same_round_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            build_run(Path(tmp) / "a" / "x")
            build_run(Path(tmp) / "b" / "x")
            diff = compare(Path(tmp) / "a", Path(tmp) / "b")
        self.assertEqual(diff["piorou"], [])
        self.assertEqual(diff["paginas"][0]["mudou"], 0.0)


class Corpus(unittest.TestCase):
    def test_commands_follow_the_test_round(self):
        item = {"id": "pb-1", "capitulo": "cap.cbz", "paginas": "5-10", "obra": "Obra"}
        (_, command), = corpus_commands([item], "base", gpu=False, workdir=Path("/srv"))
        self.assertIn("translator-cpu", command)
        self.assertEqual(command[command.index("--input") + 1], "/work/teste/cap.cbz")
        self.assertEqual(command[command.index("--output") + 1], "/work/teste-curto/base/pb-1")
        self.assertIn("--diagnostics", command)
        self.assertIn("--no-memory", command)   # rounds stay comparable
        (_, remembering), = corpus_commands([dict(item, memoria=True)], "base", workdir=Path("/srv"))
        self.assertNotIn("--no-memory", remembering)
        self.assertNotIn("--gpu", command)
        (_, gpu), = corpus_commands([item], "base", gpu=True, workdir=Path("/srv"))
        self.assertIn("translator-gpu", gpu)
        self.assertIn("--gpu", gpu)

    def test_other_image_runs_through_an_override(self):
        item = {"id": "pb-1", "capitulo": "cap.cbz", "paginas": "1"}
        (_, command), = corpus_commands([item], "base", workdir=Path("/srv"), override=Path("/srv/o.yml"))
        self.assertEqual(command[:6], ["docker", "compose", "-f", str(Path("/srv/docker-compose.yml")),
                                       "-f", str(Path("/srv/o.yml"))])
        self.assertIn("image: mangalate-translator-cpu:base",
                      avaliacao.image_override("translator-cpu", "mangalate-translator-cpu:base"))
        with self.assertRaises(ValueError):
            avaliacao.image_override("translator-cpu", "x:y\n  privileged: true")

    def test_paths_outside_the_test_folder_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "corpus.json"
            for bad in ({"id": "a", "capitulo": "../x.cbz", "paginas": "1"},
                        {"id": "../a", "capitulo": "x.cbz", "paginas": "1"}):
                path.write_text(json.dumps([bad]))
                with self.assertRaises(ValueError):
                    load_corpus(path)
            path.write_text(json.dumps([{"id": "a", "capitulo": "x.cbz", "paginas": "1"}] * 2))
            with self.assertRaises(ValueError):
                load_corpus(path)


if __name__ == "__main__":
    unittest.main()
