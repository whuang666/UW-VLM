"""Boundary tests for extractable_permutation_v1 (secondary metric).

The metric only ever relaxes the *outer* envelope (prose around a trailing list).  The
inner value rules must stay identical to ``USIMEvaluator.parse_strict``, so one test pins
that equivalence by comparing the two implementations on bare-list inputs.
"""

import importlib.util
import inspect
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ENACT/scripts/usim/extractable_v1.py"
SPEC = importlib.util.spec_from_file_location("extractable_v1", SCRIPT)
extractable = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extractable)

sys.path.insert(0, str(ROOT / "ENACT"))
from scripts.usim.evaluate import USIMEvaluator  # noqa: E402


def run(text, finish="stop", n=3):
    return extractable.extract(text, finish, n)


class TrailingListEnvelope(unittest.TestCase):
    def test_bare_list_at_end(self):
        result = run("[2, 1, 3]")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["permutation"], [2, 1, 3])

    def test_prose_then_list_at_end_is_accepted(self):
        """The whole point of the metric: reasoning prose is allowed, the list is what counts."""
        text = ("Based on the provided actions and images:\n\n1. **Action 1:** the gripper descends.\n"
                "2. **Action 2:** it grasps.\n3. **Action 3:** it lifts.\n\nTherefore: [2, 1, 3]")
        result = run(text)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["permutation"], [2, 1, 3])

    def test_trailing_whitespace_and_newlines_allowed(self):
        self.assertEqual(run("[2, 1, 3]\n\n  ")["status"], "ok")

    def test_trailing_punctuation_is_rejected(self):
        """Conservative reading of "at the end": nothing but whitespace may follow."""
        result = run("[2, 1, 3].")
        self.assertEqual(result["status"], "zero")
        self.assertEqual(result["reason"], "list_not_at_end")

    def test_full_width_punctuation_is_rejected(self):
        self.assertEqual(run("[2, 1, 3]。")["reason"], "list_not_at_end")

    def test_extra_or_unclosed_brackets_are_not_skipped(self):
        for text in ("[[2, 1, 3]", "unclosed [ prose [2, 1, 3]", "] [2, 1, 3]", "[[2, 1, 3]]"):
            with self.subTest(text=text):
                self.assertEqual(run(text)["status"], "zero")

    def test_two_lists_rejected(self):
        result = run("First guess [1, 2, 3], corrected answer [2, 1, 3]")
        self.assertEqual(result["status"], "zero")
        self.assertEqual(result["reason"], "multiple_lists")
        self.assertEqual(result["list_count"], 2)

    def test_echoed_action_brackets_count_as_a_second_list(self):
        result = run('**Action 1:** "[Action 1]" matches. Answer: [2, 1, 3]')
        self.assertEqual(result["status"], "zero")
        self.assertEqual(result["reason"], "multiple_lists")

    def test_list_not_at_end(self):
        result = run("[2, 1, 3] and that is my final answer")
        self.assertEqual(result["reason"], "list_not_at_end")

    def test_no_list(self):
        self.assertEqual(run("I cannot determine the order.")["reason"], "no_list")

    def test_unclosed_bracket(self):
        self.assertEqual(run("answer: [2, 1")["reason"], "no_list")

    def test_malformed_body(self):
        self.assertEqual(run("[2, 1, 3,]")["reason"], "unparsable")


class Eligibility(unittest.TestCase):
    def test_truncated_response_scores_zero_even_with_trailing_list(self):
        result = run("reasoning ... [2, 1, 3]", finish="length")
        self.assertEqual(result["status"], "zero")
        self.assertEqual(result["reason"], "not_stop:length")

    def test_unknown_finish_reason_scores_zero(self):
        self.assertEqual(run("[2, 1, 3]", finish=None)["reason"], "not_stop:None")

    def test_missing_and_empty(self):
        self.assertEqual(run(None)["reason"], "missing")
        self.assertEqual(run("   \n ")["reason"], "missing")

    def test_non_string(self):
        self.assertEqual(run(123)["reason"], "bad_type")


class ValueRules(unittest.TestCase):
    def test_wrong_length(self):
        self.assertEqual(run("[1, 2]", n=3)["reason"], "wrong_length")

    def test_non_integer(self):
        # json parses both of these into a list, so the failure is the value rule, not the syntax
        self.assertEqual(run("[1, 2.0, 3]")["reason"], "non_integer")
        self.assertEqual(run('["1", 2, 3]')["reason"], "non_integer")

    def test_boolean_is_not_an_integer(self):
        self.assertEqual(run("[true, 2, 3]")["reason"], "non_integer")

    def test_duplicate_and_out_of_range(self):
        self.assertEqual(run("[1, 1, 3]")["reason"], "not_a_permutation")
        self.assertEqual(run("[1, 2, 4]")["reason"], "not_a_permutation")

    def test_accepts_lengths_two_to_five(self):
        for length in (2, 3, 4, 5):
            permutation = list(range(1, length + 1))
            self.assertEqual(run(str(permutation).replace(" ", " "), n=length)["status"], "ok")


class EquivalenceWithStrictParser(unittest.TestCase):
    """On bare lists the two implementations must agree exactly."""

    CASES = [
        "[2, 1]", "[2, 1, 3]", "[1, 2, 3]", "[3, 2, 1]",
        "[1, 1, 3]", "[1, 2, 4]", "[1, 2]", "[1, 2, 3, 4]",
        "[]", "[true, 2, 3]", "[1, 2.0, 3]", "[1, 2, 3,]",
    ]

    def test_reasons_match(self):
        for text in self.CASES:
            for length in (2, 3, 4):
                strict_value, strict_reason = USIMEvaluator.parse_strict(text, length)
                mine = extractable.extract(text, "stop", length)
                with self.subTest(text=text, length=length):
                    self.assertEqual(mine["reason"], strict_reason)
                    if strict_value is None:
                        self.assertIsNone(mine["permutation"])
                    else:
                        self.assertEqual(mine["permutation"], strict_value)


class Contract(unittest.TestCase):
    def test_candidate_is_delegated_to_primary_parser(self):
        with patch.object(USIMEvaluator, "parse_strict", return_value=([2, 1, 3], "ok")) as parser:
            self.assertEqual(run("reasoning [2, 1, 3]")["status"], "ok")
            parser.assert_called_once_with("[2, 1, 3]", 3)

    def test_extract_never_receives_ground_truth(self):
        parameters = list(inspect.signature(extractable.extract).parameters)
        self.assertEqual(parameters, ["text", "finish_reason", "expected_length"])

    def test_version_is_pinned(self):
        self.assertEqual(extractable.VERSION, "extractable_permutation_v1")


if __name__ == "__main__":
    unittest.main()
