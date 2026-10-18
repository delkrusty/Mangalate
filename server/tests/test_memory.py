"""Work memory: learned glossary and previous pages of the chapter (no network)."""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine_compat
from gateway import page_work
from memory import (WorkMemory, accept_terms, context_block, parse_work, relevant_glossary, remember,
                    split_terms)


def region(text, translation):
    return SimpleNamespace(text=text, text_raw=text, translation=translation)


class TermsTest(unittest.TestCase):
    def test_terms_line_is_removed_before_parsing(self):
        answer, terms = split_terms("<|1|>O restritor falhou.\n<|2|>Grey!\n<|termos|>RESTRAINER=restritor; GREY=Grey")
        self.assertEqual(answer, "<|1|>O restritor falhou.\n<|2|>Grey!")
        self.assertEqual(terms, [("RESTRAINER", "restritor"), ("GREY", "Grey")])
        self.assertEqual(engine_compat.parse_marked(answer, 2), ["O restritor falhou.", "Grey!"])

    def test_variant_spellings_of_the_terms_line(self):
        for line in ("Termos: GREY=Grey", "<termos> GREY=Grey", "<|TERMS|>GREY=Grey"):
            answer, terms = split_terms("<|1|>Oi, Grey.\n" + line)
            self.assertEqual(answer, "<|1|>Oi, Grey.", line)
            self.assertEqual(terms, [("GREY", "Grey")], line)

    def test_terms_on_the_last_bubble_line_are_cut_off(self):
        answer, terms = split_terms("<|1|>Oi, Grey. <|termos|>GREY=Grey")
        self.assertEqual((answer, terms), ("<|1|>Oi, Grey.", [("GREY", "Grey")]))

    def test_the_word_termos_inside_dialogue_is_kept(self):
        self.assertEqual(split_terms("<|1|>Nesses termos: aceito."), ("<|1|>Nesses termos: aceito.", []))

    def test_answer_without_terms_is_unchanged(self):
        self.assertEqual(split_terms("<|1|>Oi.\n<|2|>Tchau."), ("<|1|>Oi.\n<|2|>Tchau.", []))

    def test_only_terms_present_on_the_page_are_accepted(self):
        page = "THE RESTRAINER K MUST'VE MAL- FUNCTIONED. GREY!"
        terms = [("RESTRAINER", "restritor"), ("ARTHUR", "Arthur"), ("GREY", ""), ("X" * 80, "y"),
                 ("GREY", "<|1|>Grey")]
        self.assertEqual(accept_terms(terms, page), [("RESTRAINER", "restritor")])

    def test_pinned_terms_are_not_overridden(self):
        self.assertEqual(accept_terms([("GREY", "Cinza")], "GREY!", pinned=["Grey"]), [])


class MemoryTest(unittest.TestCase):
    def test_first_translation_of_a_term_wins_and_persists(self):
        with tempfile.TemporaryDirectory() as folder:
            memory = WorkMemory(folder)
            memory.record("TBATE", "Cap 236", 6, [], [("RESTRAINER", "restritor")], "THE RESTRAINER K")
            self.assertEqual(memory.glossary("TBATE"), [])  # one page is not enough
            memory.record("TBATE", "Cap 236", 6, [], [("RESTRAINER", "restritor")], "THE RESTRAINER K")
            self.assertEqual(memory.glossary("TBATE"), [])  # the same page again neither
            memory.record("TBATE", "Cap 236", 7, [], [("RESTRAINER", "restrainer")], "RESTRAINER KI")
            memory.record("TBATE", "Cap 236", 8, [], [("RESTRAINER", "outro")], "RESTRAINER")
            again = WorkMemory(folder)
            self.assertEqual(again.glossary("TBATE"), [{"source": "RESTRAINER", "target": "restritor"}])
            self.assertEqual(len(list(Path(folder).glob("*.json"))), 1)

    def test_previous_pages_come_from_the_same_chapter_and_before_the_page(self):
        memory = WorkMemory()
        for page in (1, 2, 3, 5):
            memory.record("Obra", "Cap 1", page, [{"original": f"P{page}", "translation": f"T{page}"}], [], "")
        memory.record("Obra", "Cap 2", 1, [{"original": "OTHER", "translation": "Outro"}], [], "")
        previous = memory.context("Obra", "Cap 1", 4)["previous"]
        self.assertEqual([p[0]["original"] for p in previous], ["P2", "P3"])
        self.assertEqual(memory.context("Obra", "Cap 1", 1)["previous"], [])
        self.assertIsNone(memory.context("", "Cap 1", 1))

    def test_only_recent_chapters_are_kept(self):
        memory = WorkMemory()
        for chapter in range(5):
            memory.record("Obra", f"Cap {chapter}", 1, [{"original": "A", "translation": "B"}], [], "")
        self.assertEqual(list(memory.load("Obra")["chapters"]), ["Cap 2", "Cap 3", "Cap 4"])

    def test_glossary_sent_is_only_what_the_page_uses(self):
        glossary = [{"source": "GREY", "target": "Grey"}, {"source": "MANA CORE", "target": "núcleo de mana"},
                    {"source": "ELIJAH", "target": "Elijah"}]
        self.assertEqual([g["source"] for g in relevant_glossary(glossary, "<|1|>MY MANA CORE, GREY...")],
                         ["GREY", "MANA CORE"])
        block = context_block({"glossary": glossary, "previous": []}, "<|1|>GREY?")
        self.assertIn('"GREY"', block)
        self.assertNotIn("ELIJAH", block)
        self.assertIn("<|termos|>", block)

    def test_remember_records_page_dialogue_and_terms(self):
        memory = WorkMemory()
        work = {"obra": "TBATE", "capitulo": "236", "pagina": 6}
        added = remember(memory, work, [region("THE RESTRAINER K", "O restritor K")], [("RESTRAINER", "restritor")])
        self.assertEqual(added, [])
        added = remember(memory, dict(work, pagina=7), [region("RESTRAINER", "Restritor")], [("RESTRAINER", "x")])
        self.assertEqual(added, [("RESTRAINER", "restritor")])
        self.assertEqual(memory.context("TBATE", "236", 7)["previous"][0][0]["translation"], "O restritor K")

    def test_word_cut_by_lettering_is_not_a_term(self):
        self.assertEqual(accept_terms([("WET- SUIT", "roupa de mergulho"), ("AZUSA-", "Azusa")],
                                      "WET- SUIT AZUSA- SAN"), [])


