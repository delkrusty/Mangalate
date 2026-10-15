"""BYOK provider presets, secret format, rotation and installer menu (no network)."""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine_compat
from providers import (AllProvidersResting, LONG_REST, PRESETS, ProviderPool, SHORT_REST, UnusableAnswer,
                       dump_secret, parse_secret, validate_base)
from setup import choose_providers, configure

GROQ = {"name": "groq", "base": PRESETS["groq"]["base"], "model": "openai/gpt-oss-120b", "key": "gsk_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
GEMINI = {"name": "gemini", "base": PRESETS["gemini"]["base"], "model": "gemini-flash-lite-latest", "key": "AIzabbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class ProviderError(Exception):
    def __init__(self, status, retry=None):
        super().__init__("provider body must never be logged")
        self.status_code = status
        self.response = SimpleNamespace(headers={"retry-after": retry} if retry else {})


def pool(*providers):
    clock, logs = Clock(), []
    return ProviderPool(providers or (GROQ, GEMINI), clock=clock, log=logs.append), clock, logs


class SecretTest(unittest.TestCase):
    def test_addresses(self):
        self.assertTrue(validate_base("https://api.groq.com/openai/v1"))
        self.assertTrue(validate_base("http://host.docker.internal:11434/v1"))
        self.assertFalse(validate_base("http://api.example.com/v1"))
        self.assertFalse(validate_base("api.groq.com"))

    def test_plain_key_keeps_single_provider_mode(self):
        self.assertIsNone(parse_secret("gsk_plain_key\n"))

    def test_provider_list_round_trip_and_validation(self):
        self.assertEqual(parse_secret(dump_secret([GROQ, GEMINI])), [GROQ, GEMINI])
        with self.assertRaises(ValueError):
            parse_secret(dump_secret([dict(GROQ, key="")]))
        with self.assertRaises(ValueError):
            parse_secret(dump_secret([dict(GROQ, base="http://evil.example/v1")]))
        ollama = {"name": "ollama", "base": PRESETS["ollama"]["base"], "model": "qwen3", "key": ""}
        self.assertEqual(parse_secret(dump_secret([ollama]))[0]["key"], "ollama")


class RotationTest(unittest.TestCase):
    def run_pool(self, p, behaviour):
        calls = []

        async def attempt(provider):
            calls.append(provider["name"])
            outcome = behaviour(provider["name"])
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return asyncio.run(p.run(attempt)), calls

    def test_limit_moves_to_next_provider_and_rests_the_first(self):
        p, clock, logs = pool()
        result, calls = self.run_pool(p, lambda n: ProviderError(429) if n == "groq" else ["ok"])
        self.assertEqual((result, calls), (["ok"], ["groq", "gemini"]))
        self.assertEqual(p.resting["groq"], clock.now + SHORT_REST)
        self.assertNotIn("provider body", " ".join(logs))
        # While Groq rests, pages go straight to Gemini; afterwards Groq is first again.
        self.assertEqual(self.run_pool(p, lambda n: ["ok"])[1], ["gemini"])
        clock.now += SHORT_REST
        self.assertEqual(self.run_pool(p, lambda n: ["ok"])[1], ["groq"])

    def test_retry_after_and_repeated_limits(self):
        p, clock, _ = pool()
        self.run_pool(p, lambda n: ProviderError(429, "12") if n == "groq" else ["ok"])
        self.assertEqual(p.resting["groq"], clock.now + 12)
        for _ in range(2):
            clock.now = p.resting["groq"] + 1  # Groq is tried again only after its rest
            self.run_pool(p, lambda n: ProviderError(429) if n == "groq" else ["ok"])
        self.assertEqual(p.resting["groq"], clock.now + LONG_REST)

    def test_success_resets_limit_count(self):
        p, clock, _ = pool()
        self.run_pool(p, lambda n: ProviderError(429) if n == "groq" else ["ok"])
        clock.now += SHORT_REST
        self.run_pool(p, lambda n: ["ok"])
        self.assertEqual(p.strikes["groq"], 0)

    def test_bad_key_or_model_rests_for_an_hour(self):
        for status in (401, 403, 404):
            p, clock, _ = pool()
            self.run_pool(p, lambda n: ProviderError(status) if n == "groq" else ["ok"])
            self.assertEqual(p.resting["groq"], clock.now + LONG_REST)

    def test_malformed_answer_tries_next_provider(self):
        p, _, _ = pool()
        result, calls = self.run_pool(p, lambda n: ValueError("markers") if n == "groq" else ["ok"])
        self.assertEqual((result, calls), (["ok"], ["groq", "gemini"]))

    def test_malformed_answers_never_pause_providers(self):
        # Grand Blue 87 page 7: both AIs answered with broken markers and the
        # old rule paused both, so the next pages failed with everyone resting.
        p, _, _ = pool()
        with self.assertRaises(UnusableAnswer):
            self.run_pool(p, lambda n: ValueError("markers"))
        self.assertEqual(p.available(), p.providers)
        self.assertEqual(p.events, [("groq", "content"), ("gemini", "content")])
        self.assertEqual(self.run_pool(p, lambda n: ["ok"])[1], ["groq"])

    def test_everyone_resting_is_reported_with_wait(self):
        p, _, _ = pool()
        with self.assertRaises(AllProvidersResting) as raised:
            self.run_pool(p, lambda n: ProviderError(429, "90" if n == "groq" else "30"))
        self.assertEqual(round(raised.exception.seconds), 30)
        self.assertIn("min", str(raised.exception))


class TranslateWithPoolTest(unittest.TestCase):
    def tearDown(self):
        engine_compat._POOL = None

    def test_page_falls_back_when_first_provider_returns_broken_markers(self):
        p, _, _ = pool()
        engine_compat._POOL = p
        seen = []

        async def request(to_lang, prompt, client=None, model=None):
            seen.append(model)
            if model == GROQ["model"]:
                return "<|1|>Só uma fala"
            return "<|1|>Olá!\n<|2|>Mundo!"
        engine = SimpleNamespace(
            client=SimpleNamespace(max_retries=2),
            _assemble_prompts=lambda source, target, queries: [("prompt", len(queries))],
            _request_translation=request, rgx_capture="(.*)",
            extract_capture_groups=lambda text, regex: text,
        )
        original_client = engine_compat.provider_client
        engine_compat.provider_client = lambda pool, provider: None
        try:
            result = asyncio.run(engine_compat.translate_byok(engine, "ENG", "PTB", ["Hello!", "World!"]))
        finally:
            engine_compat.provider_client = original_client
        self.assertEqual(result, ["Olá!", "Mundo!"])
        self.assertEqual(seen, [GROQ["model"], GEMINI["model"]])

    def test_single_key_secret_keeps_previous_behaviour(self):
        with tempfile.TemporaryDirectory() as folder:
            secret = Path(folder) / "provider_key"
            secret.write_text("plain-key")
            import os
            previous = os.environ.get("MANGALATE_API_KEY_FILE")
            os.environ["MANGALATE_API_KEY_FILE"] = str(secret)
            try:
                engine_compat._POOL = None
                self.assertIsNone(engine_compat.provider_pool())
                engine_compat._POOL = None
                secret.write_text(dump_secret([GROQ, GEMINI]))
                self.assertEqual([x["name"] for x in engine_compat.provider_pool().providers], ["groq", "gemini"])
            finally:
                if previous is None:
                    os.environ.pop("MANGALATE_API_KEY_FILE")
                else:
                    os.environ["MANGALATE_API_KEY_FILE"] = previous


class InstallerTest(unittest.TestCase):
    def test_menu_builds_ordered_providers_with_default_models(self):
        answers = iter(["1", "", "s", "2", "", "n"])
        keys = iter([GROQ["key"], GEMINI["key"]])
        providers = choose_providers(ask=lambda prompt: next(answers), secret=lambda prompt: next(keys))
        self.assertEqual(providers, [GROQ, GEMINI])

    def test_ollama_needs_no_key_and_custom_provider_is_manual(self):
        answers = iter(["4,5", "qwen3:8b", "https://api.example.com/v1", "my-model", "n"])
        keys = iter(["custom-provider-key-123456"])
        providers = choose_providers(ask=lambda prompt: next(answers), secret=lambda prompt: next(keys))
        self.assertEqual(providers[0], {"name": "ollama", "base": PRESETS["ollama"]["base"],
                                        "model": "qwen3:8b", "key": ""})
        self.assertEqual(providers[1]["base"], "https://api.example.com/v1")

    def test_bad_paste_or_half_typed_key_is_retried(self):
        answers = iter(["1", "", "n"])
        keys = iter(["\x16", "abcdefghijklmnopqrstuvwxhgdf", GROQ["key"]])
        providers = choose_providers(ask=lambda prompt: next(answers), secret=lambda prompt: next(keys))
        self.assertEqual(providers[0]["key"], GROQ["key"])
        with self.assertRaises(ValueError):
            choose_providers(ask=lambda prompt: "1" if "Número" in prompt else "",
                             secret=lambda prompt: "\x16")

    def test_key_is_read_from_clipboard_without_pasting(self):
        from setup import ask_key
        prompts = []
        key = ask_key("groq", secret=lambda prompt: self.fail("should not ask to paste"),
                      ask=prompts.append, clipboard=lambda: GROQ["key"] + "\n")
        self.assertEqual(key, GROQ["key"])
        self.assertIn("não precisa colar", prompts[0])

    def test_yes_no_insists_on_a_clear_answer(self):
        from setup import yes_no
        answers = iter(["h", "S"])
        self.assertTrue(yes_no("?", ask=lambda prompt: next(answers)))
        self.assertFalse(yes_no("?", ask=lambda prompt: ""))

    def test_enter_picks_groq_and_comma_list_still_works(self):
        answers = iter(["", "", "n"])
        keys = iter([GROQ["key"]])
        self.assertEqual(choose_providers(ask=lambda prompt: next(answers), secret=lambda prompt: next(keys)), [GROQ])
        answers = iter(["1,2", "", "", "n"])
        keys = iter([GROQ["key"], GEMINI["key"]])
        self.assertEqual(choose_providers(ask=lambda prompt: next(answers), secret=lambda prompt: next(keys)),
                         [GROQ, GEMINI])

    def test_invalid_choice_is_rejected(self):
        with self.assertRaises(ValueError):
            choose_providers(ask=lambda prompt: "9", secret=lambda prompt: "")

    def test_configure_writes_rotation_secret_but_no_key_in_env(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            configure("byok", "cpu", "127.0.0.1", root=root, providers=[GROQ, GEMINI])
            env = (root / ".env").read_text()
            self.assertIn(f"CUSTOM_OPENAI_API_BASE={GROQ['base']}", env)
            self.assertNotIn(GROQ["key"], env)
            self.assertEqual(json.loads((root / "secrets/provider_key.txt").read_text())["providers"][1]["name"],
                             "gemini")
            with self.assertRaises(ValueError):
                configure("byok", "cpu", "127.0.0.1", root=root, providers=[dict(GROQ, key="")])


if __name__ == "__main__":
    unittest.main()


class NumberedAnswerTest(unittest.TestCase):
    """Some models number lines '1.' instead of '<|1|>' (Groq qwen, live check 14/10)."""

    def test_strictly_ordered_numbering_is_accepted(self):
        from engine_compat import parse_marked
        self.assertEqual(parse_marked("1. Entendido, Kaiser.\n2. Hoje de manhã?", 2),
                         ["Entendido, Kaiser.", "Hoje de manhã?"])
        self.assertEqual(parse_marked("[1] Olá\n[2] Mundo\ncontinua aqui", 2), ["Olá", "Mundo continua aqui"])
        self.assertEqual(parse_marked("1) Sim\n2) Não", 2), ["Sim", "Não"])

    def test_anything_that_could_swap_or_lose_a_bubble_is_rejected(self):
        from engine_compat import parse_marked
        for bad in ("1. a\n3. b\n2. c", "1. a\n2. b", "Aqui está:\n1. a\n2. b\n3. c", "1. a\n2. b\n3. c\n4. d",
                    "1. a\n2.\n3. c"):
            with self.assertRaises(ValueError, msg=bad):
                parse_marked(bad, 3)


class RebuildTest(unittest.TestCase):
    def test_plain_docker_build_then_restart_and_version_check(self):
        import subprocess
        from rebuild import rebuild
        calls = []

        def run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout=self.running(cmd) if "sha256sum" in cmd else "")
        rebuild("cpu", run=run)
        self.assertEqual(calls[0][:2], ["docker", "build"])
        self.assertIn("mangalate-translator-cpu:local", calls[0])
        self.assertIn("--no-build", calls[2])
        self.assertIn("sha256sum", calls[3])

    @staticmethod
    def running(cmd, stale=None):
        import hashlib
        from rebuild import CHECKED, ROOT
        lines = []
        for path, inside in CHECKED.items():
            digest = "0" * 64 if inside == stale else hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            lines.append(f"{digest}  {inside}")
        return "\n".join(lines)

    def test_old_image_still_running_is_reported(self):
        import subprocess
        from rebuild import rebuild
        run = lambda cmd, **kw: subprocess.CompletedProcess(
            cmd, 0, stdout=self.running(cmd, stale="/mangalate/batch.py") if "sha256sum" in cmd else "")
        with self.assertRaises(SystemExit) as raised:
            rebuild("cpu", run=run)
        self.assertIn("batch.py", str(raised.exception))

    def test_hardware_is_read_from_env(self):
        import tempfile
        from rebuild import hardware_from_env
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / ".env").write_text("MANGALATE_PROFILE=byok\nMANGALATE_HARDWARE=gpu\n")
            self.assertEqual(hardware_from_env(Path(folder)), "gpu")
