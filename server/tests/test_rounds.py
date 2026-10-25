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

    def test_column_beside_the_last_line_stays_apart(self):
        # One Piece 1161 p4: a caption box with columns side by side, the right one starting higher.
        # Joined as "a word after the last line", the OCR read the columns row by row, mixed.
        left = SimpleNamespace(xyxy=np.array([715, 144, 776, 199]), texts=["...OF THE LONG NIGHT."],
                               lines=np.array([[[727, 144], [764, 144], [764, 158], [727, 158]],
                                               [[718, 159], [776, 159], [776, 181], [718, 181]],
                                               [[715, 178], [772, 178], [772, 199], [715, 199]]]))
        right = SimpleNamespace(xyxy=np.array([791, 153, 854, 190]), texts=["...AND THE SEA..."],
                                lines=np.array([[[791, 153], [854, 153], [854, 170], [791, 170]],
                                                [[798, 170], [841, 170], [841, 190], [798, 190]]]))
        self.assertFalse(same_block(left, right))

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

    def test_non_breaking_hyphen_becomes_plain_hyphen(self):
        # The AI writes U+2011 in clitics; the lettering font has no glyph for it
        # and it was drawn as a box (Black Clover 374 p5, Grand Blue 102 p2).
        self.assertEqual(normalize_spacing("vamos enfrentá\u2011los juntos."), "vamos enfrentá-los juntos.")
        self.assertEqual(normalize_spacing("vamos enfrentá-los juntos."), "vamos enfrentá-los juntos.")
        self.assertEqual(normalize_spacing("Espera — não – agora."), "Espera — não – agora.")


if __name__ == "__main__":
    unittest.main()


class Round4Test(unittest.TestCase):
    """Round 4: dropped names, feminine narrator without evidence, "WANT..." -> "EU..."."""

    GLOSSARY = [{"source": "ARTHUR", "target": "Arthur", "gender": "m"},
                {"source": "ELEANOR", "target": "Eleanor"}, {"source": "SYLVIE", "target": "Sylvie"}]

    def test_dropped_name_and_unfounded_feminine_are_found(self):
        from quality import translation_problems
        notes = translation_problems(
            ["HELLO, GENERAL ARTHUR LEYWIN. ELEANOR. SYLVIE.", "I TOLD MYSELF IT WAS FINE.", "THE SAME THING."],
            ["Olá, General Arthur Leywin. E Sylvie.", "Eu disse a mim mesma que estava tudo bem.", "A mesma coisa."],
            self.GLOSSARY)
        self.assertEqual(len(notes), 2)
        self.assertIn("<|1|>", notes[0])
        self.assertIn("Eleanor", notes[0])
        self.assertIn("<|2|>", notes[1])

    def test_feminine_is_fine_with_a_woman_on_the_page_or_before(self):
        from quality import translation_problems
        self.assertEqual(translation_problems(["SHE SAID THANKS.", "THANK YOU."], ["Ela agradeceu.", "Obrigada."]), [])
        self.assertEqual(translation_problems(["THANK YOU."], ["Obrigada."], earlier="HER SWORD"), [])
        self.assertEqual(translation_problems(["ELLIE!", "THANK YOU."], ["Ellie!", "Obrigada."],
                                              [{"source": "ELLIE", "target": "Ellie", "gender": "f"}]), [])

    def test_short_hesitation_in_caps_is_fixed_but_a_shout_is_not(self):
        from quality import sentence_case
        self.assertEqual(sentence_case("EU..."), "Eu...")
        self.assertEqual(sentence_case("NÃO!"), "NÃO!")

    def test_gender_is_learned_with_the_term(self):
        from memory import WorkMemory, context_block, split_gender
        self.assertEqual(split_gender("Arthur (m)"), ("Arthur", "m"))
        self.assertEqual(split_gender("Ellie (f)"), ("Ellie", "f"))
        self.assertEqual(split_gender("núcleo de mana"), ("núcleo de mana", None))
        memory = WorkMemory()
        memory.record("TBATE", "1", 1, [], [("ARTHUR", "Arthur (m)")], "ARTHUR")
        memory.record("TBATE", "1", 2, [], [("ARTHUR", "Arthur")], "ARTHUR")
        memory.record("TBATE", "1", 3, [], [("ELLIE", "Ellie")], "ELLIE")
        memory.record("TBATE", "1", 4, [], [("ELLIE", "Ellie")], "ELLIE")
        memory.record("TBATE", "1", 5, [], [("ELLIE", "Ellie (f)")], "ELLIE")
        glossary = {g["source"]: g for g in memory.glossary("TBATE")}
        self.assertEqual(glossary["ARTHUR"], {"source": "ARTHUR", "target": "Arthur", "gender": "m"})
        self.assertEqual(glossary["ELLIE"]["gender"], "f")
        self.assertIn('"gender": "male"', context_block(memory.context("TBATE", "1", 6), "ARTHUR"))

    def test_answer_with_a_dropped_name_is_asked_again(self):
        import asyncio
        import engine_compat
        from test_providers import pool
        p, _, _ = pool()
        engine_compat._POOL = p
        engine_compat.set_page_context({"glossary": self.GLOSSARY, "previous": []})
        prompts = []

        async def request(to_lang, prompt, client=None, model=None):
            prompts.append(prompt)
            if len(prompts) == 1:
                return "<|1|>Olá, General Arthur Leywin. E Sylvie."
            return "<|1|>Olá, General Arthur Leywin. Eleanor. Sylvie."
        engine = SimpleNamespace(
            client=SimpleNamespace(max_retries=2),
            _assemble_prompts=lambda source, target, queries: [("prompt", len(queries))],
            _request_translation=request, rgx_capture="(.*)", extract_capture_groups=lambda text, regex: text)
        original_client = engine_compat.provider_client
        engine_compat.provider_client = lambda pool, provider: None
        try:
            result = asyncio.run(engine_compat.translate_byok(
                engine, "ENG", "PTB", ["HELLO, GENERAL ARTHUR LEYWIN. ELEANOR. SYLVIE."]))
        finally:
            engine_compat.provider_client = original_client
            engine_compat._POOL = None
            engine_compat.set_page_context(None)
        self.assertEqual(result, ["Olá, General Arthur Leywin. Eleanor. Sylvie."])
        self.assertEqual(len(prompts), 2)
        self.assertIn("Eleanor", prompts[1])