class WorkFieldTest(unittest.TestCase):
    def test_gateway_forwards_only_known_short_fields(self):
        forwarded = json.loads(page_work(json.dumps({"obra": " TBATE ", "capitulo": "236", "pagina": 6,
                                                     "gpt_config": "/etc/passwd"})))
        self.assertEqual(forwarded, {"obra": "TBATE", "capitulo": "236", "pagina": 6})
        self.assertEqual(page_work(json.dumps({"capitulo": "1"})), "")
        self.assertEqual(page_work(None), "")
        with self.assertRaises(ValueError):
            page_work("[1]")

    def test_worker_ignores_invalid_work(self):
        self.assertIsNone(parse_work("not json"))
        self.assertIsNone(parse_work(json.dumps({"obra": ""})))
        self.assertEqual(parse_work(json.dumps({"obra": "A", "pagina": True}))["pagina"], None)


class SoundEffectTest(unittest.TestCase):
    def test_kana_with_few_latin_letters_is_a_sound_effect(self):
        self.assertTrue(engine_compat.is_sound_effect("BOBふ。か"))
        self.assertTrue(engine_compat.is_sound_effect("ドドド"))
        self.assertFalse(engine_compat.is_sound_effect("BOB"))
        self.assertFalse(engine_compat.is_sound_effect("I SAID IT'S FINE, OKAY? ふ"))


class KeptNamesTest(unittest.TestCase):
    def test_names_kept_by_the_translation_become_terms(self):
        from memory import kept_names
        pairs = [{"original": "CHISA, HANG ON A SEC", "translation": "Chisa, espera aí."},
                 {"original": "OKAY KOHEI, LET'S GO", "translation": "Ok, Kohei, vamos."},
                 {"original": "THE WALL", "translation": "A muralha."}]
        self.assertEqual(sorted(kept_names(pairs)), [("CHISA", "Chisa"), ("KOHEI", "Kohei")])

    def test_a_name_of_several_words_is_kept_whole(self):
        # op1153-6a: a sea and a mountain range named in English came back translated in
        # the next round; learned as single words, the whole name was never a term.
        from memory import kept_names
        pairs = [{"original": "I WAS BORN IN THE WEST MARSH.", "translation": "Nasci no West Marsh."},
                 {"original": "BEYOND THE IRON PEAKS, CHISA?", "translation": "Além dos Iron Peaks, Chisa?"}]
        self.assertEqual(sorted(kept_names(pairs)), [("CHISA", "Chisa"), ("IRON PEAKS", "Iron Peaks"),
                                                     ("WEST MARSH", "West Marsh")])
        # A name and a title next to it, both kept but apart, stay two terms.
        self.assertEqual(sorted(kept_names([{"original": "KOHEI, CHISA!", "translation": "Kohei, Chisa!"}])),
                         [("CHISA", "Chisa"), ("KOHEI", "Kohei")])

    def test_a_term_seen_on_this_very_page_is_sent_again_for_it(self):
        # The same page read again has the same OCR, so an unconfirmed term from it is
        # safe there; other pages still wait for the second page.
        memory = WorkMemory()
        memory.record("Obra", "Cap 1", 8, [], [("WEST MARSH", "West Marsh")], "BORN IN THE WEST MARSH")
        self.assertEqual(memory.glossary("Obra"), [])
        same = memory.context("Obra", "Cap 1", 8)["glossary"]
        self.assertEqual(same, [{"source": "WEST MARSH", "target": "West Marsh"}])
        self.assertEqual(memory.context("Obra", "Cap 1", 9)["glossary"], [])
        self.assertEqual(memory.context("Obra", "Cap 2", 8)["glossary"], [])
        # A translated term or a gender from one reading is not forced on the next one.
        memory.record("Obra", "Cap 1", 8, [], [("IRON PEAKS", "Picos de Ferro"), ("CHISA", "Chisa (f)")],
                      "THE IRON PEAKS, CHISA")
        self.assertEqual([g["source"] for g in memory.context("Obra", "Cap 1", 8)["glossary"]],
                         ["WEST MARSH", "CHISA"])
        self.assertNotIn("gender", memory.context("Obra", "Cap 1", 8)["glossary"][1])

    def test_names_need_two_pages_even_without_the_terms_line(self):
        memory = WorkMemory()
        page = [region("CHISA, WAIT!", "Chisa, espera!")]
        self.assertEqual(remember(memory, {"obra": "GB", "capitulo": "87", "pagina": 1}, page, []), [])
        self.assertEqual(remember(memory, {"obra": "GB", "capitulo": "87", "pagina": 2}, page, []),
                         [("CHISA", "Chisa")])

    def test_scan_watermarks_stay_as_drawn(self):
        self.assertTrue(engine_compat.is_credit("thunderscans"))
        self.assertTrue(engine_compat.is_credit("READ AT ASURASCANS.COM"))
        self.assertFalse(engine_compat.is_credit("IT SCANS THE AREA"))
        self.assertTrue(engine_compat.is_credit("YOU CAN READ THE CHAPTER AT"))
        self.assertTrue(engine_compat.is_credit("SUPPORT US BY READING ON OUR WEBSITE"))
        self.assertFalse(engine_compat.is_credit("I READ THE LETTER AT HOME"))

    def test_comma_before_final_mark_is_dropped(self):
        from quality import normalize_spacing
        self.assertEqual(normalize_spacing("...da muralha,."), "...da muralha.")
        self.assertEqual(normalize_spacing("3,5 metros."), "3,5 metros.")


