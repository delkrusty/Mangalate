"""What the reader fixes and reports from the app: the work's glossary and page reports (no Docker)."""
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import memory
from core import create_core, report_rows
from gateway import create_app
from memory import WorkMemory

KEY = "test-only-" + "x" * 30


def png(color="white", size=(100, 100)):
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, "PNG")
    return output.getvalue()


def learn(work_memory, pages=(1, 2)):
    for page in pages:
        work_memory.record("Obra A", "Cap 1", page, [{"original": "GREY RUNS.", "translation": "Grey corre."}],
                           [("GREY", "Grey")], "GREY RUNS.")


class ReaderGlossaryTest(unittest.TestCase):
    """WorkMemory.entries/edit, behind GET/PUT /v1/glossary."""

    def test_reader_fix_is_kept_and_reaches_the_ai(self):
        work_memory = WorkMemory()
        learn(work_memory)
        self.assertEqual(work_memory.entries("Obra A"), [{"source": "GREY", "target": "Grey"}])
        work_memory.edit("Obra A", [{"source": "GREY", "target": "Cinza", "gender": "m"}])
        # A later page listing the old translation does not undo the reader's fix.
        learn(work_memory, (3,))
        self.assertEqual(work_memory.entries("Obra A"), [{"source": "GREY", "target": "Cinza", "gender": "m"}])
        self.assertIn({"source": "GREY", "target": "Cinza", "gender": "m"},
                      work_memory.context("Obra A", "Cap 1", 4)["glossary"])

    def test_removed_term_is_not_learned_again(self):
        work_memory = WorkMemory()
        learn(work_memory)
        work_memory.edit("Obra A", [], ["GREY"])
        learn(work_memory, (3, 4))
        self.assertEqual(work_memory.entries("Obra A"), [])
        self.assertNotIn("GREY", [g["source"] for g in work_memory.context("Obra A", "Cap 1", 5)["glossary"]])
        # Written back by the reader, it is a term again.
        work_memory.edit("Obra A", [{"source": "GREY", "target": "Grey"}])
        self.assertEqual(work_memory.entries("Obra A"), [{"source": "GREY", "target": "Grey"}])

    def test_term_learned_while_the_list_was_open_is_kept(self):
        # The app sends only what the reader wrote or deleted: a name confirmed by another page
        # after the list was loaded is neither, so saving does not block it.
        work_memory = WorkMemory()
        learn(work_memory)
        work_memory.record("Obra A", "Cap 1", 3, [], [("MARA", "Mara")], "MARA.")
        work_memory.record("Obra A", "Cap 1", 4, [], [("MARA", "Mara")], "MARA.")
        stored = work_memory.edit("Obra A", [{"source": "GREY", "target": "Cinza"}])
        self.assertEqual([g["source"] for g in stored], ["GREY", "MARA"])
        self.assertEqual(stored[0]["target"], "Cinza")
        # A term with its translation erased is not sent at all: it stays, not blocked.
        self.assertEqual(work_memory.edit("Obra A", [{"source": "MARA", "target": " "}]), stored)

    def test_failed_save_reaches_the_app(self):
        with tempfile.TemporaryDirectory() as folder:
            work_memory = WorkMemory(folder)
            work_memory.write = lambda work, data: (_ for _ in ()).throw(PermissionError())
            with self.assertRaises(OSError):
                work_memory.edit("Obra A", [{"source": "GREY", "target": "Cinza"}])

    def test_edit_cleans_and_bounds_the_list(self):
        work_memory = WorkMemory()
        stored = work_memory.edit("Obra A", [{"source": "  A\x00B ", "target": "x" * 500, "gender": "z"},
                                             {"source": "a b", "target": "dup"}, {"source": "", "target": "vazio"}])
        self.assertEqual(stored, [{"source": "A B", "target": "x" * 60}])
        with self.assertRaises(ValueError):
            work_memory.edit("", [])
        with self.assertRaises(ValueError):
            work_memory.edit("Obra A", "GREY=Grey")

    def test_edit_survives_a_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            WorkMemory(folder).edit("Obra A", [{"source": "GREY", "target": "Cinza"}])
            self.assertEqual(WorkMemory(folder).entries("Obra A"), [{"source": "GREY", "target": "Cinza"}])