class StaircaseLineTest(unittest.TestCase):
    """236 p32: "THAT ENOUGH, GREY" touches "ARTHUR, AND" below it; neither line was read."""

    def test_touching_lines_of_a_staircase_caption_are_both_added(self):
        from quality import repair_lines
        mask = np.zeros((300, 600), np.uint8)
        for x0 in range(40, 300, 22):
            mask[60:90, x0:x0 + 16] = 255       # "TELL YOURSELF", already a box
        for x0 in range(10, 330, 22):
            mask[107:137, x0:x0 + 16] = 255     # "THAT ENOUGH, GREY"
        for x0 in range(250, 480, 22):
            mask[126:156, x0:x0 + 16] = 255     # "ARTHUR, AND", touching from below
        mask[130:140, 250:330] = 255            # the strike over GREY joins them
        _, changes = repair_lines(mask, [(40, 60, 300, 90)])
        added = changes[0][2]
        self.assertEqual(len(added), 2)
        first, second = sorted(added, key=lambda b: b[1])
        self.assertLess(first[0], 20)
        self.assertLessEqual(first[3] - first[1], 32)
        self.assertGreater(second[0], 240)
        self.assertGreater(second[1], 110)

    def test_one_detector_box_over_both_staircase_lines_is_split(self):
        from quality import repair_lines
        mask = np.zeros((300, 600), np.uint8)
        for x0 in range(40, 300, 22):
            mask[60:90, x0:x0 + 16] = 255
        for x0 in range(10, 330, 22):
            mask[107:137, x0:x0 + 16] = 255
        for x0 in range(250, 480, 22):
            mask[126:156, x0:x0 + 16] = 255
        mask[130:140, 250:330] = 255
        for x0 in range(220, 520, 22):
            mask[170:200, x0:x0 + 16] = 255     # "YOU MIGHT START"
        _, changes = repair_lines(mask, [(40, 60, 300, 90), (5, 102, 485, 160), (220, 170, 520, 200)])
        self.assertEqual(changes[0][0], "split")
        first, second = sorted(changes[0][2], key=lambda b: b[1])
        self.assertEqual((first[1], first[3]), (107, 137))
        self.assertEqual((second[1], second[3]), (126, 156))
        self.assertGreater(second[0], 240)