class CapitalsTest(unittest.TestCase):
    def test_an_answer_in_capitals_goes_back_to_sentence_case(self):
        from quality import page_names, sentence_case
        names = page_names(["Pegamos o Virion ontem."]) | {"Tri-Union"}
        self.assertEqual(sentence_case("A TRI-UNION VENCEU. O VIRION, NÃO!", names),
                         "A Tri-Union venceu. O Virion, não!")
        self.assertEqual(sentence_case("NÃO!", names), "NÃO!")
        self.assertEqual(sentence_case("ISSO FOI...", names), "Isso foi...")
        self.assertEqual(sentence_case("Já está certo.", names), "Já está certo.")

    def test_credits_stay_as_drawn(self):
        self.assertTrue(engine_compat.is_credit("THE BEGINNING AFTER™END"))
        self.assertFalse(engine_compat.is_credit("THE END"))


class PromptTest(unittest.TestCase):
    def tearDown(self):
        engine_compat.set_page_context(None)

    def translator(self, answer):
        calls = []

        class Completions:
            async def create(self, **kwargs):
                calls.append(kwargs["messages"])
                message = SimpleNamespace(content=answer)
                return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")], usage=None)

        fake = SimpleNamespace(
            chat_system_template="System {to_lang}.", get_chat_sample=lambda lang: None, model="m",
            _MAX_TOKENS=100, temperature=0.2, top_p=1, token_count=0,
            client=SimpleNamespace(chat=SimpleNamespace(completions=Completions()), max_retries=2),
            rgx_capture="(.*)", extract_capture_groups=lambda text, regex: text,
            _assemble_prompts=lambda f, t, q: iter([("\n".join(f"<|{i}|>{x}" for i, x in enumerate(q, 1)), len(q))]))
        fake._request_translation = lambda to, prompt, client=None, model=None: engine_compat.request_byok_translation(
            fake, to, prompt, client, model)
        return fake, calls

    def test_context_goes_to_the_system_prompt_and_terms_are_collected(self):
        engine_compat.set_page_context({"glossary": [{"source": "GREY", "target": "Grey"}], "previous": []})
        fake, calls = self.translator("<|1|>Ei, Grey!\n<|termos|>GREY=Grey; SWORD=espada")
        original = engine_compat.provider_pool
        engine_compat.provider_pool = lambda: None
        try:
            result = asyncio.run(engine_compat.translate_byok(fake, "ENG", "PTB", ["HEY, GREY!"]))
        finally:
            engine_compat.provider_pool = original
        self.assertEqual(result, ["Ei, Grey!"])
        self.assertIn('"GREY"', calls[0][0]["content"])
        self.assertEqual(engine_compat.take_learned_terms(), [("GREY", "Grey"), ("SWORD", "espada")])

    def test_without_work_the_prompt_is_unchanged(self):
        engine_compat.set_page_context(None)
        fake, calls = self.translator("<|1|>Oi.")
        original = engine_compat.provider_pool
        engine_compat.provider_pool = lambda: None
        try:
            asyncio.run(engine_compat.translate_byok(fake, "ENG", "PTB", ["HI."]))
        finally:
            engine_compat.provider_pool = original
        self.assertEqual(calls[0][0]["content"], "System PTB.")


if __name__ == "__main__":
    unittest.main()
