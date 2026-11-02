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

    def test_a_line_lettered_unchanged_teaches_no_name(self):
        # A scream the AI returned unchanged is lettered as is (engine_compat.validate_page_translations);
        # "Guha- aaa!!!" keeps "Guha" capitalized, but that is no name of the work.
        memory = WorkMemory()
        for page in (1, 2):
            regions = [SimpleNamespace(text="GUHA- AAA!!!", translation="Guha- aaa!!!", mangalate_same_as_source=True),
                       SimpleNamespace(text="KOHEI, WAIT!", translation="Kohei, espera!")]
            remember(memory, {"obra": "Obra", "capitulo": "Cap 1", "pagina": page}, regions, [])
        targets = {g["target"] for g in memory.context("Obra", "Cap 1", 3)["glossary"]}
        self.assertIn("Kohei", targets)
        self.assertNotIn("Guha", targets)

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
        # One Piece 1153 p1: a chapter subtitle read in one block with its staff.
        self.assertTrue(engine_compat.is_credit("PILGRIMAGE, VOL.37 By EIICHIRO ODA Iation: STEPHEN PAUL Lettering: VANESSA"))
        self.assertFalse(engine_compat.is_credit("THAT'S THE STORY: HE LEFT"))
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

    def test_chapter_heading_stays_as_drawn(self):
        # One Piece 1161 p3: the chapter title, once read whole, was lettered at about half the size
        # of its capitals.  A heading stays in its own lettering.
        self.assertTrue(engine_compat.is_credit("Chapter 12: A LONG WAY HOME"))
        self.assertTrue(engine_compat.is_credit("EPISODE 3 - THE STORM"))
        self.assertTrue(engine_compat.is_credit("Ch. 40"))
        self.assertFalse(engine_compat.is_credit("THE NEXT CHAPTER STARTS TODAY."))
        self.assertFalse(engine_compat.is_credit("IN CHAPTER 2 HE DIES?!"))
        self.assertFalse(engine_compat.is_credit("CHAPTER?"))


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