class GatewayReaderLoopTest(unittest.TestCase):
    def client(self, handler, reports=None):
        return TestClient(create_app(key=KEY, profile="basic", transport=httpx.MockTransport(handler), reports=reports))

    def headers(self):
        return {"X-Mangalate-Key": KEY}

    def test_glossary_needs_the_key_and_forwards_only_clean_terms(self):
        seen = []

        def worker(request):
            seen.append(request)
            if request.method == "PUT":
                return httpx.Response(200, json=json.loads(request.content))
            return httpx.Response(200, json={"obra": "Obra A", "termos": []})
        with self.client(worker) as client:
            self.assertEqual(client.get("/v1/glossary", params={"obra": "Obra A"}).status_code, 401)
            self.assertEqual(client.put("/v1/glossary", json={"obra": "Obra A", "termos": []}).status_code, 401)
            self.assertEqual(seen, [])
            self.assertEqual(client.get("/v1/glossary", params={"obra": "Obra A"}, headers=self.headers()).status_code, 200)
            self.assertEqual(seen[-1].url.params["obra"], "Obra A")
            put = client.put("/v1/glossary", headers=self.headers(), json={
                "obra": "Obra A", "termos": [{"source": "GREY", "target": "Cinza", "gender": "m", "extra": "x"}]})
            self.assertEqual(put.status_code, 200)
            self.assertEqual(json.loads(seen[-1].content),
                             {"obra": "Obra A", "termos": [{"source": "GREY", "target": "Cinza", "gender": "m"}],
                              "removidos": []})
            for bad in ({"termos": []}, {"obra": "Obra A", "termos": "GREY=Grey"},
                        {"obra": "Obra A", "termos": [{"source": 1, "target": "x"}]},
                        {"obra": "Obra A", "termos": [], "removidos": [3]}):
                self.assertEqual(client.put("/v1/glossary", headers=self.headers(), json=bad).status_code, 422)

    def test_report_saves_both_pages_and_regions_on_this_computer(self):
        original, translated = png("white"), png("gray")

        def worker(request):
            self.assertEqual(request.url.path, f"/regions/{hashlib.sha256(original).hexdigest()}")
            return httpx.Response(200, json=[{"estado": "original", "caixa": [1, 2, 3, 4], "ocr": "WAIT!"}])
        with tempfile.TemporaryDirectory() as folder:
            with self.client(worker, folder) as client:
                files = {"original": ("o.png", original, "image/png"), "traduzida": ("t.png", translated, "image/png")}
                work = json.dumps({"obra": "Obra A", "capitulo": "Cap 1", "pagina": 3})
                self.assertEqual(client.post("/v1/report", files=files, data={"work": work}).status_code, 401)
                result = client.post("/v1/report", headers=self.headers(), files=files,
                                     data={"work": work, "nota": "balão sujo"})
            self.assertEqual(result.status_code, 200, result.text)
            saved = Path(folder) / result.json()["pasta"]
            self.assertTrue(saved.name.endswith("-obra-a-p3"), saved.name)
            self.assertEqual((saved / "original.png").read_bytes(), original)
            self.assertEqual((saved / "traduzida.png").read_bytes(), translated)
            self.assertEqual(json.loads((saved / "regioes.json").read_text(encoding="utf-8"))[0]["ocr"], "WAIT!")
            info = json.loads((saved / "info.json").read_text(encoding="utf-8"))
            self.assertEqual(info["nota"], "balão sujo")
            self.assertNotIn(KEY, json.dumps(info))

    def test_report_without_regions_or_with_a_bad_page(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.client(lambda request: httpx.Response(404), folder) as client:
                ok = client.post("/v1/report", headers=self.headers(), files={
                    "original": ("o.png", png(), "image/png"), "traduzida": ("t.png", png(), "image/png")})
                self.assertEqual(ok.status_code, 200, ok.text)
                self.assertFalse(ok.json()["regioes"])
                # The page failed or its translation left the app's cache: the original alone.
                alone = client.post("/v1/report", headers=self.headers(), files={"original": ("o.png", png(), "image/png")})
                self.assertEqual(alone.status_code, 200, alone.text)
                info = json.loads((Path(folder) / alone.json()["pasta"] / "info.json").read_text(encoding="utf-8"))
                self.assertFalse(info["traduzida"])
                bad = client.post("/v1/report", headers=self.headers(), files={
                    "original": ("o.png", b"not an image", "image/png"), "traduzida": ("t.png", png(), "image/png")})
                self.assertEqual(bad.status_code, 422)


class WorkerReaderLoopTest(unittest.TestCase):
    def test_glossary_endpoints_use_the_work_memory(self):
        old = memory._DEFAULT
        memory._DEFAULT = WorkMemory()
        try:
            with TestClient(create_core(object())) as client:
                put = client.put("/glossary", json={"obra": "Obra A", "termos": [{"source": "GREY", "target": "Cinza"}]})
                self.assertEqual(put.status_code, 200)
                self.assertEqual(client.get("/glossary", params={"obra": "Obra A"}).json()["termos"],
                                 [{"source": "GREY", "target": "Cinza"}])
                self.assertEqual(client.put("/glossary", json={"obra": "", "termos": []}).status_code, 422)
        finally:
            memory._DEFAULT = old

    def test_regions_of_recent_pages_are_kept_for_reports(self):
        page = png()

        class Engine:
            async def translate(self, image, config):
                region = SimpleNamespace(xyxy=(1, 2, 30, 40), text="HI", text_raw="HI", translation="OI",
                                         mangalate_background={"tipo": "balao"})
                return SimpleNamespace(result=image, text_regions=[region])
        with TestClient(create_core(Engine())) as client:
            result = client.post("/translate/with-form/image", files={"image": ("p.png", page, "image/png")})
            self.assertEqual(result.status_code, 200, result.text)
            rows = client.get(f"/regions/{hashlib.sha256(page).hexdigest()}").json()
            self.assertEqual(rows[0]["caixa"], [1, 2, 30, 40])
            self.assertEqual(rows[0]["traducao"], "OI")
            self.assertEqual(client.get("/regions/" + "0" * 64).status_code, 404)

    def test_boxes_of_a_stitched_page_match_the_page_sent(self):
        # A webtoon page is translated with a slice of the page above on top; the report's
        # boxes are moved back onto the page the app sent.
        region = SimpleNamespace(xyxy=(5, 130, 50, 160), text="HI", translation="OI")
        self.assertEqual(report_rows(SimpleNamespace(text_regions=[region]), top=100)[0]["caixa"], [5, 30, 50, 60])


class PairingTest(unittest.TestCase):
    """parear.py: the QR code the app reads (MangalatePairing on the app side)."""
    KEY = "k" * 43

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def folder(self, bind="0.0.0.0"):
        root = Path(self.tmp.name)
        (root / "secrets").mkdir(exist_ok=True)
        (root / "secrets" / "mangalate_key.txt").write_text(self.KEY)
        (root / ".env").write_text(f"MANGALATE_PROFILE=byok\nMANGALATE_BIND={bind}\n")
        return root

    def test_link_has_address_and_key_encoded(self):
        from parear import pairing_link
        # The same link the app's unit test parses (MangalatePairingTest).
        fixture = json.loads((Path(__file__).parent / "app_pairing_contract.json").read_text(encoding="utf-8"))
        self.assertEqual(pairing_link(fixture["address"], fixture["key"]), fixture["link"])

    def test_no_code_while_the_server_only_accepts_this_computer(self):
        import parear
        lines = []
        self.assertFalse(parear.show(self.folder("127.0.0.1"), address="192.168.0.10", out=lines.append))
        self.assertNotIn(self.KEY, "\n".join(lines))

    def test_code_shows_the_address_but_never_the_key_as_text(self):
        import parear
        lines = []
        shown = parear.show(self.folder(), address="192.168.0.10", out=lines.append)
        text = "\n".join(lines)
        self.assertNotIn(self.KEY, text)
        try:
            import qrcode  # noqa: F401
        except ImportError:
            self.assertFalse(shown)
            self.assertIn("pip install qrcode", text)
            return
        self.assertTrue(shown)
        self.assertIn("http://192.168.0.10:5003", text)


if __name__ == "__main__":
    unittest.main()
