"""The app's configuration contract, shared with ServerContractTest.kt through app_config_contract.json."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gateway import art_choice, profile_config

CONTRACT = json.loads((Path(__file__).parent / "app_config_contract.json").read_text(encoding="utf-8"))
# Every field the gateway reads from the app; anything else would be ignored silently.
READ_BY_GATEWAY = {"translator": {"target_lang"}, "render": {"font_size_offset", "uppercase"}, "arte": None}


class ContractTest(unittest.TestCase):
    def test_the_gateway_applies_what_the_app_sends(self):
        for case in CONTRACT["cases"]:
            for profile in ("basic", "byok"):
                with self.subTest(case=case["name"], profile=profile):
                    config = profile_config(profile, case["sent"], speed="quality")
                    expected = case["server"]
                    self.assertEqual(config["translator"]["target_lang"], expected["target_lang"])
                    self.assertEqual(config["render"]["font_size_offset"], expected["font_size_offset"])
                    self.assertEqual(config["render"]["uppercase"], expected["uppercase"])
                    self.assertEqual(art_choice(case["sent"]), expected["art"])

    def test_the_app_sends_only_what_the_gateway_reads(self):
        for case in CONTRACT["cases"]:
            for key, value in case["sent"].items():
                with self.subTest(case=case["name"], key=key):
                    self.assertIn(key, READ_BY_GATEWAY)
                    if READ_BY_GATEWAY[key] is not None:
                        self.assertLessEqual(set(value), READ_BY_GATEWAY[key])


if __name__ == "__main__":
    unittest.main()