class TermConsistencyTest(unittest.TestCase):
    """A term keeps the translation the chapter first used (Manwha teste p24 -> p64)."""

    def test_a_term_the_page_did_not_use_is_not_learned(self):
        # The AI translated the title and listed it untranslated: "IRON FIST MASTER=IRON FIST MASTER"
        # next to "Mestre do Punho de Ferro!".  The glossary then held the English as the translation.
        memory = WorkMemory()
        page = [region("IRON FIST MASTER!", "Mestre do Punho de Ferro!")]
        for number in (1, 2):
            remember(memory, {"obra": "Obra", "capitulo": "Cap 1", "pagina": number}, page,
                     [("IRON FIST MASTER", "IRON FIST MASTER")])
        self.assertEqual(memory.glossary("Obra"), [])
        # The translation it did write is learned.
        for number in (3, 4):
            remember(memory, {"obra": "Obra", "capitulo": "Cap 1", "pagina": number}, page,
                     [("IRON FIST MASTER", "Mestre do Punho de Ferro (m)")])
        self.assertEqual(memory.glossary("Obra"), [{"source": "IRON FIST MASTER", "target": "Mestre do Punho de Ferro",
                                                    "gender": "m"}])

    def test_a_term_used_once_is_offered_to_the_later_pages_of_the_chapter(self):
        memory = WorkMemory()
        remember(memory, {"obra": "Obra", "capitulo": "Cap 1", "pagina": 24},
                 [region("IRON FIST MASTER!", "Mestre do Punho de Ferro!")], [("IRON FIST MASTER", "Mestre do Punho de Ferro")])
        self.assertEqual(memory.glossary("Obra"), [])  # still not a glossary term of the work
        later = memory.context("Obra", "Cap 1", 64)["glossary"]
        self.assertEqual(later, [{"source": "IRON FIST MASTER", "target": "Mestre do Punho de Ferro"}])
        # Not before the page that used it, nor in another chapter.
        self.assertEqual(memory.context("Obra", "Cap 1", 10)["glossary"], [])
        self.assertEqual(memory.context("Obra", "Cap 2", 64)["glossary"], [])

    def test_a_word_only_kept_capitalized_waits_for_a_second_page(self):
        # Manga control p3: "THAT MUST BE THE BAR" -> "Deve ser o Bar".  A word the translation
        # merely kept is weaker evidence than a term the AI listed: offered to the next pages,
        # it was listed there too and "Bar" became a name of the work.
        memory = WorkMemory()
        remember(memory, {"obra": "Obra", "capitulo": "Cap 1", "pagina": 3},
                 [region("THAT MUST BE THE BAR", "Deve ser o Bar")], [])
        self.assertEqual(memory.context("Obra", "Cap 1", 5)["glossary"], [])
        remember(memory, {"obra": "Obra", "capitulo": "Cap 1", "pagina": 3},
                 [region("[MARA KELL HAS WON!]", "[Mara Kell venceu!]")], [("MARA KELL", "Mara Kell")])
        self.assertEqual([g["source"] for g in memory.context("Obra", "Cap 1", 5)["glossary"]], ["MARA KELL"])

    def test_a_bubble_that_is_only_a_title_teaches_it(self):
        # Manwha teste p24: a title alone in a bubble, never listed as a term,
        # came back another way on p64.
        from memory import region_titles
        pairs = [{"original": "IRON FIST MASTER!", "translation": "Mestre do Punho de Ferro!"},
                 {"original": "GOT IT.", "translation": "Entendido."},                       # one word
                 {"original": "THE LAST QUEEN, MARA.", "translation": "A última rainha, Mara."},  # a sentence
                 {"original": "RUN, NOW!", "translation": "Corre, Agora!"},                  # a comma: speech
                 {"original": "I SEE...", "translation": "Entendo..."},
                 {"original": "IT'S MARA KELL", "translation": "É Mara Kell"},              # a sentence about a name
                 {"original": "NOT CHA SUNGMIN.", "translation": "Não Notcha Sungmin."},
                 {"original": "GET OUT OF HERE", "translation": "SAIA DAQUI"}]              # an answer in capitals
        self.assertEqual(region_titles(pairs), [("IRON FIST MASTER", "Mestre do Punho de Ferro")])

    def test_a_term_in_capitals_is_kept_in_sentence_case(self):
        # The AI listed "MARA KELL=MARA KELL" and the next pages wrote the name in capitals.
        memory = WorkMemory()
        page = [region("[MARA KELL OF THE NORTH WINS!]", "[MARA KELL DO NORTE VENCE!]")]
        remember(memory, {"obra": "Obra", "capitulo": "Cap 1", "pagina": 1}, page,
                 [("MARA KELL", "MARA KELL"), ("NORTH", "NORTE"), ("HP", "HP")])
        targets = {g["source"]: g["target"] for g in memory.context("Obra", "Cap 1", 2)["glossary"]}
        self.assertEqual(targets["MARA KELL"], "Mara Kell")
        self.assertEqual(targets["NORTH"], "Norte")
        from memory import _out_of_capitals
        for acronym in ("NPC", "SSS RANK", "STR", "HP"):  # acronyms of a status window stay
            self.assertTrue(_out_of_capitals(acronym).startswith(acronym.split()[0]), acronym)
        self.assertEqual(_out_of_capitals("ESPADA DO REI"), "Espada do Rei")

    def test_an_offered_term_does_not_force_its_gender(self):
        # Manga control: one page guessed "a" for a man's name; passed on with the term, the
        # guess spread to the next page.  The gender counts once the term is confirmed.
        memory = WorkMemory()
        remember(memory, {"obra": "Obra", "capitulo": "Cap 1", "pagina": 3},
                 [region("MARA KELL IS HERE", "Mara Kell está aqui")], [("MARA KELL", "Mara Kell (f)")])
        self.assertEqual(memory.context("Obra", "Cap 1", 7)["glossary"], [{"source": "MARA KELL", "target": "Mara Kell"}])

    def test_a_name_misread_after_the_right_one_is_known_is_not_learned(self):
        # Manwha teste: a name misread on p36 and p64, the right one known since p40; the
        # misreading became a name of the work.
        memory = WorkMemory()
        for number in (36, 64):
            if number == 64:
                for p in (39, 40):
                    remember(memory, {"obra": "Obra", "capitulo": "Cap 1", "pagina": p},
                             [region("MARA KELL ATTACKS", "Mara Kell ataca")], [("MARA KELL", "Mara Kell")])
            remember(memory, {"obra": "Obra", "capitulo": "Cap 1", "pagina": number},
                     [region("MARA TELL WINS", "Mara Tell vence")], [("MARA TELL", "Mara Tell")])
        self.assertEqual([g["source"] for g in memory.glossary("Obra")], ["MARA KELL"])

    def test_a_misread_name_learned_first_is_not_offered_once_the_right_one_is_known(self):
        # Manwha teste p64: the misreading, learned on p36 before the right name was known, went
        # to the AI next to the right name and the misreading stayed.
        memory = WorkMemory()
        remember(memory, {"obra": "Obra", "capitulo": "Cap 1", "pagina": 36},
                 [region("MARA TELL WINS", "Mara Tell vence")], [("MARA TELL", "Mara Tell")])
        for p in (39, 40):
            remember(memory, {"obra": "Obra", "capitulo": "Cap 1", "pagina": p},
                     [region("MARA KELL ATTACKS", "Mara Kell ataca")], [("MARA KELL", "Mara Kell")])
        self.assertEqual([g["source"] for g in memory.context("Obra", "Cap 1", 64)["glossary"]], ["MARA KELL"])

    def test_a_misread_name_is_not_offered_next_to_the_right_one_seen_once(self):
        memory = WorkMemory()
        remember(memory, {"obra": "Obra", "capitulo": "Cap 1", "pagina": 36},
                 [region("MARA TELL WINS", "Mara Tell vence")], [("MARA TELL", "Mara Tell")])
        remember(memory, {"obra": "Obra", "capitulo": "Cap 1", "pagina": 39},
                 [region("MARA KELL ATTACKS", "Mara Kell ataca")], [("MARA KELL", "Mara Kell")])
        self.assertEqual([g["source"] for g in memory.context("Obra", "Cap 1", 64)["glossary"]], ["MARA KELL"])

    def test_written_the_chapter_way_but_listed_another_counts(self):
        memory = WorkMemory()
        remember(memory, {"obra": "Obra", "capitulo": "Cap 1", "pagina": 1},
                 [region("IRON FIST MASTER!", "Mestre do Punho de Ferro!")], [("IRON FIST MASTER", "Mestre do Punho de Ferro")])
        added = remember(memory, {"obra": "Obra", "capitulo": "Cap 1", "pagina": 2},
                         [region("THE IRON FIST MASTER WON", "O Mestre do Punho de Ferro venceu")],
                         [("IRON FIST MASTER", "Mestre Punho-de-Ferro")])
        self.assertEqual(added, [("IRON FIST MASTER", "Mestre do Punho de Ferro")])

    def test_a_name_read_one_letter_off_goes_to_the_ai_as_a_hint(self):
        block = context_block({"glossary": [{"source": "MARA KELL", "target": "Mara Kell"}], "previous": []},
                              "<|1|>[HELPER, MARA TELL HAS FALLEN!]")
        self.assertIn('"names_maybe_misread": [{"read": "MARA TELL", "name": "Mara Kell"}]', block)
        block = context_block({"glossary": [{"source": "MARA KELL", "target": "Mara Kell"}], "previous": []},
                              "<|1|>MARA TOLD ME.")
        self.assertNotIn("names_maybe_misread\":", block)

    def test_a_term_without_translations_to_check_keeps_waiting(self):
        # Neighbour: terms recorded with no dialogue (older callers, a page whose regions
        # were not kept) still need a second page before any other page sees them.
        memory = WorkMemory()
        memory.record("Obra", "Cap 1", 8, [], [("WEST MARSH", "West Marsh")], "BORN IN THE WEST MARSH")
        self.assertEqual(memory.context("Obra", "Cap 1", 9)["glossary"], [])


if __name__ == "__main__":
    unittest.main()
