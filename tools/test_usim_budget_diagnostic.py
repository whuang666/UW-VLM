"""Guards against changed inputs and selective retries in the paid diagnostic."""

import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch


SCRIPT = Path(__file__).resolve().parents[1] / "ENACT/scripts/usim/run_v02_budget_diagnostic.py"
SPEC = importlib.util.spec_from_file_location("budget_diagnostic", SCRIPT)
budget = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(budget)


class BudgetDiagnosticTests(unittest.TestCase):
    def test_selection_ignores_order_answers_and_old_outcomes(self):
        rows = budget.load_rows(budget.SOURCE_RUN / "inputs/dev.jsonl")
        expected = [row["id"] for row in budget.select_questions(rows)]
        changed = copy.deepcopy(list(reversed(rows)))
        for row in changed:
            row["gt_answer"] = [999]
            row["old_exact_match"] = 0
            row["old_finish_reason"] = "length"
        self.assertEqual(expected, [row["id"] for row in budget.select_questions(changed)])
        self.assertEqual(len(expected), 16)
        self.assertEqual(len(set(expected)), 16)

    def test_selected_a_b_have_identical_question_and_reference_order(self):
        a = budget.load_rows(budget.SOURCE_RUN / "inputs/dev.jsonl")
        b = budget.load_rows(budget.SOURCE_RUN / "inputs/dev_B.jsonl")
        budget.validate_pairs(a, b)
        for field in ("question", "gt_answer", "key_frame_ids", "source_images"):
            changed = copy.deepcopy(b)
            changed[0][field] = "changed"
            with self.subTest(field=field), self.assertRaises(ValueError):
                budget.validate_pairs(a, changed)

    def test_duplicate_or_mismatched_ids_are_rejected(self):
        a = budget.load_rows(budget.SOURCE_RUN / "inputs/dev.jsonl")
        b = budget.load_rows(budget.SOURCE_RUN / "inputs/dev_B.jsonl")
        with self.assertRaises(ValueError):
            budget.select_questions(a + a[:1])
        with self.assertRaises(ValueError):
            budget.validate_pairs(a, b[:-1])

    def test_prepared_inputs_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "inputs/A.jsonl"
            budget.write_once(path, b"original\n")
            budget.write_once(path, b"original\n")
            with self.assertRaises(ValueError):
                budget.write_once(path, b"changed\n")
            self.assertEqual(path.read_bytes(), b"original\n")

    def test_diagnostic_cannot_write_inside_frozen_evidence(self):
        for path in (budget.SOURCE_RUN, budget.SOURCE_RUN / "new",
                     budget.DATA_ROOT / "new", budget.BASE / "_protocol/new"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                budget.validate_destination(path)

    def test_missing_key_sends_no_request(self):
        with patch.object(budget, "execution_environment", return_value={}), \
                patch.object(budget, "checked_process") as request:
            with self.assertRaisesRegex(ValueError, "VLM_API_KEY"):
                budget.run_real(Path("unused"), {}, False)
            request.assert_not_called()

    def test_process_key_takes_priority_over_persistent_key(self):
        registry = MagicMock()
        with patch.dict(budget.os.environ, {"VLM_API_KEY": "process-placeholder"}, clear=True), \
                patch.dict("sys.modules", {"winreg": registry}):
            self.assertEqual(budget.execution_environment()["VLM_API_KEY"], "process-placeholder")
            registry.OpenKey.assert_not_called()

    def test_stale_windows_process_loads_user_environment(self):
        registry = MagicMock()
        registry.QueryValueEx.return_value = ("persistent-placeholder", 1)
        with patch.dict(budget.os.environ, {}, clear=True), \
                patch.object(budget.os, "name", "nt"), \
                patch.dict("sys.modules", {"winreg": registry}):
            self.assertEqual(budget.execution_environment()["VLM_API_KEY"], "persistent-placeholder")
            registry.QueryValueEx.assert_called_once()

    def test_existing_answers_require_explicit_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            path = run / "A_full_image/predictions.jsonl"
            budget.write_once(path, b'{"id":"selected","status":"truncated"}\n')
            with patch.object(budget, "execution_environment", return_value={"VLM_API_KEY": "test-placeholder"}), \
                    patch.object(budget, "checked_process") as request:
                with self.assertRaisesRegex(ValueError, "--resume"):
                    budget.run_real(run, {"selected_ids": ["selected"]}, False)
                request.assert_not_called()

    def test_unknown_resume_ids_send_no_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            budget.write_once(run / "B_zoom/predictions.jsonl", b'{"id":"unselected"}\n')
            with patch.object(budget, "execution_environment", return_value={"VLM_API_KEY": "test-placeholder"}), \
                    patch.object(budget, "checked_process") as request:
                with self.assertRaisesRegex(ValueError, "unknown IDs"):
                    budget.run_real(run, {"selected_ids": ["selected"]}, True)
                request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
