"""Regression checks for incomplete listings and undetected file corruption."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hf_snapshot_download import list_snapshot, local_path, verified


class SnapshotTests(unittest.TestCase):
    def test_follows_next_page_at_pinned_commit(self):
        commit = "a" * 40
        next_url = f"https://huggingface.co/api/datasets/user/data/tree/{commit}?cursor=page2"
        responses = [
            ({"sha": commit, "siblings": [{"rfilename": "one"}, {"rfilename": "two"}]}, ""),
            ([{"type": "file", "path": "one", "size": 1}], f'<{next_url}>; rel="next"'),
            ([{"type": "file", "path": "two", "size": 2}], ""),
        ]
        with patch("hf_snapshot_download.get_json", side_effect=responses) as fetch:
            result = list_snapshot("https://huggingface.co", "user/data", "main")
        self.assertEqual([entry["path"] for entry in result["files"]], ["one", "two"])
        self.assertIn(f"/tree/{commit}?", fetch.call_args_list[1].args[0])
        self.assertEqual(fetch.call_args_list[2].args[0], next_url)

    def test_rejects_truncated_listing_without_next_link(self):
        responses = [
            ({"sha": "a" * 40, "siblings": [{"rfilename": "one"}, {"rfilename": "two"}]}, ""),
            ([{"type": "file", "path": "one", "size": 1}], ""),
        ]
        with patch("hf_snapshot_download.get_json", side_effect=responses):
            with self.assertRaisesRegex(ValueError, "sibling list"):
                list_snapshot("https://huggingface.co", "user/data", "main")

    def test_detects_same_size_corruption_and_git_blob_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "file"
            path.write_bytes(b"good")
            item = {"path": "file", "size": 4, "sha256": hashlib.sha256(b"good").hexdigest()}
            self.assertTrue(verified(path, item))
            git_item = {"path": "file", "size": 4,
                        "git_blob_sha1": hashlib.sha1(b"blob 4\0good").hexdigest()}
            self.assertTrue(verified(path, git_item))
            path.write_bytes(b"oops")
            self.assertFalse(verified(path, item))
            self.assertFalse(verified(path, git_item))

    def test_rejects_paths_outside_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            for path in ("../file", "C:/file", "/file", "folder\\file"):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    local_path(Path(temp), path)


if __name__ == "__main__":
    unittest.main()