class RetiredModelTest(unittest.TestCase):
    def test_saved_second_groq_with_the_retired_llama_moves_to_gpt_oss_20b(self):
        import json
        from providers import parse_secret
        saved = json.dumps({"providers": [{"name": "groq-llama", "base": "https://api.groq.com/openai/v1",
                                           "model": "llama-3.3-70b-versatile", "key": "gsk_x"}]})
        self.assertEqual(parse_secret(saved)[0]["name"], "groq-2")
        self.assertEqual(parse_secret(saved)[0]["model"], "openai/gpt-oss-20b")

    def test_saved_mistral_and_github_keys_are_skipped(self):
        """16/10: free Mistral answered 429 with 0 requests allowed; GitHub Models a plain "OK"."""
        import json
        from providers import parse_secret
        item = lambda n, b: {"name": n, "base": b, "model": "m", "key": "k" * 24}
        saved = json.dumps({"providers": [item("groq", "https://api.groq.com/openai/v1"),
                                          item("mistral", "https://api.mistral.ai/v1"),
                                          item("github", "https://models.github.ai/inference")]})
        self.assertEqual([p["name"] for p in parse_secret(saved)], ["groq"])
        with self.assertRaises(ValueError):
            parse_secret(json.dumps({"providers": [item("mistral", "https://api.mistral.ai/v1")]}))

    def test_groq_gpt_oss_thinks_briefly(self):
        """Groq counts GPT-OSS thinking against 8,000 free tokens per minute."""
        import asyncio
        from types import SimpleNamespace
        from engine_compat import request_byok_translation
        sent = []

        async def create(**kwargs):
            sent.append(kwargs)
            message = SimpleNamespace(content="<|1|>Oi")
            return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")], usage=None)
        translator = SimpleNamespace(chat_system_template="S {to_lang}", get_chat_sample=lambda lang: None,
                                     _MAX_TOKENS=100, temperature=.2, top_p=1, token_count=0)
        for base, model, short in (("https://api.groq.com/openai/v1", "openai/gpt-oss-120b", True),
                                   ("https://api.groq.com/openai/v1", "other", False),
                                   ("https://openrouter.ai/api/v1", "openai/gpt-oss-120b", False)):
            client = SimpleNamespace(base_url=base, chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
            asyncio.run(request_byok_translation(translator, "PTB", "<|1|>Hi", client, model))
            self.assertEqual(sent[-1].get("extra_body"), {"reasoning_effort": "low"} if short else None)


class ReserveTest(unittest.TestCase):
    """Round 6: gpt-oss-20b (groq-2) translated worse; an address answered a plain "OK"."""

    def providers(self):
        base = "https://api.example.com/v1"
        return [{"name": n, "base": base, "model": "m", "key": "k"} for n in ("groq", "groq-2", "gemini")]

    def test_reserves_stay_out_of_the_turns(self):
        import asyncio
        from providers import ProviderPool
        logs = []
        pool = ProviderPool(self.providers(), clock=lambda: 0.0, log=logs.append, take_turns=True)
        used = [asyncio.run(pool.run(lambda p: asyncio.sleep(0, p["name"]))) for _ in range(4)]
        self.assertEqual(used, ["groq", "gemini", "groq", "gemini"])
        self.assertIn("BYOK: página traduzida por groq", logs)

    def test_reserves_take_over_when_the_others_rest(self):
        import asyncio
        from providers import ProviderPool, NotAnAnswer
        pool = ProviderPool(self.providers(), clock=lambda: 0.0, log=lambda m: None, take_turns=True)

        async def attempt(p):
            if p["name"] in ("groq", "gemini"):
                raise NotAnAnswer("x")
            return p["name"]
        self.assertEqual(asyncio.run(pool.run(attempt)), "groq-2")
        self.assertGreater(pool.resting["groq"], 1000)  # not a chat API: long pause


class ReserveWaitTest(unittest.TestCase):
    """ouro-8: gpt-oss-20b got 7 of 11 pages while Gemini and Groq were at a per-minute limit."""

    def pool(self, now):
        from providers import ProviderPool
        base = "https://api.example.com/v1"
        providers = [{"name": n, "base": base, "model": "m", "key": "k"} for n in ("groq", "groq-2", "gemini")]
        slept = []

        async def sleep(seconds):
            slept.append(seconds)
            now[0] += seconds
        return ProviderPool(providers, clock=lambda: now[0], log=lambda m: None, take_turns=True, sleep=sleep), slept

    def test_short_limit_waits_for_the_main_provider(self):
        import asyncio
        now = [0.0]
        pool, slept = self.pool(now)
        pool.resting.update({"groq": 30.0, "gemini": 50.0})
        self.assertEqual(asyncio.run(pool.run(lambda p: asyncio.sleep(0, p["name"]))), "groq")
        self.assertEqual(slept, [30.0])

    def test_daily_quota_still_uses_the_reserve(self):
        import asyncio
        now = [0.0]
        pool, slept = self.pool(now)
        pool.resting.update({"groq": 3600.0, "gemini": 3600.0})
        self.assertEqual(asyncio.run(pool.run(lambda p: asyncio.sleep(0, p["name"]))), "groq-2")
        self.assertEqual(slept, [])
