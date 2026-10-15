import importlib.util
import io
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import zipfile
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gateway import create_app, profile_config, inspect_result, apply_speed
from setup import configure
from hardware import detect
from core import create_core
from engine_compat import translate_nllb_batch, request_byok_translation, validate_byok_results, validate_page_translations, infer_nllb, translate_byok, PanelCV
from contextlib import nullcontext

spec = importlib.util.spec_from_file_location("batch", ROOT / "colab/batch.py")
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


def png(color="white", size=(100, 100)):
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, "PNG")
    return output.getvalue()


class SpeedTest(unittest.TestCase):
    def test_fast_mode_uses_lighter_cleaning_and_quality_keeps_profile(self):
        quality = profile_config("byok", {}, "quality")
        fast = profile_config("byok", {}, "fast")
        self.assertEqual(quality["inpainter"]["inpainter"], "lama_large")
        self.assertEqual((fast["inpainter"]["inpainter"], fast["inpainter"]["inpainting_size"]), ("lama_mpe", 1024))
        self.assertLessEqual(fast["detector"]["detection_size"], 1536)
        self.assertEqual(fast["detector"]["detector"], quality["detector"]["detector"])
        with self.assertRaises(ValueError):
            apply_speed(dict(quality), "turbo")


class ServerTest(unittest.TestCase):
    def test_panel_cv_normalizes_new_and_legacy_geometry_shapes(self):
        import numpy as np
        for legacy in (False, True):
            points = np.array([[0, 0], [10, 0], [10, 10]])
            lines = np.array([[0., 0., 10., 0.]])
            if legacy:
                points, lines = points.reshape(-1, 1, 2), lines.reshape(-1, 1, 4)
            cv = PanelCV(SimpleNamespace(
                findContours=lambda *args: ([points], None),
                approxPolyDP=lambda *args: points,
                convexHull=lambda *args: points,
                createLineSegmentDetector=lambda *args: SimpleNamespace(detect=lambda *args: (lines, None, None, None)),
            ))
            self.assertEqual(cv.findContours(None)[0][0].shape, (3, 1, 2))
            self.assertEqual(cv.approxPolyDP(None).shape, (3, 1, 2))
            self.assertEqual(cv.convexHull(None).shape, (3, 1, 2))
            self.assertEqual(cv.createLineSegmentDetector().detect(None)[0].shape, (1, 1, 4))

    def test_byok_strict_markers_and_no_automatic_paid_restart(self):
        content = "<|1|>Olá!<|2|>Mundo!"
        async def request(to, prompt):
            return content
        engine = SimpleNamespace(
            client=SimpleNamespace(max_retries=2),
            _assemble_prompts=lambda source, target, queries: [("prompt", len(queries))],
            _request_translation=request, rgx_capture="(.*)",
            extract_capture_groups=lambda text, regex: text,
        )
        self.assertEqual(asyncio.run(translate_byok(engine, "English", "Portuguese", ["Hello!", "World!"])),
                         ["Olá!", "Mundo!"])
        self.assertEqual(engine.client.max_retries, 0)
        content = "<|1|>Olá!<|1|>Duplicado"
        with self.assertRaises(ValueError):
            asyncio.run(translate_byok(engine, "English", "Portuguese", ["Hello!", "World!"]))

    def test_nllb_does_not_silently_drop_unresolved_source_language(self):
        engine = SimpleNamespace(
            _mangalate_langid=SimpleNamespace(classify=lambda text: ("en", .4)),
            _map_detected_lang_to_translator=lambda code: "eng_Latn" if code == "en" else None,
            _translate_batch=lambda source, target, texts: [source + ":" + target],
        )
        self.assertEqual(asyncio.run(infer_nllb(engine, "auto", "por_Latn", ["Hello world!"])),
                         ["eng_Latn:por_Latn"])
        engine._mangalate_langid.classify = lambda text: ("unsupported", .9)
        with self.assertRaises(ValueError):
            asyncio.run(infer_nllb(engine, "auto", "por_Latn", ["Hello world!"]))

    def test_recognized_page_cannot_succeed_with_zero_translated_regions(self):
        async def empty(self, config, ctx):
            for region in ctx.text_regions:
                region.translation = ""
            return []
        ctx = SimpleNamespace(text_regions=[SimpleNamespace(text="Hello!", translation="")])
        with self.assertRaises(ValueError):
            asyncio.run(validate_page_translations(empty)(None, None, ctx))
        ctx.text_regions = []
        self.assertEqual(asyncio.run(validate_page_translations(empty)(None, None, ctx)), [])

    def test_unchanged_proper_names_preserve_page_without_false_engine_failure(self):
        async def unchanged(self, config, ctx):
            for region in ctx.text_regions:
                region.translation = region.text
            return []
        ctx = SimpleNamespace(text_regions=[SimpleNamespace(text="Naruto", translation="")])
        self.assertEqual(asyncio.run(validate_page_translations(unchanged)(None, None, ctx)), [])

    def test_byok_provider_without_usage_and_truncated_output(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="<|1|>Olá!"), finish_reason="stop")],
            usage=None,
        )
        async def create(**kwargs):
            self.assertEqual(kwargs["model"], "user-model")
            return response
        engine = SimpleNamespace(
            client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
            model="user-model", _MAX_TOKENS=2048, temperature=.2, top_p=1,
            token_count=0, chat_system_template="Translate to {to_lang}", get_chat_sample=lambda to: None,
        )
        self.assertEqual(asyncio.run(request_byok_translation(engine, "Portuguese", "Hello!")), "<|1|>Olá!")
        self.assertEqual(engine.token_count, 0)
        response.choices[0].finish_reason = "length"
        with self.assertRaises(ValueError):
            asyncio.run(request_byok_translation(engine, "Portuguese", "Hello!"))

    def test_byok_missing_bubble_translation_is_not_silent_success(self):
        async def missing(self, from_lang, to_lang, queries):
            return ["Olá!", ""]
        translated = validate_byok_results(missing)
        with self.assertRaises(ValueError):
            asyncio.run(translated(None, "English", "Portuguese", ["Hello!", "World!"]))

    def test_direct_engine_supplies_required_upstream_initialization_parameter(self):
        class Engine:
            def __init__(self, params):
                if int(params["kernel_size"]) != 3:
                    raise ValueError("Wrong kernel")
        upstream = SimpleNamespace(MangaTranslator=Engine, Config=dict)
        with patch.dict(sys.modules, {"manga_translator": upstream}), \
             patch("engine_compat.apply_compatibility"):
            with TestClient(create_core()) as client:
                self.assertEqual(client.get("/healthz").status_code, 200)

    def test_nllb_uses_current_language_token_api_and_rejects_empty_results(self):
        class Tokenizer:
            unk_token_id = 0
            def __call__(self, *args, **kwargs):
                return {}
            def convert_tokens_to_ids(self, code):
                return 7 if code == "por_Latn" else 0
            def batch_decode(self, *args, **kwargs):
                return ["Olá mundo!"]
        class Model:
            def generate(self, **kwargs):
                self.target = kwargs["forced_bos_token_id"]
                return [[1, 2]]
        engine = SimpleNamespace(tokenizer=Tokenizer(), model=Model(), device="cpu")
        with patch.dict(sys.modules, {"torch": SimpleNamespace(no_grad=nullcontext)}):
            self.assertEqual(translate_nllb_batch(engine, "eng_Latn", "por_Latn", ["Hello world!"]), ["Olá mundo!"])
            self.assertEqual(engine.model.target, 7)
            with self.assertRaises(ValueError):
                translate_nllb_batch(engine, "eng_Latn", "invalid", ["Hello world!"])
            engine.tokenizer.batch_decode = lambda *args, **kwargs: [""]
            with self.assertRaises(ValueError):
                translate_nllb_batch(engine, "eng_Latn", "por_Latn", ["Hello world!"])

    def test_direct_engine_returns_png_without_internal_rpc(self):
        class Engine:
            async def translate(self, image, config):
                self.config = config
                return type("Context", (), {"result": image})()
        engine = Engine()
        with TestClient(create_core(engine)) as client:
            self.assertEqual(client.post("/queue-size").json(), 0)
            response = client.post("/translate/with-form/image",
                                   files={"image": ("page.png", png())},
                                   data={"config": '{"translator":{"target_lang":"PTB"}}'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["content-type"], "image/png")
            self.assertEqual(engine.config["translator"]["target_lang"], "PTB")
            self.assertEqual(client.post("/simple_execute/translate").status_code, 404)

    def test_direct_engine_sanitizes_provider_errors(self):
        class Engine:
            async def translate(self, image, config):
                raise RuntimeError("SECRET-PROVIDER-KEY")
        with TestClient(create_core(Engine())) as client:
            response = client.post("/translate/with-form/image",
                                   files={"image": ("page.png", png())})
            self.assertEqual(response.status_code, 502)
            self.assertNotIn("SECRET-PROVIDER-KEY", response.text)

    def client(self, handler=None, profile="basic"):
        if handler is None:
            handler = lambda request: httpx.Response(200, content=png(), headers={"content-type": "image/png"})
        return TestClient(create_app(key="test-only-" + "x" * 30, profile=profile, transport=httpx.MockTransport(handler)))

    def headers(self):
        return {"X-Mangalate-Key": "test-only-" + "x" * 30}

    def test_auth_is_mandatory_and_private_routes_are_not_exposed(self):
        with self.client() as client:
            self.assertEqual(client.get("/v1/info").status_code, 401)
            self.assertEqual(client.get("/healthz").status_code, 200)
            self.assertEqual(client.get("/results/list", headers=self.headers()).status_code, 404)

    def test_profile_cannot_be_overridden_by_old_app_paid_engine_or_file_paths(self):
        config = profile_config("basic", {"translator": {"translator": "gemini", "gpt_config": "/etc/passwd", "target_lang": "PTB"}})
        self.assertEqual(config["translator"]["translator"], "nllb")
        self.assertNotIn("gpt_config", config["translator"])
        self.assertEqual(config["ocr"]["ignore_bubble"], 8)
        self.assertNotIn("upscale", config)

    def test_byok_selects_contextual_prompt(self):
        config = profile_config("byok", {})
        self.assertEqual(config["translator"]["translator"], "custom_openai")
        self.assertTrue(config["translator"]["enable_post_translation_check"])

    def test_png_response_and_real_multipart_contract(self):
        def upstream(request):
            self.assertIn(b'name="image"', request.content)
            self.assertIn(b'"translator": "nllb"', request.content)
            return httpx.Response(200, content=png())
        with self.client(upstream) as client:
            result = client.post("/translate/with-form/image", headers=self.headers(),
                                 files={"image": ("page.png", png(), "image/png")}, data={"config": "{}"})
            self.assertEqual(result.status_code, 200, result.text if result.status_code != 200 else "")
            self.assertEqual(result.headers["x-mangalate-review"], "required")

    def test_invalid_page_and_config_rejected(self):
        with self.client() as client:
            for config, image in (("{}", b"not an image"), ("[]", png()), ('{"translator":{"target_lang":"XXX"}}', png())):
                result = client.post("/translate/with-form/image", headers=self.headers(),
                                     files={"image": ("bad.png", image)}, data={"config": config})
                self.assertEqual(result.status_code, 422)

    def test_upstream_errors_never_echo_keys(self):
        with self.client(lambda r: httpx.Response(403, text="private-api-token")) as client:
            result = client.post("/translate/with-form/image", headers=self.headers(),
                                 files={"image": ("page.png", png())})
            self.assertEqual(result.status_code, 502)
            self.assertNotIn("private-api-token", result.text)

    def test_only_one_paid_or_local_page_is_admitted_at_a_time(self):
        started, release = threading.Event(), threading.Event()
        async def handler(request):
            started.set()
            await asyncio.to_thread(release.wait, 3)
            return httpx.Response(200, content=png())
        with self.client(handler) as client, ThreadPoolExecutor(max_workers=1) as pool:
            kwargs = {"headers": self.headers(), "files": {"image": ("page.png", png())}}
            first = pool.submit(client.post, "/translate/with-form/image", **kwargs)
            self.assertTrue(started.wait(2))
            try:
                self.assertEqual(client.post("/translate/with-form/image", **kwargs).status_code, 429)
            finally:
                release.set()
            self.assertEqual(first.result(timeout=4).status_code, 200)

    def test_oversized_mask_and_wrong_framing_blocked(self):
        for image in (Image.new("RGB", (100, 100), "black"), Image.new("RGB", (120, 100), "white")):
            with self.assertRaises(ValueError):
                inspect_result(Image.new("RGB", (100, 100), "white"), image)

    def test_queue_contract_matches_android_int_response(self):
        with self.client(lambda r: httpx.Response(200, json=2)) as client:
            self.assertEqual(client.post("/queue-size", headers=self.headers()).json(), 2)

    def test_setup_creates_separate_key_paths_and_reuses_access_key(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path, _ = configure("basic", "cpu", "127.0.0.1", root=root)
            original = path.read_text()
            configure("byok", "gpu", "127.0.0.1", "https://example.com/v1", "model", "provider-test-token", root=root)
            self.assertEqual(original, path.read_text())
            self.assertNotIn("provider-test-token", (root / ".env").read_text())
            self.assertEqual((root / "secrets/provider_key.txt").read_text().strip(), "provider-test-token")

    def test_zip_traversal_rejected_and_pages_sorted_numerically(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / "input.zip"
            with zipfile.ZipFile(archive, "w") as book:
                book.writestr("../escape.png", png())
            with self.assertRaises(ValueError):
                batch.unpack_pages(archive, root / "pages")
            with zipfile.ZipFile(archive, "w") as book:
                book.writestr("10.png", png())
                book.writestr("2.png", png())
            self.assertEqual([x.name for x in batch.unpack_pages(archive, root / "ok")], ["2.png", "10.png"])

    def test_chapter_context_is_data_and_safe_for_template_format(self):
        context = batch.contextual_prompt([[{"original": "{not_an_instruction}", "translation": "Olá"}]], [])
        self.assertIn("{not_an_instruction}", context.format(to_lang="Portuguese"))

    def test_notebook_cells_compile_and_no_tunnel_or_keepalive(self):
        notebook = json.loads((ROOT / "colab/Mangalate_Colab.ipynb").read_text())
        for index, cell in enumerate(notebook["cells"]):
            if cell["cell_type"] == "code":
                code = "".join(cell["source"])
                compile(code, f"cell_{index}", "exec")
                self.assertNotIn("cloudflared", code)
                self.assertNotIn("while True", code)

    def test_hardware_matrix_does_not_claim_directml_or_rocm_validation(self):
        report = detect(system="Windows", kfd=False, nvidia=False)
        self.assertEqual(report["safe_default"], "cpu")
        self.assertEqual(next(x for x in report["backends"] if x["id"] == "directml")["state"], "planned")
        report = detect(system="Linux", kfd=True, nvidia=False)
        self.assertEqual(next(x for x in report["backends"] if x["id"] == "amd-rocm")["state"], "experimental_candidate")


if __name__ == "__main__":
    unittest.main()
