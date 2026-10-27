"""Contract tests for the (proposed) ``usim_strict_v0.3`` scoring contract.

``evaluate.py`` (``usim_strict_v0.2``) already fixes the four P0 items of
docs/WBW §3.  Two scoring-relevant gaps remain, and both can only be tested with
*synthetic* data because the frozen v0.1 set does not contain the situations:

a. **Multiple semantically valid orders.**  ``evaluate.py`` computes TA from the
   verifier, so if two permutations are accepted both must get ``TA=1`` while EM
   must still recognise only the reference permutation.  The check enumerates a
   synthetic case whose reference transitions are signature-subsets of the
   swapped order and asserts ``TA=1`` for both, ``EM`` for one, and
   ``semantic_only=0.5`` in the summary.
b. **Non-exchangeable actions.**  Swapping a genuinely ordered pair (grasp then
   lift) must give ``TA=0``; this guards against a verifier that only compares
   sets and ignores order.
c. **Empty reference signatures / empty visible transitions.**  The empty set is
   a subset of everything, so the upstream verifier accepts *every* permutation
   when a reference transition has an empty visible signature -- a false
   semantic pass.  The test documents that upstream behaviour, then asserts the
   v0.3 reference guard rejects such a record and scores it 0 instead of 1.
d. **Fixed denominator + strict parsing boundaries.**  L=3 perfect + L=4 missing
   must yield ``PA_transition_micro = 0.4``; explanation text / multiple arrays /
   non-permutations must all be invalid with zero score.
e. **Duplicate / unknown prediction IDs** are rejected (exit code 2 from
   ``evaluate.main``), while a valid file for the same question is accepted.

Synthetic scene graphs are fed through a stub ``SceneGraphReader``; every fixture
lives in memory, so no v0.1 file is written or modified.  Real v0.1 data is only
*read* for the duplicate/unknown-ID probe of the existing ``evaluate.main``.

Usage:
    python -m scripts.usim.check_scoring_contract_v2

Exit code 0 = every test passed; 1 = at least one failed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enact.adapters.usim_annotations import PROTOCOL_VERSION  # noqa: E402
from enact.utils.qa_gen_utils import TaskData  # noqa: E402
from scripts.usim import evaluate as evaluate_module  # noqa: E402
from scripts.usim.evaluate import (  # noqa: E402
    DEFAULT_DATA_ROOT,
    EVALUATION_PROTOCOL,
    USIMEvaluator,
    USIMVerifier,
    load_jsonl,
    load_predictions,
)

DEFAULT_OUT = ROOT / "data" / "usim_enact" / "_protocol" / "contract" / "check_scoring_contract_v2.json"
CONTRACT_VERSION = "usim_strict_v0.3"
TZ_SHANGHAI = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(TZ_SHANGHAI).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------- fixtures
def diff_add_nodes(*items: Tuple[str, Sequence[str]]) -> Dict[str, Any]:
    return {"add": {"nodes": [{"name": name, "states": list(states)} for name, states in items],
                    "edges": []},
            "remove": {"nodes": [], "edges": []}}


def diff_add_edges(*items: Tuple[str, str, Sequence[str]]) -> Dict[str, Any]:
    return {"add": {"nodes": [],
                    "edges": [{"from": source, "to": target, "states": list(states)}
                              for source, target, states in items]},
            "remove": {"nodes": [], "edges": []}}


def diff_remove_nodes(*items: Tuple[str, Sequence[str]]) -> Dict[str, Any]:
    return {"add": {"nodes": [], "edges": []},
            "remove": {"nodes": [{"name": name, "states": list(states)} for name, states in items],
                       "edges": []}}


def merge_diffs(*diffs: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {"add": {"nodes": [], "edges": []}, "remove": {"nodes": [], "edges": []}}
    for diff in diffs:
        for operation in ("add", "remove"):
            for kind in ("nodes", "edges"):
                merged[operation][kind].extend(diff[operation][kind])
    return merged


EMPTY_DIFF: Dict[str, Any] = {"type": "empty"}


class StubGraphReader:
    """Scene-graph reader that returns fixture diffs keyed by (from, to, partial)."""

    def __init__(self, diffs: Dict[Tuple[str, str, bool], Dict[str, Any]]) -> None:
        self._diffs = dict(diffs)
        self.calls = 0

    def get_visible_full_diff(self, from_id, to_id, sensor_names, partial_diff: bool = False) -> Dict[str, Any]:
        self.calls += 1
        return self._diffs.get((str(from_id), str(to_id), bool(partial_diff)), EMPTY_DIFF)


def make_record(record_id: str, task_name: str, direction: str, num_states: int,
                key_frame_ids: Sequence[str], gt: Sequence[int]) -> Dict[str, Any]:
    suffix = "forward" if direction == "forward" else "inverse"
    return {
        "id": record_id,
        "type": f"{suffix}_world_modeling_{num_states}_steps",
        "task_name": task_name,
        "key_frame_ids": list(key_frame_ids),
        "images": [],
        "question": "",
        "options": [],
        "gt_answer": list(gt),
    }


def stub_evaluator(reader: StubGraphReader, key_frame_ids: Sequence[str],
                   task_name: str = "synthetic_ordering_task") -> Tuple[USIMEvaluator, USIMVerifier]:
    """A USIMEvaluator whose verifier is backed by the in-memory stub reader."""
    task_data = TaskData(
        task_name=task_name,
        scene_graph_reader=reader,
        key_frame_ids=list(key_frame_ids),
        image_paths={},
        task_dir="",
        image_root_path=Path("."),
    )
    verifier = USIMVerifier(task_data)
    evaluator = USIMEvaluator(DEFAULT_DATA_ROOT)
    evaluator.verifier = lambda _task_name: verifier  # type: ignore[assignment]
    return evaluator, verifier


# ------------------------------------------------------- proposed v0.3 contract
class ContractViolation(RuntimeError):
    """Raised when the frozen question set itself cannot be scored (v0.3)."""


class ScoringContractV2:
    """Reference-spec implementation of the v0.3 contract additions.

    Not wired into ``evaluate.py`` (docs/WBW constraint: do not edit existing
    scripts without Lead approval); the script serves as the executable spec and
    as a regression test for the future scorer.
    """

    def __init__(self, evaluator: USIMEvaluator) -> None:
        self.evaluator = evaluator

    def reference_audit(self, record: Dict[str, Any]) -> Dict[str, Any]:
        verifier = self.evaluator.verifier(record["task_name"])
        signatures = verifier._translate_sequence_to_signatures(list(record["key_frame_ids"]), partial_diff=True)
        num_transitions = len(record["gt_answer"])
        empty_indices = [index for index, signature in enumerate(signatures) if not signature]
        problems: List[str] = []
        if len(signatures) != num_transitions:
            problems.append(f"reference transitions {len(signatures)} != answer length {num_transitions}")
        if empty_indices:
            problems.append(f"empty visible reference signatures at transitions {empty_indices}")
        return {
            "signatures": [sorted(signature) for signature in signatures],
            "empty_indices": empty_indices,
            "ok": not problems,
            "problems": problems,
        }

    def validate_records(self, records: Sequence[Dict[str, Any]]) -> None:
        problems: List[str] = []
        for record in records:
            audit = self.reference_audit(record)
            if not audit["ok"]:
                problems.append(f"{record['id']}: {'; '.join(audit['problems'])}")
        if problems:
            raise ContractViolation("参考转移无效，拒绝评分：\n  - " + "\n  - ".join(problems))

    def score_record(self, record: Dict[str, Any], answer: Any) -> Dict[str, Any]:
        gt = list(record["gt_answer"])
        parsed, parse_reason = self.evaluator.parse_strict(answer, len(gt))
        item: Dict[str, Any] = {
            "id": record["id"],
            "task_name": record["task_name"],
            "type": record["type"],
            "num_states": len(record["key_frame_ids"]),
            "num_transitions": len(gt),
            "gt": gt,
            "parsed": parsed,
            "reason": parse_reason,
            "raw": answer,
            "exact_match": 0.0,
            "semantic_match": 0.0,
            "task_accuracy": 0.0,
            "pairwise_accuracy": 0.0,
            "contract_version": CONTRACT_VERSION,
        }
        if parsed is None:
            return item
        audit = self.reference_audit(record)
        if not audit["ok"]:
            item["reason"] = "invalid_reference_transitions"
            item["reference_problems"] = audit["problems"]
            return item
        verifier = self.evaluator.verifier(record["task_name"])
        direction = "inverse" if "inverse" in record["type"] else "forward"
        method = verifier.verify_inverse if direction == "inverse" else verifier.verify_forward
        result, _ = method(list(record["key_frame_ids"]), gt, parsed)
        item["exact_match"] = float(bool(result["exact_match"]))
        item["semantic_match"] = float(bool(result["semantic_match"]))
        item["task_accuracy"] = float(bool(result["task_accuracy"]))
        item["pairwise_accuracy"] = float(result["pairwise_accuracy"])
        return item


# --------------------------------------------------------------------- helpers
def enumerate_verifier(verifier: USIMVerifier, record: Dict[str, Any],
                       direction: Optional[str] = None) -> Dict[int, Dict[str, Any]]:
    import itertools

    gt = list(record["gt_answer"])
    direction = direction or ("inverse" if "inverse" in record["type"] else "forward")
    method = verifier.verify_inverse if direction == "inverse" else verifier.verify_forward
    results: Dict[int, Dict[str, Any]] = {}
    for permutation in itertools.permutations(range(1, len(gt) + 1)):
        result, _ = method(list(record["key_frame_ids"]), gt, list(permutation))
        results[tuple(permutation)] = result
    return results


def items_from_scores(scores: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep only the keys evaluate.py's USIMEvaluator.summarise consumes."""
    keys = ("exact_match", "semantic_match", "task_accuracy", "pairwise_accuracy", "parsed",
            "num_transitions", "reason")
    return [{key: score.get(key) for key in keys} for score in scores]


