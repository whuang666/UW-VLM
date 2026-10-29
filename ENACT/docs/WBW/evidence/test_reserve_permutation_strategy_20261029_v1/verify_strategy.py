"""Verify a presentation-order proposal; never rewrite existing QA or images."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import redirect_stdout
from fractions import Fraction
import hashlib
import io
import itertools
import json
import math
from pathlib import Path
import socket
import sys

WORKSPACE = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(WORKSPACE / "ENACT"))
from enact.adapters.usim_scene_graph import USIMSceneGraphReader  # noqa: E402
from enact.utils.qa_gen_utils import TaskData  # noqa: E402
from scripts.usim.evaluate import USIMEvaluator, USIMVerifier  # noqa: E402

VERSION = "test-reserve-balanced-labels-draft-v1"
SEED = 20261029
INPUT = WORKSPACE / "ENACT/docs/WBW/evidence/test_reserve_conservative_semantic_20261029_v1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rank_key(value: object) -> str:
    data = json.dumps([VERSION, SEED, value], ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def proposed_schedule(records: list[dict]) -> list[dict]:
    result = []
    for length in sorted({len(r["gt_answer"]) for r in records}):
        permutations = sorted(itertools.permutations(range(1, length + 1)),
                              key=lambda p: rank_key(["permutation", length, p]))
        offset = 0
        for direction in ("forward", "inverse"):
            selected = [r for r in records if len(r["gt_answer"]) == length and direction in r["type"]]
            selected.sort(key=lambda r: rank_key(["episode", length, direction, r["task_name"], r["key_frame_ids"]]))
            for rank, record in enumerate(selected):
                answer = list(permutations[(offset + rank) % len(permutations)])
                chronological_items_at_slots = [answer.index(slot) + 1 for slot in range(1, length + 1)]
                assert [chronological_items_at_slots.index(i) + 1 for i in range(1, length + 1)] == answer
                result.append({"parent_diagnostic_id": record["id"], "episode_key": record["task_name"],
                               "direction": direction, "L": length + 1, "chronological_frame_ids": record["key_frame_ids"],
                               "proposed_gt": answer, "chronological_item_indices_at_numbered_slots": chronological_items_at_slots,
                               "draft_binding_sha256": rank_key(["binding", record["task_name"], direction,
                                                                  record["key_frame_ids"], answer]),
                               "draft_only": True})
            offset += len(selected)
    return result


def summarize_cells(schedule: list[dict], include_direction: bool) -> tuple[dict, Fraction]:
    cells = defaultdict(list)
    for row in schedule:
        key = (row["direction"] + "_" if include_direction else "") + f"L{row['L']}"
        cells[key].append(row)
    result, max_hits = {}, 0
    for key, rows in sorted(cells.items()):
        space = math.factorial(rows[0]["L"] - 1)
        hist = Counter(tuple(row["proposed_gt"]) for row in rows)
        counts = [hist[p] for p in itertools.permutations(range(1, rows[0]["L"]))]
        assert max(counts) - min(counts) <= 1
        bound = Fraction(math.ceil(len(rows) / space), len(rows))
        score = Fraction(max(counts), len(rows))
        assert score == bound
        max_hits += max(counts)
        result[key] = {"N": len(rows), "permutation_space": space,
                       "answer_histogram": {json.dumps(p): count for p, count in sorted(hist.items())},
                       "distinct_answers": len(hist), "counts_including_unobserved": counts,
                       "best_observed_constant_EM": str(score), "finite_sample_minimum_possible_best_constant_EM": str(bound),
                       "uniform_random_EM": str(Fraction(1, space))}
    return result, Fraction(max_hits, len(schedule))


def make_counterexample() -> dict:
    # Signed changes are all distinct, yet the forward subset comparison accepts
    # an alternative ordering with extra changes. No occlusion is needed.
    values = [0, 1, 2, 6, 5]
    names = ["Open", "Heated", "ToggledOn"]
    graph = {str(i): {"type": "full", "nodes": [{"name": "synthetic_object", "category": "object",
              "states": [p for bit, p in enumerate(names) if value & (1 << bit)],
              "visibility": {"external_sensor1": {"method": "synthetic", "value": True}}}], "edges": []}
             for i, value in enumerate(values)}
    task = TaskData(task_name="synthetic_distinct_transition_counterexample",
                    scene_graph_reader=USIMSceneGraphReader.from_graph(graph), key_frame_ids=list(graph),
                    image_paths={}, task_dir="", image_root_path=Path("."))
    with redirect_stdout(io.StringIO()):
        verifier = USIMVerifier(task)
    reference = verifier._translate_sequence_to_signatures(list(graph), partial_diff=True)
    assert len({frozenset(s) for s in reference}) == 4 and all(reference)
    accepted = [list(p) for p in itertools.permutations(range(1, 5))
                if verifier.verify_forward(list(graph), [1, 2, 3, 4], list(p))[0]["task_accuracy"]]
    result, _ = verifier.verify_forward(list(graph), [1, 2, 3, 4], [4, 2, 3, 1])
    assert result["semantic_match"] and not result["exact_match"] and len(accepted) == 2
    return {"schema": "usim-distinct-transition-counterexample/v1", "synthetic_only": True, "L": 5,
            "all_objects_visible": True, "states": [graph[str(i)]["nodes"][0]["states"] for i in range(5)],
            "reference_signatures": [sorted(s) for s in reference], "pairwise_distinct": True,
            "reference_answer": [1, 2, 3, 4], "alternative_accepted_answer": [4, 2, 3, 1],
            "alternative_result": result, "accepted_answers": accepted,
            "alternative_full_signatures": [sorted(s) for s in verifier._translate_sequence_to_signatures(
                ["0", "4", "2", "3", "1"], partial_diff=False)],
            "implication": "Distinct adjacent signatures alone do not establish uniqueness under stock subset semantics"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    out = args.out.resolve()
    allowed = WORKSPACE / "ENACT/docs/WBW/evidence"
    if not out.is_relative_to(allowed) or out == allowed:
        raise ValueError("Write new design evidence only under ENACT/docs/WBW/evidence")
    targets = [out / n for n in ("strategy_preview.json", "uniqueness_counterexample.json", "verification.json")]
    if any(p.exists() for p in targets):
        raise FileExistsError("Refusing to replace design evidence; use a fresh output directory")
    records = [json.loads(line) for line in (INPUT / "diagnostic_full_chain_qa.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    metadata = json.loads((INPUT / "summary.json").read_text(encoding="utf-8"))
    audited = json.loads((INPUT / "permutation_audit.json").read_text(encoding="utf-8"))
    assert len(records) == 20 and len({r["task_name"] for r in records}) == 10
    schedule = proposed_schedule(records)
    assert schedule == proposed_schedule(list(reversed(records)))
    by_cell, cell_constant = summarize_cells(schedule, True)
    by_length, length_constant = summarize_cells(schedule, False)
    random_em = sum((Fraction(1, math.factorial(r["L"] - 1)) for r in schedule), Fraction()) / len(schedule)
    assert random_em == Fraction(13, 30) and length_constant == Fraction(9, 20) and cell_constant == Fraction(1, 2)
    assert by_cell["forward_L3"]["distinct_answers"] == by_cell["inverse_L3"]["distinct_answers"] == 2
    assert by_length["L4"]["distinct_answers"] == 4
    attempts = []

    def deny(*a, **kw):
        attempts.append("socket connection")
        raise RuntimeError("Network disabled during design verification")

    old_connect, old_connect_ex = socket.socket.connect, socket.socket.connect_ex
    socket.socket.connect, socket.socket.connect_ex = deny, deny
    checked, distinct = 0, 0
    try:
        evaluator = USIMEvaluator(WORKSPACE / metadata["dataset_path"])
        with redirect_stdout(io.StringIO()):
            evaluator.precheck(records)
            baseline = evaluator.evaluate(records, {r["id"]: [2, 1] if len(r["gt_answer"]) == 2 else [1, 2, 3] for r in records})
            constant_report = evaluator.summarise([item for cell in baseline["items"].values() for item in cell])
            assert constant_report["EM"] == constant_report["TA"] == 1
            for record in records:
                verifier = evaluator.verifier(record["task_name"])
                signatures = verifier._translate_sequence_to_signatures(record["key_frame_ids"], partial_diff=True)
                distinct += len({frozenset(s) for s in signatures}) == len(signatures)
                permutations = list(itertools.permutations(range(1, len(record["gt_answer"]) + 1)))
                method = verifier.verify_forward if "forward" in record["type"] else verifier.verify_inverse
                for gt in permutations:
                    accepted = []
                    for answer in permutations:
                        checked += 1
                        if method(record["key_frame_ids"], list(gt), list(answer))[0]["task_accuracy"]:
                            accepted.append(answer)
                    assert accepted == [gt], (record["id"], gt, accepted)
        counterexample = make_counterexample()
    finally:
        socket.socket.connect, socket.socket.connect_ex = old_connect, old_connect_ex
    assert checked == 208 and distinct == 20 and not attempts
    preview = {"schema": "usim-balanced-label-plan/v1", "version": VERSION, "seed": SEED,
               "status": "draft plan, no QA or image rewrite", "question_count": 20, "episode_count": 10,
               "selection_space": "all (L-1)! permutations including identity",
               "algorithm": "SHA256 rank of permutation space; independently hash-rank episodes per direction/length; circular slots continue between directions",
               "by_direction_length": by_cell, "by_length": by_length,
               "uniform_random_EM": str(random_em), "best_length_constant_EM": str(length_constant),
               "best_direction_length_constant_EM": str(cell_constant), "schedule": schedule,
               "formal_QA_built": False, "image_writes": 0, "original_annotation_writes": 0,
               "independent_acceptance": "0/10"}
    receipt = {"schema": "usim-permutation-design-verification/v1", "version": VERSION,
               "diagnostic_constant_baseline": constant_report, "actual_chain_signature_sets_distinct": distinct,
               "relabeling_verifier_calls": checked, "all_relabelings_have_single_accepted_reference": True,
               "distinct_signatures_general_counterexample_found": True, "schedule_independent_of_input_row_order": True,
               "finite_sample_balance_checks_pass": True, "forward_slot_inverse_checks_pass": True,
               "input_sha256": {str(p.relative_to(WORKSPACE)).replace('\\', '/'): sha(p) for p in
                   [INPUT / "diagnostic_full_chain_qa.jsonl", INPUT / "permutation_audit.json", INPUT / "summary.json",
                    WORKSPACE / "ENACT/enact/core/evaluators.py", Path(__file__)]},
               "model_api_calls": 0, "socket_attempts": len(attempts), "formal_QA_writes": 0}
    out.mkdir(parents=True, exist_ok=True)
    for path, value in zip(targets, [preview, counterexample, receipt]):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"version": VERSION, "diagnostic_constant_EM": constant_report["EM"],
                      "planned_length_constant_EM": str(length_constant), "planned_direction_length_constant_EM": str(cell_constant),
                      "random_EM": str(random_em), "relabeling_verifier_calls": checked,
                      "uniqueness_counterexample_confirmed": True, "formal_QA_writes": 0}))


if __name__ == "__main__":
    main()
