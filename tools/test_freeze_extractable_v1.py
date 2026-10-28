"""Freeze verification must detect changed sources, edited payloads and overwrites."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ENACT"))
from scripts.usim import freeze_extractable_v1 as freeze


class FreezeIntegrity(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "rules.txt").write_text("trailing whitespace only\n", encoding="utf-8")
        self.manifest = freeze.build_manifest(self.root, ["rules.txt"], {"passed": True}, "fixture")

    def test_fresh_manifest_verifies(self):
        self.assertTrue(freeze.verify_manifest(self.manifest, self.root)["ok"])

    def test_changed_source_is_detected(self):
        (self.root / "rules.txt").write_text("allow punctuation\n", encoding="utf-8")
        self.assertFalse(freeze.verify_manifest(self.manifest, self.root)["ok"])

    def test_missing_source_is_detected(self):
        (self.root / "rules.txt").unlink()
        self.assertFalse(freeze.verify_manifest(self.manifest, self.root)["ok"])

    def test_changed_manifest_payload_is_detected(self):
        self.manifest["punctuation_tolerance"] = True
        self.assertFalse(freeze.verify_manifest(self.manifest, self.root)["ok"])

    def test_existing_registration_cannot_be_overwritten(self):
        path = self.root / "registration.json"
        freeze.write_manifest(path, self.manifest)
        before = path.read_bytes()
        with self.assertRaises(FileExistsError):
            freeze.write_manifest(path, self.manifest)
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