def check(condition: bool, expected: Any, actual: Any, **extra: Any) -> Dict[str, Any]:
    block = {"pass": bool(condition), "expected": expected, "actual": actual}
    block.update(extra)
    return block


# ----------------------------------------------------------------------- tests
def test_a_multiple_valid_orders() -> Dict[str, Any]:
    """Two permutations are semantically accepted: both TA=1, EM only reference."""
    grasp = diff_add_nodes(("red_cylinder", ["InGripper"]))
    edge = diff_add_edges(("robot", "red_cylinder", ["NextTo"]))
    reader = StubGraphReader({
        ("s0", "s1", True): edge,
        ("s0", "s1", False): edge,
        ("s1", "s2", True): grasp,
        ("s1", "s2", False): grasp,
        # Moving from s0 straight to s2 contains both changes; moving "backwards"
        # from s2 to s1 is deliberately crafted to re-add both signatures so that
        # the swapped order is a semantic subset too (a true multi-answer case).
        ("s0", "s2", False): merge_diffs(edge, grasp),
        ("s2", "s1", False): merge_diffs(edge, grasp),
    })
    key_frame_ids = ["s0", "s1", "s2"]
    record = make_record("synthetic_multi_forward", "synthetic_multi", "forward", 3, key_frame_ids, [1, 2])
    evaluator, verifier = stub_evaluator(reader, key_frame_ids, "synthetic_multi")

    acceptance = enumerate_verifier(verifier, record)
    accepted = sorted(perm for perm, result in acceptance.items() if result["task_accuracy"])

    contract = ScoringContractV2(evaluator)
    reference_item = contract.score_record(record, [1, 2])
    alternative_item = contract.score_record(record, [2, 1])
    summary = evaluator.summarise(items_from_scores([reference_item, alternative_item]))

    checks = {
        "acceptance_set_contains_both_orders": check(accepted == [(1, 2), (2, 1)], [(1, 2), (2, 1)], accepted),
        "reference_TA": check(reference_item["task_accuracy"] == 1.0, 1.0, reference_item["task_accuracy"]),
        "alternative_TA": check(alternative_item["task_accuracy"] == 1.0, 1.0, alternative_item["task_accuracy"]),
        "alternative_is_semantic_only": check(
            alternative_item["semantic_match"] == 1.0 and alternative_item["exact_match"] == 0.0,
            {"semantic": 1.0, "exact": 0.0},
            {"semantic": alternative_item["semantic_match"], "exact": alternative_item["exact_match"]},
        ),
        "EM_only_reference": check(reference_item["exact_match"] == 1.0 and alternative_item["exact_match"] == 0.0,
                                   {"reference": 1.0, "alternative": 0.0},
                                   {"reference": reference_item["exact_match"],
                                    "alternative": alternative_item["exact_match"]}),
        "summary_TA": check(summary["TA"] == 1.0, 1.0, summary["TA"]),
        "summary_EM": check(summary["EM"] == 0.5, 0.5, summary["EM"]),
        "summary_semantic_only": check(summary["semantic_only"] == 0.5, 0.5, summary["semantic_only"]),
        "summary_PA_item_mean": check(summary["PA_item_mean"] == 1.0, 1.0, summary["PA_item_mean"]),
    }
    return {
        "description": "synthetic scene graph where two permutations are semantically accepted",
        "accepted_permutations": [list(permutation) for permutation in accepted],
        "reference_item": reference_item,
        "alternative_item": alternative_item,
        "summary": summary,
        "checks": checks,
        "pass": all(block["pass"] for block in checks.values()),
    }


