import importlib.util
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gateway import create_app, profile_config, inspect_result
from setup import configure
from hardware import detect

spec = importlib.util.spec_from_file_location("batch", ROOT / "colab/batch.py")
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


def png(color="white", size=(100, 100)):
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, "PNG")
    return output.getvalue()


class ServerTest(unittest.TestCase):
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
