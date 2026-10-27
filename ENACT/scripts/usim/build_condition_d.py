"""Build condition D: forward questions with **all action text removed**.

Condition D is the pure-visual ordering control for forward world modeling.  For
every forward question it keeps the current/future-state images, the image labels
and the reference answer permutation, but removes the ``## Actions in Order``
block and rewrites the task requirement to a neutral "order the future state
images chronologically" instruction.  Inverse questions are excluded by
definition: their whole task is to order the shuffled *action* labels, so a
no-action-text variant does not exist.

The transformation is deterministic and only touches the ``question`` field:

* preamble: the clause "that result from applying a given series of actions"
  becomes "that follow a given initial state" (no unavailable actions implied);
* ``## Your Task``: replaced by a visual-only ordering instruction;
* ``## Output Format`` and the trailing answer request: copied verbatim;
* ``## Actions in Order`` and every ``[Action N]`` line: removed;
* ``id/type/task_name/key_frame_ids/images/gt_answer/options``: unchanged, so the
  oracle score must be exactly 1.0 and scores remain comparable with condition A.

Outputs (default ``data/usim_enact/_protocol/conditions/D_no_action_text/``):
``enact_ordering.jsonl``, ``build_manifest.json`` and ``oracle_report.json``.
The QA file is compatible with ``run_inference.py --condition-label D_no_action_text``
because image paths stay relative to the dataset root.

Usage:
    python -m scripts.usim.build_condition_d
    python -m scripts.usim.build_condition_d --data-root data/usim_enact/usim-enact-v0.2

Exit code 0 = built and oracle-verified; 2 = validation failed (nothing published).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
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
)

TZ_SHANGHAI = timezone(timedelta(hours=8))
CONDITION = "D_no_action_text"
RULE_VERSION = "remove_actions_v1"
OUTPUT_SCHEMA = "usim-condition-transform/v1"

OLD_PREAMBLE = ("You are a capable agent designed to infer multi-step forward dynamics transitions "
                "in embodied decision-making. Your goal is to predict the correct sequence of future "
                "states that result from applying a given series of actions to an initial state.")
NEW_PREAMBLE = ("You are a capable agent designed to infer multi-step forward dynamics transitions "
                "in embodied decision-making. Your goal is to predict the correct chronological sequence "
                "of future states that follow a given initial state.")

NEW_TASK_BLOCK = """## Your Task
You will be provided with a single **Current State Image** and a set of shuffled **Future State Images** (labeled 1, 2, 3, etc.). Determine their **chronological order** using only the visual evidence from the images; no action descriptions are provided.

1.  Start with the **Current State Image**.
2.  Among the **Future State Images**, identify the one whose scene most likely comes immediately after the current state.
3.  Continue from that image: identify the next future state among the remaining images, and repeat until all future state images have been ordered.