def test_b_non_exchangeable_swap() -> Dict[str, Any]:
    """Swapping ordered actions (grasp -> lift) must fail TA."""
    grasp = diff_add_nodes(("red_cylinder", ["InGripper"]))
    lift = diff_add_nodes(("red_cylinder", ["Lifted"]))
    reader = StubGraphReader({
        ("f0", "f1", True): grasp,
        ("f0", "f1", False): grasp,
        ("f1", "f2", True): lift,
        ("f1", "f2", False): lift,
        ("f0", "f2", False): merge_diffs(grasp, lift),
        ("f2", "f1", False): diff_remove_nodes(("red_cylinder", ["Lifted"])),
    })
    key_frame_ids = ["f0", "f1", "f2"]
    forward = make_record("synthetic_swap_forward", "synthetic_swap", "forward", 3, key_frame_ids, [1, 2])
    evaluator, verifier = stub_evaluator(reader, key_frame_ids, "synthetic_swap")
    contract = ScoringContractV2(evaluator)

    reference_item = contract.score_record(forward, [1, 2])
    swapped_item = contract.score_record(forward, [2, 1])
    acceptance = enumerate_verifier(verifier, forward)
    accepted = sorted(perm for perm, result in acceptance.items() if result["task_accuracy"])

    # Inverse variant: same non-exchangeable pair, shuffled action labels.
    inverse = make_record("synthetic_swap_inverse", "synthetic_swap", "inverse", 3, key_frame_ids, [1, 2])
    inverse_reference = contract.score_record(inverse, [1, 2])
    inverse_swapped = contract.score_record(inverse, [2, 1])

    checks = {
        "forward_reference_TA": check(reference_item["task_accuracy"] == 1.0, 1.0, reference_item["task_accuracy"]),
        "forward_swapped_TA": check(swapped_item["task_accuracy"] == 0.0, 0.0, swapped_item["task_accuracy"]),
        "forward_swapped_EM": check(swapped_item["exact_match"] == 0.0, 0.0, swapped_item["exact_match"]),
        "forward_accepted_set_is_reference_only": check(accepted == [(1, 2)], [(1, 2)], accepted),
        "inverse_reference_TA": check(inverse_reference["task_accuracy"] == 1.0, 1.0,
                                      inverse_reference["task_accuracy"]),
        "inverse_swapped_TA": check(inverse_swapped["task_accuracy"] == 0.0, 0.0,
                                    inverse_swapped["task_accuracy"]),
    }
    return {
        "description": "grasp then lift: exchanging the two steps is not semantically equivalent",
        "forward_reference_item": reference_item,
        "forward_swapped_item": swapped_item,
        "inverse_reference_item": inverse_reference,
        "inverse_swapped_item": inverse_swapped,
        "checks": checks,
        "pass": all(block["pass"] for block in checks.values()),
    }


