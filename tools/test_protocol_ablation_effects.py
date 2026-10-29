"""Statistical invariants for whole-episode paired analysis; no HTTP calls."""

import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ENACT"))
from scripts.usim import report_protocol_ablation_effects as stats


def item(qid, episode, correct, *, transitions=2, pa=None, extracted=True, secondary=None):
    return {"id": qid, "task_name": episode, "num_states": transitions + 1, "num_transitions": transitions,
            "gt": list(range(1, transitions + 1)), "exact_match": int(correct), "task_accuracy": int(correct),
            "pairwise_accuracy": float(correct) if pa is None else pa,
            "parsed": list(range(1, transitions + 1)) if extracted else None,
            "secondary_correct": bool(correct) if secondary is None else secondary, "extractable": extracted,
            "secondary_permutation": list(range(1, transitions + 1)) if extracted else None,
            "truncated": False, "reason": "ok" if extracted else "extra_text"}


class EpisodeBootstrap(unittest.TestCase):
    def test_point_is_question_weighted_and_draws_whole_episodes(self):
        rows = [item(str(i), "episode_a", True) for i in range(10)] + [item("last", "episode_b", False)]
        result = stats.bootstrap_contrast([(1., rows)], 10000, 42)
        self.assertEqual(result["episodes"], 2)
        self.assertAlmostEqual(result["metrics"]["EM"]["point"], 10 / 11)
        self.assertEqual(result["metrics"]["EM"]["ci_low"], 0.0)
        self.assertEqual(result["metrics"]["EM"]["ci_high"], 1.0)

    def test_identical_paired_outcomes_have_zero_uncertainty_of_difference(self):
        rows = [item("a", "episode_a", True), item("b", "episode_b", False)]
        result = stats.bootstrap_contrast([(1., rows), (-1., copy.deepcopy(rows))], 1000, 42)
        for metric in result["metrics"].values():
            self.assertEqual(metric, {"point": 0.0, "ci_low": 0.0, "ci_high": 0.0})

    def test_micro_pa_weights_full_transition_denominator(self):
        rows = [item("a", "episode_a", True, transitions=1), item("b", "episode_b", False, transitions=3, extracted=False)]
        block = stats.metric_block(rows)
        self.assertEqual(block["PA_item_mean"], .5)
        self.assertEqual(block["PA_transition_micro"], .25)
        boot = stats.bootstrap_contrast([(1., rows)], 1000, 7)
        self.assertEqual(boot["metrics"]["PA_transition_micro"]["point"], .25)

    def test_repeated_seed_gives_identical_result(self):
        rows = [item("a", "episode_a", True), item("b", "episode_b", False), item("c", "episode_c", True)]
        self.assertEqual(stats.bootstrap_contrast([(1., rows)], 1000, 19), stats.bootstrap_contrast([(1., rows)], 1000, 19))

    def test_primary_effect_uses_unrounded_counts(self):
        a = [item(str(i), f"episode_{i}", i < 2) for i in range(3)]
        b = [item(str(i), f"episode_{i}", i < 1) for i in range(3)]
        result = stats.comparison(a, b, 1000, 42)
        self.assertAlmostEqual(result["bootstrap"]["metrics"]["EM"]["point"], 1 / 3)
        self.assertEqual(result["paired_strict_counts"]["only_first"], 1)

    def test_empty_support_is_rejected(self):
        with self.assertRaises(ValueError):
            stats.bootstrap_contrast([(1., [])], 100, 42)


class PairedScope(unittest.TestCase):
    def test_missing_paired_question_rejected_unless_declared_subset(self):
        a = [item("a", "episode_a", True), item("b", "episode_b", False)]
        with self.assertRaises(ValueError):
            stats.pair_rows(a, a[:1])
        x, y = stats.pair_rows(a, a[:1], allow_subset=True)
        self.assertEqual(len(x), 1)
        self.assertEqual(len(y), 1)

    def test_reference_conflict_rejected(self):
        a = [item("a", "episode_a", True)]
        b = copy.deepcopy(a)
        b[0]["gt"] = [2, 1]
        with self.assertRaises(ValueError):
            stats.pair_rows(a, b)

    def test_extractable_wrong_answers_do_not_raise_secondary_em(self):
        rows = [item("a", "episode_a", False, extracted=True, secondary=False), item("b", "episode_b", True)]
        block = stats.metric_block(rows)
        self.assertEqual(block["extractable_rate"], 1.)
        self.assertEqual(block["secondary_EM_full_denominator"], .5)

    def test_latency_keeps_retry_time_and_attempt_counts(self):
        predictions = [{"status": "success", "finish_reason": "stop", "model_returned": "model", "usage": {
            "prompt_tokens": 100, "completion_tokens": 5, "total_tokens": 105}}]
        attempts = [{"job_id": "a", "http_status": 503, "elapsed_seconds": 1., "started_at": "2026-10-28T12:00:00+08:00", "finished_at": "2026-10-28T12:00:01+08:00"},
                    {"job_id": "a", "http_status": 200, "elapsed_seconds": 2., "started_at": "2026-10-28T12:00:03+08:00", "finished_at": "2026-10-28T12:00:05+08:00"}]
        result = stats.usage_block(predictions, attempts)
        self.assertEqual(result["retries"], 1)
        self.assertEqual(result["logical_latency_seconds_including_retry_wait"]["sum"], 5.)
        self.assertEqual(result["api_attempt_latency_seconds"]["sum"], 3.)


if __name__ == "__main__":
    unittest.main()