"""

TASK_HEADER = "## Your Task"
OUTPUT_HEADER = "## Output Format"
ACTIONS_HEADER = "## Actions in Order"
TRAILING_REQUEST = "Now please provide your answer in the requested format."


def now_iso() -> str:
    return datetime.now(TZ_SHANGHAI).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_payload_sha256(payload: Dict[str, Any]) -> str:
    without_hash = {key: value for key, value in payload.items() if key != "payload_sha256"}
    encoded = json.dumps(without_hash, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def direction_of(record: Dict[str, Any]) -> str:
    return "inverse" if "inverse" in record["type"] else "forward"


def setting_of(record: Dict[str, Any]) -> str:
    return f"{direction_of(record)}_L{len(record['key_frame_ids'])}"


def transform_question(question: str) -> Tuple[str, Dict[str, Any]]:
    """Rewrite a forward question into the no-action-text version (deterministic)."""
    positions = {marker: question.find(marker) for marker in
                 (TASK_HEADER, OUTPUT_HEADER, ACTIONS_HEADER, TRAILING_REQUEST)}
    missing = [marker for marker, index in positions.items() if index < 0]
    if missing:
        raise ValueError(f"question is missing required sections: {missing}")
    if not (positions[TASK_HEADER] < positions[OUTPUT_HEADER] < positions[ACTIONS_HEADER] < positions[TRAILING_REQUEST]):
        raise ValueError("question section order is not the expected task/output/actions/trailing order")
    head = question[:positions[TASK_HEADER]]
    if head.strip() != OLD_PREAMBLE:
        raise ValueError("unexpected forward question preamble; refusing to transform")
    output_block = question[positions[OUTPUT_HEADER]:positions[ACTIONS_HEADER]]
    if ACTIONS_HEADER not in output_block and not output_block.rstrip().endswith("`[1, 3, 2]`"):
        raise ValueError("unexpected output-format block; refusing to transform")
    # The actions block runs until the trailing answer request.
    actions_block = question[positions[ACTIONS_HEADER]:positions[TRAILING_REQUEST]]
    if "[Action" not in actions_block:
        raise ValueError("actions block contains no [Action N] lines; refusing to transform")
    tail = question[positions[TRAILING_REQUEST]:]
    if tail.strip() != TRAILING_REQUEST:
        raise ValueError("unexpected trailing request; refusing to transform")

    new_question = NEW_PREAMBLE + "\n\n" + NEW_TASK_BLOCK + output_block + tail
    stats = {
        "source_chars": len(question),
        "new_chars": len(new_question),
        "removed_actions_block_chars": len(actions_block),
        "output_format_block_sha256": sha256_text(output_block),
        "removed_actions_block_lines": [line for line in actions_block.splitlines() if line.strip()],
        "preamble_rewritten": True,
        "task_block_replaced": True,
    }
    return new_question, stats


def verify_question(record: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
    question = record["question"]
    return {
        "no_action_tag": "[Action" not in question,
        "no_actions_header": ACTIONS_HEADER not in question,
        "has_output_format": question.count(OUTPUT_HEADER) == 1,
        "has_chronological_instruction": "chronological order" in question,
        "has_visual_only_statement": "no action descriptions are provided" in question,
        "has_trailing_request": question.rstrip().endswith(TRAILING_REQUEST),
        "starts_with_new_preamble": question.startswith(NEW_PREAMBLE),
        "output_format_block_verbatim": question.split(OUTPUT_HEADER, 1)[1].split(TRAILING_REQUEST, 1)[0]
        == source["question"].split(OUTPUT_HEADER, 1)[1].split(ACTIONS_HEADER, 1)[0],
        "question_changed": question != source["question"],
    }


def non_question_fields_equal(record: Dict[str, Any], source: Dict[str, Any]) -> bool:
    keys = sorted((set(record) | set(source)) - {"question"})
    return all(record.get(key) == source.get(key) for key in keys)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--qa", default="", help="source QA JSONL; defaults to <data-root>/QA/train/enact_ordering.jsonl")
    parser.add_argument("--out-dir", default=str(ROOT / "data" / "usim_enact" / "_protocol" / "conditions" / CONDITION))
    parser.add_argument("--name", default=CONDITION)
    args = parser.parse_args(argv)

    data_root = Path(args.data_root)
    qa_path = Path(args.qa) if args.qa else data_root / "QA" / "train" / "enact_ordering.jsonl"
    out_dir = Path(args.out_dir)
    if not qa_path.exists():
        print(f"source QA not found: {qa_path}", file=sys.stderr)
        return 2
    source_records = load_jsonl(qa_path)
    if not source_records:
        print(f"source QA is empty: {qa_path}", file=sys.stderr)
        return 2
    forward_records = [record for record in source_records if direction_of(record) == "forward"]
    excluded = [record for record in source_records if direction_of(record) != "forward"]
    if not forward_records:
        print("source QA contains no forward questions", file=sys.stderr)
        return 2

    dataset_version = PROTOCOL_VERSION
    manifest_path = data_root / "manifest.json"
    if manifest_path.exists():
        try:
            dataset_version = json.loads(manifest_path.read_text(encoding="utf-8")).get(
                "protocol_version", dataset_version)
        except json.JSONDecodeError:
            pass

    transformed: List[Dict[str, Any]] = []
    transform_stats: List[Dict[str, Any]] = []
    integrity_rows: List[Dict[str, Any]] = []
    source_by_id = {record["id"]: record for record in source_records}
    image_refs: List[str] = []
    for source in forward_records:
        record = dict(source)
        new_question, stats = transform_question(source["question"])
        record["question"] = new_question
        transformed.append(record)
        checks = verify_question(record, source)
        checks["non_question_fields_unchanged"] = non_question_fields_equal(record, source)
        checks["id_present_in_source"] = record["id"] in source_by_id
        integrity_rows.append({"id": record["id"], "checks": checks,
                               "pass": all(checks.values())})
        transform_stats.append({"id": record["id"], **stats})
        image_refs.extend(str(relative) for relative in record["images"])

    ids = [record["id"] for record in transformed]
    missing_images = sorted({relative for relative in image_refs
                             if not (data_root / relative.replace("\\", "/")).exists()})
    by_setting = Counter(setting_of(record) for record in transformed)
    by_type = Counter(record["type"] for record in transformed)
    duplicate_ids = sorted({qid for qid, count in Counter(ids).items() if count > 1})
    failed_rows = [row for row in integrity_rows if not row["pass"]]
    output_example = "[1, 3, 2]"
    gt_equals_example = sorted(record["id"] for record in transformed
                               if json.dumps(record["gt_answer"]) == output_example)

    # Oracle: identical answers/images must still score exactly 1.0 through the real
    # verifier, including the new v0.3 reference-transition gate.
    evaluator = USIMEvaluator(data_root)
    gate_error = None
    oracle_block: Dict[str, Any] = {"pass": False}
    oracle_report_path = out_dir / "oracle_report.json"
    try:
        evaluator.precheck(transformed)
        predictions = {record["id"]: list(record["gt_answer"]) for record in transformed}
        result = evaluator.evaluate(transformed, predictions)
        items = [item for bucket in result["items"].values() for item in bucket]
        oracle_overall = evaluator.summarise(items)
        oracle_by_setting = {f"{direction}_L{num_states}": evaluator.summarise(bucket)
                             for (direction, num_states), bucket in sorted(result["items"].items())}
        oracle_all_correct = (oracle_overall["count"] == len(transformed)
                              and oracle_overall["EM"] == 1.0
                              and oracle_overall["TA"] == 1.0
                              and oracle_overall["PA_transition_micro"] == 1.0)
        oracle_block = {
            "protocol": EVALUATION_PROTOCOL,
            "name": f"{args.name}_oracle",
            "total_questions": len(transformed),
            "overall": oracle_overall,
            "by_setting": oracle_by_setting,
            "all_correct": oracle_all_correct,
            "pass": oracle_all_correct,
        }
    except Exception as error:  # AssetError or verifier failure -> do not publish
        gate_error = f"{type(error).__name__}: {error}"
        oracle_block = {"pass": False, "error": gate_error}

    validation_checks = {
        "source_qa_ids_unique": len({record["id"] for record in source_records}) == len(source_records),
        "ids_unique": not duplicate_ids,
        "only_forward_records": all(direction_of(record) == "forward" for record in transformed),
        "all_ids_match_source_forward": set(ids) == {record["id"] for record in forward_records},
        "non_question_fields_unchanged": all(row["checks"]["non_question_fields_unchanged"]
                                             for row in integrity_rows),
        "all_questions_transformed": all(row["checks"]["question_changed"] for row in integrity_rows),
        "no_action_text_anywhere": all(row["checks"]["no_action_tag"] and row["checks"]["no_actions_header"]
                                       for row in integrity_rows),
        "output_format_preserved": all(row["checks"]["has_output_format"] for row in integrity_rows),
        "images_exist": not missing_images,
        "oracle_all_correct": oracle_block.get("pass") is True,
    }
    all_valid = all(validation_checks.values())
    if not all_valid:
        print(json.dumps({"validation_checks": validation_checks,
                          "failed_rows": failed_rows[:10],
                          "missing_images": missing_images[:10],
                          "gate_error": gate_error}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)
    out_qa = out_dir / "enact_ordering.jsonl"
    out_qa.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in transformed),
                      encoding="utf-8")
    (out_dir / "oracle_report.json").write_text(
        json.dumps(oracle_block, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    manifest: Dict[str, Any] = {
        "schema": OUTPUT_SCHEMA,
        "condition": CONDITION,
        "condition_label": args.name,
        "definition": "forward questions with all action descriptions removed; pure visual chronological "
                      "ordering of the future-state images; answer semantics unchanged",
        "generated_at": now_iso(),
        "dataset_version": dataset_version,
        "data_root": str(data_root),
        "source_qa": {
            "path": str(qa_path),
            "sha256": sha256_file(qa_path),
            "records_total": len(source_records),
            "forward_records": len(forward_records),
            "inverse_records_excluded": len(excluded),
            "excluded_ids": [record["id"] for record in excluded],
        },
        "transform": {
            "rule_version": RULE_VERSION,
            "deterministic": True,
            "touched_fields": ["question"],
            "untouched_fields": ["id", "type", "task_name", "key_frame_ids", "images", "gt_answer", "options"],
            "removed": [ACTIONS_HEADER + " block (all [Action N] lines)"],
            "replaced": [TASK_HEADER + " block"],
            "preamble_rewrite": {
                "from": OLD_PREAMBLE,
                "to": NEW_PREAMBLE,
                "reason": "the source preamble refers to 'a given series of actions'; condition D provides none",
            },
            "task_block_template": NEW_TASK_BLOCK,
            "output_format_block": "copied verbatim from the source question",
            "trailing_request": "copied verbatim from the source question",
            "answer_semantics": "unchanged: gt_answer still orders the future-state image labels (1..L-1)",
        },
        "counts": {
            "total": len(transformed),
            "by_setting": dict(sorted(by_setting.items())),
            "by_type": dict(sorted(by_type.items())),
            "images_referenced": len(image_refs),
            "unique_images_referenced": len(set(image_refs)),
        },
        "integrity": {
            "checks": validation_checks,
            "question_level": integrity_rows,
            "missing_images": missing_images,
            "gt_equals_output_example": {
                "example": output_example,
                "count": len(gt_equals_example),
                "ids": gt_equals_example,
                "note": "the fixed output-format example is inherited verbatim from condition A; "
                        "pre-existing coincidence, unchanged by the D transform",
            },
        },
        "utility_notes": {
            "text_prior": "condition D removes the action-text ordering shortcut for forward questions; "
                          "a text-only baseline cannot order image labels and must fall back to a label prior",
            "oracle": "oracle answers are the frozen gt_answer and score 1.0 by construction; the oracle "
                      "block re-runs the real verifier (including the v0.3 reference gate) as a self-check",
        },
        "output": {
            "qa_path": str(out_qa),
            "qa_sha256": sha256_file(out_qa),
            "qa_rows": len(transformed),
            "ids_sha256": sha256_text("\n".join(sorted(ids))),
            "question_sha256": sha256_text("\n".join(record["question"] for record in transformed)),
            "oracle_report_path": str(oracle_report_path),
            "oracle_report_sha256": sha256_file(oracle_report_path),
        },
        "oracle": oracle_block,
        "usage": {
            "inference_template": (
                "python scripts/usim/run_inference.py --data-root <data-root> "
                f"--qa {out_qa} --out <run-dir>/cond{CONDITION}/predictions.jsonl "
                "--max-completion-tokens 256 --sleep 1 --condition-label " + CONDITION),
            "evaluate_template": (
                "python scripts/usim/evaluate.py --data-root <data-root> "
                f"--qa {out_qa} --predictions <run-dir>/cond{CONDITION}/predictions.jsonl "
                f"--out <run-dir>/cond{CONDITION}/report.json --name {CONDITION}"),
            "scoring_protocol": EVALUATION_PROTOCOL,
        },
        "limitations": [
            "condition D is defined for forward questions only; inverse questions inherently order action "
            "labels and have no no-action-text variant",
            "removing action text makes the task underdetermined from text alone: it is a pure visual "
            "ordering control, not a substitute for condition A",
            "the frozen gt_answer/image labels are unchanged, so D and A scores are paired by question id",
            "D has not been run against any model yet; only the oracle self-check has been executed",
            "on v0.1 the forward set has 35 questions (28 L=3, 7 L=4); L=4 evidence is small",
        ],
    }
    manifest_path = out_dir / "build_manifest.json"
    manifest["payload_sha256"] = canonical_payload_sha256(manifest)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    summary = {
        "condition": CONDITION,
        "source_qa": str(qa_path),
        "output_qa": str(out_qa),
        "output_manifest": str(manifest_path),
        "rows": len(transformed),
        "by_setting": dict(sorted(by_setting.items())),
        "excluded_inverse": len(excluded),
        "images_referenced": len(image_refs),
        "missing_images": missing_images,
        "oracle": {"overall": oracle_block.get("overall"), "by_setting": oracle_block.get("by_setting"),
                   "all_correct": oracle_block.get("all_correct")},
        "qa_sha256": manifest["output"]["qa_sha256"],
        "payload_sha256": manifest["payload_sha256"],
        "all_valid": all_valid,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