def test_c_empty_reference_transitions() -> Dict[str, Any]:
    """Empty (or invisibly filtered) reference signatures must be rejected, not passed."""
    import itertools

    no_visible_change = StubGraphReader({})
    invisible_change = StubGraphReader({
        # The underlying transition changes something, but nothing is visible in
        # the ego camera, so the reference visible signature is empty.
        ("v0", "v1", True): EMPTY_DIFF,
        ("v0", "v1", False): diff_add_nodes(("red_cylinder", ["InGripper"])),
        ("v1", "v2", True): EMPTY_DIFF,
        ("v1", "v2", False): diff_add_nodes(("red_cylinder", ["Lifted"])),
        ("v0", "v2", False): diff_add_nodes(("red_cylinder", ["InGripper"]), ("red_cylinder", ["Lifted"])),
        ("v2", "v1", False): diff_remove_nodes(("red_cylinder", ["Lifted"])),
    })
    results: Dict[str, Any] = {}
    all_checks_pass = True
    for name, reader, key_frame_ids in (
        ("empty_diff", no_visible_change, ["e0", "e1", "e2"]),
        ("invisible_change", invisible_change, ["v0", "v1", "v2"]),
    ):
        record = make_record(f"synthetic_{name}", f"synthetic_{name}", "forward", 3, key_frame_ids, [1, 2])
        evaluator, verifier = stub_evaluator(reader, key_frame_ids, f"synthetic_{name}")
        acceptance = enumerate_verifier(verifier, record)
        wrong_answer = [2, 1]
        upstream = acceptance[tuple(wrong_answer)]
        upstream_false_passes = sum(1 for result in acceptance.values() if result["task_accuracy"])

        contract = ScoringContractV2(evaluator)
        audit = contract.reference_audit(record)
        rejected_item = contract.score_record(record, wrong_answer)
        try:
            contract.validate_records([record])
            validation_raises = False
            validation_message = "no error raised"
        except ContractViolation as error:
            validation_raises = True
            validation_message = str(error).splitlines()[0]

        checks = {
            "upstream_accepts_own_reference": check(acceptance[(1, 2)]["task_accuracy"], True,
                                                    acceptance[(1, 2)]["task_accuracy"]),
            "upstream_false_pass_documented": check(upstream_false_passes == len(acceptance), len(acceptance),
                                                    upstream_false_passes,
                                                    note="empty signature is a subset of everything"),
            "upstream_wrong_answer_TA_is_1": check(upstream["task_accuracy"] is True, True,
                                                   upstream["task_accuracy"]),
            "v03_guard_flags_empty_reference": check(bool(audit["empty_indices"]), "non-empty empty_indices",
                                                     audit["empty_indices"]),
            "v03_rejected_answer_TA": check(rejected_item["task_accuracy"] == 0.0, 0.0,
                                            rejected_item["task_accuracy"]),
            "v03_rejected_answer_reason": check(rejected_item["reason"] == "invalid_reference_transitions",
                                                "invalid_reference_transitions", rejected_item["reason"]),
            "v03_precheck_raises": check(validation_raises, True, validation_raises),
        }
        passed = all(block["pass"] for block in checks.values())
        all_checks_pass = all_checks_pass and passed
        results[name] = {
            "permutations_total": len(acceptance),
            "upstream_false_passes": upstream_false_passes,
            "reference_audit": audit,
            "v03_rejected_item": rejected_item,
            "v03_validation_message": validation_message,
            "checks": checks,
            "pass": passed,
        }
    return {
        "description": "empty visible reference signature would make every permutation pass semantically",
        "cases": results,
        "pass": all_checks_pass,
    }


