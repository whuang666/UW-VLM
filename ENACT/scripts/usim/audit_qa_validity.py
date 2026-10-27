"""Audit QA validity: enumerate every legal permutation and use the real verifier.

For each frozen question the scorer only ever sees the answer string.  The set of
answers that receive ``TA=1`` is therefore *enumerable*: for L=3 there are 2
permutations, for L=4 there are 6.  This script enumerates the full acceptance set
with the same ``USIMVerifier`` that ``evaluate.py`` uses and reports:

* multi-answer questions (``|accepted| > 1``), the per-question acceptance size and
  whether the reference answer / the identity permutation are accepted;
* the *exact* chance level of uniform random answering (EM / TA / PA) computed by
  enumeration instead of a single random draw;
* empty reference transitions (the "empty signature always passes" failure mode,
  docs/06 §6) and whether the reference answer is accepted at all;
* a direction x L summary plus an overall summary;
* cross-checks against the v0.1 numbers already published in docs/WBW
  (random EM 0.4333, TA == EM, identity 0.4714) and against the stored
  ``evaluation/baseline_*/report.json`` files.

The script is read-only with respect to the dataset and the existing scripts; it
writes one JSON evidence file under ``data/usim_enact/_protocol/``.

Usage:
    python -m scripts.usim.audit_qa_validity
    python -m scripts.usim.audit_qa_validity --data-root data/usim_enact/usim-enact-v0.2 \
        --qa data/usim_enact/usim-enact-v0.2/QA/train/enact_ordering.jsonl

Exit codes: 0 = all hard validity checks pass; 2 = invalid QA (duplicate IDs,
reference answer rejected, empty reference transition) or failed v0.1 cross-check.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enact.adapters.usim_annotations import PROTOCOL_VERSION  # noqa: E402
from scripts.usim.evaluate import (  # noqa: E402
    DEFAULT_DATA_ROOT,
    EVALUATION_PROTOCOL,
    USIMEvaluator,
    load_jsonl,
    synthetic_predictions,
)

DEFAULT_OUT_DIR = ROOT / "data" / "usim_enact" / "_protocol"
TZ_SHANGHAI = timezone(timedelta(hours=8))

# Published v0.1 reference numbers (docs/WBW/...执行结果-20261024.md §5,
# docs/WBW/...复核与补充清单-20261024.md §2).  Only checked for v0.1.
KNOWN_V01 = {
    "questions": 70,
    "uniform_EM": 0.4333,
    "uniform_TA": 0.4333,
    "uniform_PA_item_mean": 0.5167,
    "uniform_PA_transition_micro": 0.5000,
    "identity_EM": 0.4714,
    "multi_answer_count": 0,
    "by_setting_question_count": {
        "forward_L3": 28,
        "forward_L4": 7,
        "inverse_L3": 28,
        "inverse_L4": 7,
    },
    "by_setting_uniform_EM": {
        "forward_L3": 0.5000,
        "forward_L4": 0.1667,
        "inverse_L3": 0.5000,
        "inverse_L4": 0.1667,
    },
}


def now_iso() -> str:
    return datetime.now(TZ_SHANGHAI).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def direction_of(type_name: str) -> str:
    return "inverse" if "inverse" in type_name else "forward"


def direction_length(type_name: str, num_states: int) -> str:
    return f"{direction_of(type_name)}_L{num_states}"


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def reference_transitions(verifier, key_frame_ids: Sequence[str]) -> Dict[str, Any]:
    """Visible (partial) signatures and natural language of the reference timeline.

    The scorer compares reference signatures against the candidate timelines; an
    empty signature is a *subset of everything* and would silently accept any
    answer, so it is a hard QA validity error (docs/06 §6).
    """
    signatures = verifier._translate_sequence_to_signatures(list(key_frame_ids), partial_diff=True)
    natural_language = verifier._translate_sequence_to_natural_language(list(key_frame_ids))
    return {
        "signatures": [sorted(signature) for signature in signatures],
        "natural_language": list(natural_language),
        "empty_indices": [index for index, signature in enumerate(signatures) if not signature],
    }


def audit_record(evaluator: USIMEvaluator, record: Dict[str, Any]) -> Dict[str, Any]:
    gt = list(record["gt_answer"])
    num_transitions = len(gt)
    num_states = len(record["key_frame_ids"])
    direction = direction_of(record["type"])
    verifier = evaluator.verifier(record["task_name"])
    method = verifier.verify_inverse if direction == "inverse" else verifier.verify_forward

    reference = reference_transitions(verifier, record["key_frame_ids"])
    permutations = list(itertools.permutations(range(1, num_transitions + 1)))
    accepted: List[List[int]] = []
    exact: List[List[int]] = []
    pairwise: List[float] = []
    for permutation in permutations:
        result, _ = method(list(record["key_frame_ids"]), gt, list(permutation))
        if result["exact_match"]:
            exact.append(list(permutation))
        if result["task_accuracy"]:
            accepted.append(list(permutation))
        pairwise.append(float(result["pairwise_accuracy"]))

    identity = list(range(1, num_transitions + 1))
    expected_pa_item = mean(pairwise)
    accepted_count = len(accepted)
    return {
        "id": record["id"],
        "task_name": record["task_name"],
        "type": record["type"],
        "direction": direction,
        "num_states": num_states,
        "num_transitions": num_transitions,
        "gt": gt,
        "reference_signatures": reference["signatures"],
        "reference_natural_language": reference["natural_language"],
        "empty_reference_transitions": reference["empty_indices"],
        "permutations_total": len(permutations),
        "accepted_permutations": accepted,
        "accepted_count": accepted_count,
        "exact_match_permutations": exact,
        "gt_accepted": gt in accepted,
        "identity": identity,
        "identity_accepted": identity in accepted,
        "identity_exact": identity in exact,
        "expected_EM": round(1.0 / len(permutations), 6),
        "expected_TA": round(accepted_count / len(permutations), 6),
        "expected_PA_item": round(expected_pa_item, 6),
        # E[c_i] / n_i for a uniform permutation; micro average weights by n_i.
        "expected_PA_micro_contribution": round(expected_pa_item, 6),
    }


def summarise_cell(records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    count = len(records)
    if count == 0:
        return {"count": 0}
    transitions = sum(record["num_transitions"] for record in records)
    weighted_pa = sum(record["expected_PA_micro_contribution"] * record["num_transitions"] for record in records)
    histogram = Counter(record["accepted_count"] for record in records)
    return {
        "count": count,
        "transitions_total": transitions,
        "uniform_EM": round(mean([record["expected_EM"] for record in records]), 4),
        "uniform_TA": round(mean([record["expected_TA"] for record in records]), 4),
        "uniform_PA_item_mean": round(mean([record["expected_PA_item"] for record in records]), 4),
        "uniform_PA_transition_micro": round(weighted_pa / transitions, 4) if transitions else 0.0,
        "identity_EM": round(mean([1.0 if record["identity_exact"] else 0.0 for record in records]), 4),
        "identity_accepted_rate": round(mean([1.0 if record["identity_accepted"] else 0.0 for record in records]), 4),
        "multi_answer_questions": sum(1 for record in records if record["accepted_count"] > 1),
        "accepted_count_histogram": {str(size): histogram[size] for size in sorted(histogram)},
        "gt_rejected_questions": sum(1 for record in records if not record["gt_accepted"]),
        "empty_reference_questions": sum(1 for record in records if record["empty_reference_transitions"]),
        "empty_reference_transitions": sum(len(record["empty_reference_transitions"]) for record in records),
    }


def synthetic_baseline(evaluator: USIMEvaluator, records: Sequence[Dict[str, Any]], mode: str, seed: int = 0) -> Dict[str, Any]:
    result = evaluator.evaluate(records, synthetic_predictions(records, mode, seed=seed))
    items = [item for bucket in result["items"].values() for item in bucket]
    return evaluator.summarise(items)


def load_stored_baselines(data_root: Path) -> Dict[str, Any]:
    stored: Dict[str, Any] = {}
    for mode in ("oracle", "identity", "reverse", "random", "empty", "malformed"):
        path = data_root / "evaluation" / f"baseline_{mode}" / "report.json"
        if path.exists():
            report = json.loads(path.read_text(encoding="utf-8"))
            stored[mode] = {"path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                            "overall": report.get("overall", {})}
    return stored


def close(actual: Optional[float], expected: float, tolerance: float = 5e-5) -> bool:
    return actual is not None and abs(float(actual) - float(expected)) <= tolerance


def build_cross_checks(overall: Dict[str, Any], cells: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    checks: Dict[str, Any] = {}
    checks["questions"] = {
        "expected": KNOWN_V01["questions"],
        "actual": overall["count"],
        "pass": overall["count"] == KNOWN_V01["questions"],
    }
    checks["uniform_EM"] = {
        "expected": KNOWN_V01["uniform_EM"],
        "actual": overall["uniform_EM"],
        "pass": close(overall["uniform_EM"], KNOWN_V01["uniform_EM"]),
    }
    checks["uniform_TA"] = {
        "expected": KNOWN_V01["uniform_TA"],
        "actual": overall["uniform_TA"],
        "pass": close(overall["uniform_TA"], KNOWN_V01["uniform_TA"]),
    }
    checks["TA_equals_EM_uniform"] = {
        "expected": "uniform_TA == uniform_EM",
        "actual": [overall["uniform_TA"], overall["uniform_EM"]],
        "pass": close(overall["uniform_TA"], overall["uniform_EM"]),
    }
    checks["uniform_PA_item_mean"] = {
        "expected": KNOWN_V01["uniform_PA_item_mean"],
        "actual": overall["uniform_PA_item_mean"],
        "pass": close(overall["uniform_PA_item_mean"], KNOWN_V01["uniform_PA_item_mean"]),
    }
    checks["uniform_PA_transition_micro"] = {
        "expected": KNOWN_V01["uniform_PA_transition_micro"],
        "actual": overall["uniform_PA_transition_micro"],
        "pass": close(overall["uniform_PA_transition_micro"], KNOWN_V01["uniform_PA_transition_micro"]),
    }
    checks["identity_EM"] = {
        "expected": KNOWN_V01["identity_EM"],
        "actual": overall["identity_EM"],
        "pass": close(overall["identity_EM"], KNOWN_V01["identity_EM"]),
    }
    checks["multi_answer_count"] = {
        "expected": KNOWN_V01["multi_answer_count"],
        "actual": overall["multi_answer_questions"],
        "pass": overall["multi_answer_questions"] == KNOWN_V01["multi_answer_count"],
    }
    for name, expected in KNOWN_V01["by_setting_question_count"].items():
        actual = cells.get(name, {}).get("count")
        checks[f"count_{name}"] = {"expected": expected, "actual": actual, "pass": actual == expected}
    for name, expected in KNOWN_V01["by_setting_uniform_EM"].items():
        actual = cells.get(name, {}).get("uniform_EM")
        checks[f"uniform_EM_{name}"] = {"expected": expected, "actual": actual, "pass": close(actual, expected)}
    return checks


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--qa", default="", help="QA JSONL; defaults to <data-root>/QA/train/enact_ordering.jsonl")
    parser.add_argument("--out", default="", help="evidence JSON path")
    parser.add_argument("--skip-synthetic-baselines", action="store_true",
                        help="skip the six regression baselines (faster)")
    args = parser.parse_args(argv)

    data_root = Path(args.data_root)
    qa_path = Path(args.qa) if args.qa else data_root / "QA" / "train" / "enact_ordering.jsonl"
    if not qa_path.exists():
        print(f"QA file not found: {qa_path}", file=sys.stderr)
        return 2
    records = load_jsonl(qa_path)
    if not records:
        print(f"no QA records in {qa_path}", file=sys.stderr)
        return 2

    ids = [record["id"] for record in records]
    duplicate_ids = sorted({qid for qid, count in Counter(ids).items() if count > 1})
    if duplicate_ids:
        print(f"QA 文件存在重复 ID（{len(duplicate_ids)} 个，例如 {duplicate_ids[:3]}），审计中止。", file=sys.stderr)
        return 2

    dataset_version = PROTOCOL_VERSION
    manifest_path = data_root / "manifest.json"
    if manifest_path.exists():
        try:
            dataset_version = json.loads(manifest_path.read_text(encoding="utf-8")).get("protocol_version", dataset_version)
        except json.JSONDecodeError:
            pass

    evaluator = USIMEvaluator(data_root)
    try:
        evaluator.precheck(records)
    except Exception as error:  # AssetError, but keep the evidence failure readable
        print(f"资产预检查失败，拒绝审计：{error}", file=sys.stderr)
        return 2

    audited = [audit_record(evaluator, record) for record in records]

    by_cell: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for record in audited:
        by_cell[direction_length(record["type"], record["num_states"])].append(record)
    cells = {name: summarise_cell(items) for name, items in sorted(by_cell.items())}
    overall = summarise_cell(audited)

    synthetic: Dict[str, Any] = {}
    if not args.skip_synthetic_baselines:
        for mode in ("oracle", "identity", "reverse", "random", "empty", "malformed"):
            synthetic[mode] = synthetic_baseline(evaluator, records, mode, seed=0)
    stored = load_stored_baselines(data_root)
    stored_comparison: Dict[str, Any] = {}
    for mode, block in synthetic.items():
        stored_block = stored.get(mode)
        if stored_block:
            stored_overall = stored_block["overall"]
            # Stored reports were produced by an older evaluate.py build; compare the
            # shared fields and record which fields only exist on one side.
            shared_keys = sorted(set(block) & set(stored_overall))
            matches = all(block[key] == stored_overall[key] for key in shared_keys)
            shared = {key: stored_overall[key] for key in shared_keys}
            extra = sorted(set(block) - set(stored_overall))
            missing = sorted(set(stored_overall) - set(block))
        else:
            stored_overall, shared, matches, extra, missing = None, None, False, [], []
        stored_comparison[mode] = {
            "recomputed": block,
            "stored": stored_overall,
            "shared_fields": shared,
            "matches_stored": matches,
            "fields_only_in_recomputed": extra,
            "fields_only_in_stored": missing,
        }

    hard_errors: List[str] = []
    if overall["gt_rejected_questions"]:
        hard_errors.append(f"{overall['gt_rejected_questions']} 题的参考答案未被自身 verifier 接受")
    if overall["empty_reference_transitions"]:
        hard_errors.append(f"{overall['empty_reference_transitions']} 个参考转移的可见签名是空集（会被任何答案虚假通过）")

    cross_checks: Dict[str, Any] = {}
    if dataset_version == "usim-enact-v0.1":
        cross_checks = build_cross_checks(overall, cells)
        failed = [name for name, block in cross_checks.items() if not block["pass"]]
        if failed:
            hard_errors.append(f"与已发布 v0.1 数字不一致: {failed}")

    evidence = {
        "audit": "qa_validity_permutation_enumeration",
        "audited_at": now_iso(),
        "python": sys.version.split()[0],
        "dataset_version": dataset_version,
        "data_root": str(data_root),
        "qa_file": str(qa_path),
        "qa_sha256": sha256_file(qa_path),
        "manifest_sha256": sha256_file(manifest_path) if manifest_path.exists() else None,
        "evaluation_protocol": EVALUATION_PROTOCOL,
        "verifier": "enact.core.evaluators.TaskWiseOrderingVerifier (via scripts.usim.evaluate.USIMVerifier)",
        "method": "enumerate all (L-1)! permutations per question and record the TA/EM/PA the real verifier returns",
        "counts": {
            "questions": len(records),
            "unique_ids": len(set(ids)),
            "episodes": sorted({record["task_name"] for record in records}),
            "by_type": dict(sorted(Counter(record["type"] for record in records).items())),
        },
        "overall": overall,
        "by_setting": cells,
        "questions": audited,
        "synthetic_baselines_recomputed": synthetic,
        "stored_baseline_comparison": stored_comparison,
        "cross_checks_v0_1": cross_checks,
        "hard_errors": hard_errors,
        "all_validity_checks_pass": not hard_errors,
    }

    out_path = Path(args.out) if args.out else DEFAULT_OUT_DIR / f"audit_qa_validity_{dataset_version}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    summary = {
        "dataset_version": dataset_version,
        "questions": overall["count"],
        "uniform_EM": overall["uniform_EM"],
        "uniform_TA": overall["uniform_TA"],
        "uniform_PA_item_mean": overall["uniform_PA_item_mean"],
        "uniform_PA_transition_micro": overall["uniform_PA_transition_micro"],
        "identity_EM": overall["identity_EM"],
        "multi_answer_questions": overall["multi_answer_questions"],
        "accepted_count_histogram": overall["accepted_count_histogram"],
        "empty_reference_transitions": overall["empty_reference_transitions"],
        "gt_rejected_questions": overall["gt_rejected_questions"],
        "by_setting": {name: {"count": cell["count"], "uniform_EM": cell["uniform_EM"],
                              "uniform_TA": cell["uniform_TA"], "multi": cell["multi_answer_questions"]}
                       for name, cell in cells.items()},
        "synthetic_baselines": {mode: {key: block.get(key) for key in ("EM", "TA", "PA_item_mean", "PA_transition_micro")}
                                for mode, block in synthetic.items()},
        "stored_baselines_match": all(block["matches_stored"] or block["stored"] is None
                                      for block in stored_comparison.values()),
        "cross_checks_pass": all(block["pass"] for block in cross_checks.values()) if cross_checks else None,
        "all_validity_checks_pass": evidence["all_validity_checks_pass"],
        "hard_errors": hard_errors,
        "evidence": str(out_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if evidence["all_validity_checks_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
