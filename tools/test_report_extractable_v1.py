"""Supplementary analysis must retain missing/failed rows and frozen QA scope."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ENACT"))
from scripts.usim import report_extractable_v1 as report


class ReportIntegrity(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name)
        self.condition = self.run / "A"
        self.condition.mkdir()
        self.qa = self.run / "qa.jsonl"
        self.write_rows(self.qa, [{"id": "q1", "key_frame_ids": ["0", "1", "2"], "gt_answer": [2, 1]},
                                 {"id": "q2", "key_frame_ids": ["0", "1", "2"], "gt_answer": [2, 1]}])
        (self.condition / "run_config.json").write_text(json.dumps({
            "qa_path": str(self.qa), "qa_sha256": hashlib.sha256(self.qa.read_bytes()).hexdigest()}), encoding="utf-8")
        self.items = [{"id": "q1", "num_states": 3, "gt": [2, 1], "parsed": [2, 1]},
                      {"id": "q2", "num_states": 3, "gt": [2, 1], "parsed": None}]
        self.write_rows(self.condition / "report.items.jsonl", self.items)
        self.predictions = [{"id": "q1", "status": "success", "finish_reason": "stop", "answer": "[2, 1]"}]
        self.write_rows(self.condition / "predictions.jsonl", self.predictions)

    @staticmethod
    def write_rows(path, rows):
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def test_missing_answers_stay_in_denominator(self):
        result = report.analyse(self.run, "A", "A")
        self.assertEqual(result["questions"], 2)
        self.assertEqual(result["extractable"], 1)
        self.assertEqual(result["EM_extractable"], 0.5)

    def test_failed_response_cannot_pass_even_with_stop_and_valid_answer(self):
        self.predictions[0]["status"] = "failed"
        self.write_rows(self.condition / "predictions.jsonl", self.predictions)
        result = report.analyse(self.run, "A", "A")
        self.assertEqual(result["extractable"], 0)
        self.assertIn("response_not_success:failed", result["zero_reasons"])

    def test_wrong_but_extractable_answer_is_not_counted_correct(self):
        self.predictions[0]["answer"] = "reasoning [1, 2]"
        self.write_rows(self.condition / "predictions.jsonl", self.predictions)
        result = report.analyse(self.run, "A", "A")
        self.assertEqual(result["extractable"], 1)
        self.assertEqual(result["EM_extractable"], 0.0)

    def test_duplicate_predictions_are_rejected(self):
        self.write_rows(self.condition / "predictions.jsonl", self.predictions * 2)
        with self.assertRaisesRegex(ValueError, "Duplicate IDs"):
            report.analyse(self.run, "A", "A")

    def test_unknown_predictions_are_rejected(self):
        self.write_rows(self.condition / "predictions.jsonl", self.predictions + [{"id": "unknown"}])
        with self.assertRaisesRegex(ValueError, "unknown IDs"):
            report.analyse(self.run, "A", "A")

    def test_missing_scored_items_cannot_shrink_denominator(self):
        self.write_rows(self.condition / "report.items.jsonl", self.items[:1])
        with self.assertRaisesRegex(ValueError, "full frozen QA"):
            report.analyse(self.run, "A", "A")

    def test_changed_qa_is_rejected(self):
        self.qa.write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "QA hash"):
            report.analyse(self.run, "A", "A")

    def test_reference_conflict_is_rejected(self):
        self.items[0]["num_states"] = 4
        self.write_rows(self.condition / "report.items.jsonl", self.items)
        with self.assertRaisesRegex(ValueError, "reference differs"):
            report.analyse(self.run, "A", "A")

    def test_output_cannot_overwrite_source_predictions(self):
        with self.assertRaisesRegex(ValueError, "outside the source run"):
            report.main(["--run-dir", str(self.run), "--out-json", str(self.condition / "predictions.jsonl")])


class ExistingDevelopmentRegression(unittest.TestCase):
    def test_all_326_responses_keep_previous_parseable_counts(self):
        base = report.ROOT / "data/usim_enact/runs/qwen3.8-max"
        cases = (("v02_dev_001", "A_full_image", 84, 84),
                 ("v02_dev_001", "B_zoom", 75, 75),
                 ("v02_dev_001", "C_text_only", 84, 84),
                 ("v02_dev_001", "D_no_action_text", 42, 42),
                 ("v02_budget1024_diag_v1", "A_full_image", 16, 16),
                 ("v02_budget1024_diag_v1", "B_zoom", 13, 15))
        total = 0
        for run, label, strict, extractable in cases:
            with self.subTest(run=run, condition=label):
                result = report.analyse(base / run, label, label)
                self.assertEqual((result["strict_valid"], result["extractable"]), (strict, extractable))
                total += result["questions"]
        self.assertEqual(total, 326)


if __name__ == "__main__":
    unittest.main()