def test_d_fixed_denominator_and_strict_parsing() -> Dict[str, Any]:
    """L=3 perfect + L=4 missing -> PA_transition_micro 0.4; strict parsing has no back doors."""
    grasp = diff_add_nodes(("red_cylinder", ["InGripper"]))
    lift = diff_add_nodes(("red_cylinder", ["Lifted"]))
    reader = StubGraphReader({
        ("t0", "t1", True): grasp,
        ("t0", "t1", False): grasp,
        ("t1", "t2", True): lift,
        ("t1", "t2", False): lift,
    })
    l3 = make_record("synthetic_fixed_denominator_l3", "synthetic_fixed", "forward", 3, ["t0", "t1", "t2"], [1, 2])
    l4 = make_record("synthetic_fixed_denominator_l4", "synthetic_fixed", "forward", 4,
                     ["t0", "t1", "t2", "t3"], [1, 2, 3])
    evaluator, verifier = stub_evaluator(reader, ["t0", "t1", "t2"], "synthetic_fixed")
    # The L=4 record is deliberately missing from the predictions -> fixed denominator.
    result = evaluator.evaluate([l3, l4], {"synthetic_fixed_denominator_l3": [1, 2]})
    items = [item for bucket in result["items"].values() for item in bucket]
    summary = evaluator.summarise(items)

    # Strict parsing: prose / multiple arrays / non permutations are invalid and score 0.
    parser_cases = {
        "[1, 2]": ("ok", [1, 2]),
        "  [ 2, 1 ]  ": ("ok", [2, 1]),
        "Explanation: [1, 2]": ("extra_text", None),
        "[2, 1] then [1, 2]": ("unparsable", None),
        "The answer is [2, 1]": ("extra_text", None),
        "[0, 1]": ("not_a_permutation", None),
        "[1, 1]": ("not_a_permutation", None),
        "[1, 2, 3]": ("wrong_length", None),
        "[true, 1]": ("non_integer", None),
        "[1, 2": ("unparsable", None),
        "": ("empty", None),
        None: ("missing", None),
    }
    parser_rows: Dict[str, Any] = {}
    parser_pass = True
    for raw, (expected_reason, expected_value) in parser_cases.items():
        value, reason = USIMEvaluator.parse_strict(raw, 2)
        passed = reason == expected_reason and value == expected_value
        parser_pass = parser_pass and passed
        parser_rows[str(raw)] = {"reason": reason, "value": value,
                                 "expected_reason": expected_reason, "pass": passed}

    # End-to-end: an explanation-style answer must contribute 0, not a recovered list.
    prose_result = evaluator.evaluate([l3], {l3["id"]: "Explanation: [1, 2]"})
    prose_items = [item for bucket in prose_result["items"].values() for item in bucket]
    prose_summary = evaluator.summarise(prose_items)

    checks = {
        "summary_count": check(summary["count"] == 2, 2, summary["count"]),
        "transitions_total": check(summary["transitions_total"] == 5, 5, summary["transitions_total"]),
        "PA_transition_micro": check(summary["PA_transition_micro"] == 0.4, 0.4, summary["PA_transition_micro"]),
        "PA_item_mean": check(summary["PA_item_mean"] == 0.5, 0.5, summary["PA_item_mean"]),
        "EM": check(summary["EM"] == 0.5, 0.5, summary["EM"]),
        "invalid_or_missing": check(summary["invalid_or_missing"] == 1, 1, summary["invalid_or_missing"]),
        "invalid_reasons": check(summary["invalid_reasons"] == {"missing": 1}, {"missing": 1},
                                 summary["invalid_reasons"]),
        "parser_boundaries": check(parser_pass, True, parser_pass),
        "prose_answer_is_invalid": check(prose_summary["EM"] == 0.0 and prose_summary["TA"] == 0.0
                                         and prose_summary["PA_transition_micro"] == 0.0,
                                         {"EM": 0.0, "TA": 0.0, "PA_micro": 0.0},
                                         {"EM": prose_summary["EM"], "TA": prose_summary["TA"],
                                          "PA_micro": prose_summary["PA_transition_micro"]}),
    }
    return {
        "description": "fixed denominator over the frozen set + strict whole-string permutation parser",
        "mixed_summary": summary,
        "prose_answer_summary": prose_summary,
        "parser_cases": parser_rows,
        "checks": checks,
        "pass": all(block["pass"] for block in checks.values()),
    }


