"""Rented GPU machine: one container configured by environment variables."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cloud


class CloudTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def prepare(self, env, workspace=True):
        work = self.tmp / "workspace"
        if workspace:
            work.mkdir(exist_ok=True)
        return cloud.prepare(env, secrets_dir=self.tmp / "secrets", workspace=work, models=self.tmp / "models")

    def test_keys_become_files_and_leave_the_environment(self):
        env = self.prepare({"MANGALATE_KEY": "x" * 30, "GROQ_API_KEY": "gsk_1", "GEMINI_API_KEY": "AIza2", "PATH": "/bin"})
        self.assertEqual((self.tmp / "secrets/mangalate_key").read_text().strip(), "x" * 30)
        providers = json.loads((self.tmp / "secrets/provider_key").read_text())["providers"]
        self.assertEqual([p["name"] for p in providers], ["groq", "gemini"])
        self.assertEqual(providers[0]["key"], "gsk_1")
        for name in ("MANGALATE_KEY", "GROQ_API_KEY", "GEMINI_API_KEY"):
            self.assertNotIn(name, env)
        self.assertEqual(env["MANGALATE_PROFILE"], "byok")
        self.assertEqual(env["MANGALATE_UPSTREAM"], "http://127.0.0.1:8001")
        self.assertEqual(env["PATH"], "/bin")

    def test_missing_password_is_created_and_short_one_refused(self):
        self.prepare({"GROQ_API_KEY": "gsk_1"})
        self.assertGreaterEqual(len((self.tmp / "secrets/mangalate_key").read_text().strip()), 24)
        with self.assertRaises(SystemExit):
            self.prepare({"MANGALATE_KEY": "curta", "GROQ_API_KEY": "gsk_1"})

    def test_needs_an_ai_key_and_openrouter_needs_a_model(self):
        with self.assertRaises(SystemExit):
            self.prepare({"MANGALATE_KEY": "x" * 30})
        with self.assertRaises(SystemExit):
            self.prepare({"MANGALATE_KEY": "x" * 30, "OPENROUTER_API_KEY": "sk-or-1"})
        self.prepare({"MANGALATE_KEY": "x" * 30, "OPENROUTER_API_KEY": "sk-or-1", "OPENROUTER_MODEL": "m:free"})

    def test_models_and_memory_survive_on_the_persistent_disk(self):
        models = self.tmp / "models"
        models.mkdir()
        (models / "detector.ckpt").write_text("baked")
        env = self.prepare({"GROQ_API_KEY": "gsk_1"})
        self.assertTrue(models.is_symlink())
        self.assertEqual((models / "detector.ckpt").read_text(), "baked")
        self.assertTrue(env["MANGALATE_MEMORY_DIR"].startswith(str(self.tmp / "workspace")))
        self.prepare({"GROQ_API_KEY": "gsk_1"})  # restart: nothing to move again
        self.assertTrue(models.is_symlink())

    def test_without_persistent_disk_nothing_moves(self):
        env = self.prepare({"GROQ_API_KEY": "gsk_1"}, workspace=False)
        self.assertNotIn("MANGALATE_MEMORY_DIR", env)
        self.assertFalse((self.tmp / "models").exists())


if __name__ == "__main__":
    unittest.main()