def test_e_duplicate_and_unknown_ids(data_root: Path) -> Dict[str, Any]:
    """evaluate.main must reject duplicate / unknown prediction IDs with exit code 2."""
    qa_path = data_root / "QA" / "train" / "enact_ordering.jsonl"
    records = load_jsonl(qa_path)
    record = records[0]
    positives: List[str] = []
    details: Dict[str, Any] = {}
    checks: Dict[str, Any] = {}

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        single_qa = tmp_path / "qa_one.jsonl"
        single_qa.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

        def run_main(name: str, prediction_rows: Sequence[Dict[str, Any]]) -> Tuple[int, str, Optional[Path]]:
            predictions_path = tmp_path / f"{name}.jsonl"
            predictions_path.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in prediction_rows) + "\n", encoding="utf-8")
            report_path = tmp_path / f"{name}.report.json"
            import io
            from contextlib import redirect_stderr, redirect_stdout

            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = evaluate_module.main(["--data-root", str(data_root), "--qa", str(single_qa),
                                             "--predictions", str(predictions_path), "--out", str(report_path),
                                             "--name", name])
            return code, stderr.getvalue().strip(), report_path

        valid_code, valid_err, valid_report = run_main("valid", [{"id": record["id"], "answer": json.dumps(record["gt_answer"])}])
        duplicate_code, duplicate_err, duplicate_report = run_main(
            "duplicate", [{"id": record["id"], "answer": json.dumps(record["gt_answer"])},
                          {"id": record["id"], "answer": "[1, 2]"}])
        unknown_code, unknown_err, unknown_report = run_main(
            "unknown", [{"id": record["id"], "answer": json.dumps(record["gt_answer"])},
                        {"id": "usim_train_episode_999999_forward_world_modeling_3_steps_deadbeef",
                         "answer": "[1, 2]"}])

        details = {
            "valid": {"exit_code": valid_code, "stderr": valid_err, "report_written": valid_report.exists()},
            "duplicate": {"exit_code": duplicate_code, "stderr": duplicate_err,
                          "report_written": duplicate_report.exists()},
            "unknown": {"exit_code": unknown_code, "stderr": unknown_err,
                        "report_written": unknown_report.exists()},
        }
        checks = {
            "valid_file_accepted": check(valid_code == 0 and valid_report.exists(), {"exit_code": 0, "report": True},
                                         {"exit_code": valid_code, "report": valid_report.exists()}),
            "duplicate_rejected": check(duplicate_code == 2, 2, duplicate_code, stderr=duplicate_err),
            "duplicate_report_not_written": check(not duplicate_report.exists(), False, duplicate_report.exists()),
            "unknown_rejected": check(unknown_code == 2, 2, unknown_code, stderr=unknown_err),
            "unknown_report_not_written": check(not unknown_report.exists(), False, unknown_report.exists()),
        }

    # Also verify the reusable loader reports duplicates before any scoring happens.
    with tempfile.TemporaryDirectory() as tmp:
        dup = Path(tmp) / "dup.jsonl"
        dup.write_text("\n".join(json.dumps({"id": record["id"], "answer": "[1, 2]"} if index == 0
                                              else {"id": record["id"], "answer": "[2, 1]"})
                                 for index in range(2)) + "\n", encoding="utf-8")
        _, duplicates = load_predictions(dup)
    checks["load_predictions_reports_duplicates"] = check(duplicates == [record["id"]], [record["id"]], duplicates)

    return {
        "description": "duplicate / unknown prediction IDs are hard errors (exit 2), a valid file is accepted",
        "probe_question": record["id"],
        "details": details,
        "checks": checks,
        "pass": all(block["pass"] for block in checks.values()),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)

    data_root = Path(args.data_root)
    evaluate_script = Path(evaluate_module.__file__)

    tests: Dict[str, Any] = {
        "a_multiple_valid_orders": test_a_multiple_valid_orders(),
        "b_non_exchangeable_swap": test_b_non_exchangeable_swap(),
        "c_empty_reference_transitions": test_c_empty_reference_transitions(),
        "d_fixed_denominator_and_strict_parsing": test_d_fixed_denominator_and_strict_parsing(),
        "e_duplicate_and_unknown_ids": test_e_duplicate_and_unknown_ids(data_root),
    }
    evidence = {
        "contract": "scoring_contract_v2",
        "contract_version": CONTRACT_VERSION,
        "under_test": {
            "scorer": "scripts/usim/evaluate.py",
            "scorer_sha256": sha256_file(evaluate_script),
            "existing_protocol": EVALUATION_PROTOCOL,
            "dataset_version": PROTOCOL_VERSION,
            "python": sys.version.split()[0],
        },
        "generated_at": now_iso(),
        "fixtures": {
            "kind": "in-memory synthetic scene graphs via a stub SceneGraphReader",
            "note": "no frozen v0.1 file is written; the frozen dataset is only read by the "
                    "duplicate/unknown-ID probe of evaluate.main",
        },
        "tests": tests,
        "all_pass": all(test["pass"] for test in tests.values()),
        "remaining_known_gap": (
            "evaluate.py (usim_strict_v0.2) does not reject empty visible reference signatures; "
            "ScoringContractV2 is the executable spec that closes that gap for usim_strict_v0.3 "
            "(wiring it into evaluate.py needs Lead approval, docs/WBW constraint)"
        ),
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for name, test in tests.items():
        print(f"[{'PASS' if test['pass'] else 'FAIL'}] {name}")
        for check_name, block in test.get("checks", {}).items():
            if not block["pass"]:
                print(f"    - {check_name}: expected={block['expected']!r} actual={block['actual']!r}")
        for case_name, case in test.get("cases", {}).items():
            for check_name, block in case.get("checks", {}).items():
                if not block["pass"]:
                    print(f"    - {name}/{case_name}/{check_name}: expected={block['expected']!r} "
                          f"actual={block['actual']!r}")
    print(json.dumps({"all_pass": evidence["all_pass"], "evidence": str(out_path)}, ensure_ascii=False))
    return 0 if evidence["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
