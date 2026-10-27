"""Strict USIM-ENACT scoring (protocol ``usim_strict_v0.3``).

Differences from the v0.1 scorer (all five are P0 fixes from docs/WBW §3):

1. **Fixed denominator.**  Every frozen question contributes ``n_i = L_i - 1``
   transitions to ``PA_transition_micro``; invalid / missing / failed answers add 0
   to the numerator.  A mixed case (L=3 perfect + L=4 missing) now scores 0.4.
2. **No silent skipping.**  Missing scene graphs or images abort the run with a
   non-zero exit code *before* any score is produced.
3. **Strict parsing.**  The whole ``answer`` string must be a single JSON array of
   integers forming a permutation of ``1..L-1``.  Explanations, multiple arrays,
   index shifting, truncation and booleans are rejected.
4. **Prediction integrity.**  Duplicate or unknown IDs are errors, not warnings.
5. **Reference-transition gate (v0.3).**  ``precheck`` verifies that every
   reference transition between adjacent ``key_frame_ids`` has a *non-empty
   visible* signature.  An empty signature is a subset of every candidate
   signature, so the verifier would silently accept *any* permutation for such a
   question (fake semantic TA=1).  v0.3 turns that into a hard ``AssetError``:
   the CLI exits non-zero and no report is written.

Only item 5 is new in v0.3; the EM/TA/PA formulas are identical to v0.2.
Re-scoring the frozen v0.1 predictions under v0.3 reproduces the v0.2 report
values exactly (evidence: ``data/usim_enact/_protocol/contract/regression_v0.1/``).

``PA_item_mean`` (mean over questions) and ``PA_transition_micro``
(transition-weighted) are kept apart; both use the full frozen set.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enact.adapters.usim_annotations import PROTOCOL_VERSION, SENSOR_NAME  # noqa: E402
from enact.adapters.usim_scene_graph import USIMSceneGraphReader  # noqa: E402
from enact.adapters.usim_translator import USIMStateChangeTranslator  # noqa: E402
from enact.core.evaluators import TaskWiseOrderingVerifier  # noqa: E402
from enact.utils.qa_gen_utils import TaskData  # noqa: E402

DEFAULT_DATA_ROOT = ROOT / "data" / "usim_enact" / PROTOCOL_VERSION
EVALUATION_PROTOCOL = "usim_strict_v0.3"


class USIMVerifier(TaskWiseOrderingVerifier):
    """Upstream verifier with the USIM state vocabulary."""

    def __init__(self, task_data: TaskData) -> None:
        super().__init__(task_data)
        self.translator = USIMStateChangeTranslator(type="multi_forward_world_modeling")


class AssetError(RuntimeError):
    """Raised when a frozen question cannot be scored because an asset is missing."""


class USIMEvaluator:
    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root)
        self._tasks: Dict[str, TaskData] = {}
        self._verifiers: Dict[str, USIMVerifier] = {}

    # ------------------------------------------------------------------ data
    def task_data(self, task_name: str) -> TaskData:
        if task_name in self._tasks:
            return self._tasks[task_name]
        segmented_file = self.data_root / "segmented_activities" / task_name / "segmented_scene_graph_0.json"
        raw_dir = self.data_root / "replayed_activities" / task_name
        raw_file = raw_dir / "scene_graph_0.json"
        if not segmented_file.exists():
            raise AssetError(f"missing segmented scene graph: {segmented_file}")
        if not raw_file.exists():
            raise AssetError(f"missing raw scene graph: {raw_file}")

        segmented_reader = USIMSceneGraphReader(str(segmented_file))
        key_frame_ids = segmented_reader.get_available_frame_ids()
        raw_reader = USIMSceneGraphReader(str(raw_file))
        image_paths: Dict[str, Dict[str, str]] = {}
        for frame_id in key_frame_ids:
            image_file = raw_dir / SENSOR_NAME / f"{int(frame_id):05d}.png"
            if not image_file.exists():
                raise AssetError(f"missing frame image: {image_file}")
            image_paths[frame_id] = {SENSOR_NAME: str(image_file)}

        task = TaskData(
            task_name=task_name,
            scene_graph_reader=raw_reader,
            key_frame_ids=key_frame_ids,
            image_paths=image_paths,
            task_dir=str(self.data_root / "segmented_activities" / task_name),
            image_root_path=self.data_root / "replayed_activities",
        )
        self._tasks[task_name] = task
        return task

    def verifier(self, task_name: str) -> USIMVerifier:
        if task_name not in self._verifiers:
            self._verifiers[task_name] = USIMVerifier(self.task_data(task_name))
        return self._verifiers[task_name]

    # -------------------------------------------------------------- parsing
    @staticmethod
    def parse_strict(answer: Any, expected_length: int) -> Tuple[Optional[List[int]], str]:
        """Whole-string strict parser.  Returns ``(permutation, reason)``."""
        if answer is None:
            return None, "missing"
        if isinstance(answer, list):
            value = answer
        elif isinstance(answer, str):
            text = answer.strip()
            if not text:
                return None, "empty"
            if not text.startswith("["):
                return None, "extra_text"
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                # covers trailing prose after a valid array and truncated arrays
                return None, "unparsable"
            if not isinstance(value, list):
                return None, "not_a_list"
        else:
            return None, "bad_type"

        if len(value) != expected_length:
            return None, "wrong_length"
        if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
            return None, "non_integer"
        if sorted(value) != list(range(1, expected_length + 1)):
            return None, "not_a_permutation"
        return list(value), "ok"

    # ----------------------------------------------------------- evaluation
    def reference_transitions(self, record: Dict) -> List[Set[str]]:
        """Visible (partial-diff) signatures of the correct timeline transitions.

        Used by the v0.3 precheck gate; the scoring formulas are unchanged.
        """
        verifier = self.verifier(record["task_name"])
        return verifier._translate_sequence_to_signatures(list(record["key_frame_ids"]), partial_diff=True)

    def precheck(self, records: Sequence[Dict]) -> None:
        """Fail before scoring if any asset is lost or a reference transition is empty.

        v0.3 adds the second condition: an empty visible reference signature is a
        subset of every candidate signature, so the verifier would accept *any*
        answer for that question.  Such a question is invalid data, not a
        scoreable item, so the whole run aborts before a report is produced.
        """
        problems: List[str] = []
        for record in records:
            task_name = record["task_name"]
            try:
                task = self.task_data(task_name)
            except AssetError as error:
                problems.append(str(error))
                continue
            for frame_id in record["key_frame_ids"]:
                if frame_id not in task.image_paths:
                    problems.append(f"{record['id']}: no image for frame {frame_id}")

            # ---- v0.3 gate: every reference transition must have a visible signature
            try:
                signatures = self.reference_transitions(record)
            except Exception as error:  # treat uncomputable diffs as data errors, never skip
                problems.append(f"{record['id']}: reference transition diff failed "
                                f"({type(error).__name__}: {error})")
                continue
            expected_transitions = len(record["gt_answer"])
            if len(signatures) != expected_transitions:
                problems.append(
                    f"{record['id']}: {len(signatures)} reference transitions but the answer "
                    f"has {expected_transitions} entries")
            empty = [index for index, signature in enumerate(signatures) if not signature]
            if empty:
                problems.append(
                    f"{record['id']}: empty visible reference signature at transitions {empty} "
                    f"(any answer would pass semantic TA); refusing to score")
        if problems:
            unique = sorted(set(problems))
            raise AssetError("资产预检查失败，拒绝评分：\n  - " + "\n  - ".join(unique[:30]))

    def evaluate(self, records: Sequence[Dict], predictions: Dict[str, Any]) -> Dict[str, Any]:
        buckets: Dict[tuple, List[Dict]] = defaultdict(list)
        for record in records:
            verifier = self.verifier(record["task_name"])
            gt = list(record["gt_answer"])
            expected = len(gt)
            raw_answer = predictions.get(record["id"])
            parsed, reason = self.parse_strict(raw_answer, expected)

            entry = {
                "id": record["id"],
                "task_name": record["task_name"],
                "type": record["type"],
                "num_states": len(record["key_frame_ids"]),
                "num_transitions": expected,
                "gt": gt,
                "parsed": parsed,
                "reason": reason,
                "raw": raw_answer,
                "exact_match": 0.0,
                "semantic_match": 0.0,
                "task_accuracy": 0.0,
                "pairwise_accuracy": 0.0,
            }
            if parsed is not None:
                if "inverse" in record["type"]:
                    result, _ = verifier.verify_inverse(record["key_frame_ids"], gt, parsed)
                else:
                    result, _ = verifier.verify_forward(record["key_frame_ids"], gt, parsed)
                entry["exact_match"] = float(bool(result["exact_match"]))
                entry["semantic_match"] = float(bool(result["semantic_match"]))
                entry["task_accuracy"] = float(bool(result["task_accuracy"]))
                entry["pairwise_accuracy"] = float(result["pairwise_accuracy"])

            direction = "inverse" if "inverse" in record["type"] else "forward"
            buckets[(direction, entry["num_states"])].append(entry)
        return {"items": buckets}

    @staticmethod
    def summarise(items: Sequence[Dict]) -> Dict[str, Any]:
        """All metrics use the full frozen set: no skipping, fixed denominator."""
        count = len(items)
        if count == 0:
            return {"count": 0}
        em = sum(item["exact_match"] for item in items) / count
        semantic = sum(item["semantic_match"] for item in items) / count
        ta = sum(item["task_accuracy"] for item in items) / count
        pa_item = sum(item["pairwise_accuracy"] for item in items) / count

        transitions = sum(item["num_transitions"] for item in items)
        correct = sum(item["pairwise_accuracy"] * item["num_transitions"] for item in items)

        reasons: Dict[str, int] = defaultdict(int)
        for item in items:
            if item["parsed"] is None:
                reasons[item["reason"]] += 1

        return {
            "count": count,
            "valid_permutations": count - sum(reasons.values()),
            "invalid_or_missing": sum(reasons.values()),
            "invalid_reasons": dict(sorted(reasons.items())),
            "EM": round(em, 4),
            "semantic_only": round(semantic - em, 4),
            "TA": round(ta, 4),
            "PA_item_mean": round(pa_item, 4),
            "PA_transition_micro": round(correct / transitions, 4) if transitions else 0.0,
            "transitions_total": transitions,
        }


# ------------------------------------------------------------------------- io
def load_jsonl(path: Path) -> List[Dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_predictions(path: Path) -> Tuple[Dict[str, Any], List[str]]:
    answers: Dict[str, Any] = {}
    duplicates: List[str] = []
    for row in load_jsonl(path):
        qid = row.get("id")
        if qid is None:
            continue
        if qid in answers:
            duplicates.append(qid)
        status = row.get("status")
        if status in ("failed", "invalid") or (status and not row.get("answer")):
            answers[qid] = None  # keeps the denominator, scores 0
        else:
            answers[qid] = row.get("answer")
    return answers, duplicates


def synthetic_predictions(records: Sequence[Dict], mode: str, seed: int = 0) -> Dict[str, Any]:
    generator = random.Random(seed)
    output: Dict[str, Any] = {}
    for record in records:
        length = len(record["gt_answer"])
        identity = list(range(1, length + 1))
        if mode == "oracle":
            output[record["id"]] = list(record["gt_answer"])
        elif mode == "identity":
            output[record["id"]] = identity
        elif mode == "reverse":
            output[record["id"]] = list(reversed(identity))
        elif mode == "random":
            value = identity[:]
            generator.shuffle(value)
            output[record["id"]] = value
        elif mode == "empty":
            output[record["id"]] = ""
        elif mode == "malformed":
            output[record["id"]] = "[1, " + str(length)
        else:
            raise ValueError(f"unknown synthetic mode: {mode}")
    return output


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--qa", default="")
    parser.add_argument("--predictions", default="")
    parser.add_argument("--synthetic", default="", choices=["", "oracle", "identity", "reverse", "random", "empty", "malformed"])
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", default="")
    parser.add_argument("--name", default="")
    args = parser.parse_args(argv)

    data_root = Path(args.data_root)
    qa_path = Path(args.qa) if args.qa else data_root / "QA" / "train" / "enact_ordering.jsonl"
    records = load_jsonl(qa_path)
    if not records:
        print(f"no QA records in {qa_path}", file=sys.stderr)
        return 2
    ids = [record["id"] for record in records]
    if len(set(ids)) != len(ids):
        print("QA 文件存在重复 ID，拒绝评分。", file=sys.stderr)
        return 2

    if args.synthetic:
        predictions = synthetic_predictions(records, args.synthetic, args.seed)
        name = args.name or f"baseline_{args.synthetic}"
    else:
        if not args.predictions:
            print("need --predictions or --synthetic", file=sys.stderr)
            return 2
        predictions, duplicates = load_predictions(Path(args.predictions))
        if duplicates:
            print(f"预测文件存在重复 ID（{len(duplicates)} 个，例如 {duplicates[:3]}），拒绝评分。", file=sys.stderr)
            return 2
        unknown = sorted(set(predictions) - set(ids))
        if unknown:
            print(f"预测文件含 {len(unknown)} 个不属于该题集的 ID（例如 {unknown[:3]}），拒绝评分。", file=sys.stderr)
            return 2
        name = args.name or Path(args.predictions).parent.name or Path(args.predictions).stem

    evaluator = USIMEvaluator(data_root)
    try:
        evaluator.precheck(records)
    except AssetError as error:
        print(str(error), file=sys.stderr)
        return 2

    result = evaluator.evaluate(records, predictions)

    manifest_path = data_root / "manifest.json"
    dataset_version = PROTOCOL_VERSION
    if manifest_path.exists():
        try:
            dataset_version = json.loads(manifest_path.read_text(encoding="utf-8")).get("protocol_version", dataset_version)
        except json.JSONDecodeError:
            pass

    report: Dict[str, Any] = {
        "dataset_version": dataset_version,
        "evaluation_protocol": EVALUATION_PROTOCOL,
        "qa_file": str(qa_path),
        "name": name,
        "total_questions": len(records),
        "answered": sum(1 for value in predictions.values() if value is not None),
        "reference_transition_gate": {
            "enforced": True,
            "checked_questions": len(records),
            # precheck aborted already if any of these were non-empty, so a report
            # only ever exists when the gate passed.
            "empty_reference_transitions": 0,
        },
        "by_setting": {},
    }
    for key in sorted(result["items"], key=lambda item: (item[0], item[1])):
        direction, num_states = key
        report["by_setting"][f"{direction}_L{num_states}"] = evaluator.summarise(result["items"][key])

    all_items = [item for items in result["items"].values() for item in items]
    report["overall"] = evaluator.summarise(all_items)

    identity_hits = sum(
        1 for record in records
        if list(record["gt_answer"]) == list(range(1, len(record["gt_answer"]) + 1))
    )
    report["identity_reference_rate"] = round(identity_hits / len(records), 4)
    report["answer_lengths"] = {
        str(length): sum(1 for record in records if len(record["gt_answer"]) == length)
        for length in sorted({len(record["gt_answer"]) for record in records})
    }

    out_path = Path(args.out) if args.out else data_root / "evaluation" / name / "report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # items are named after the report so that several evaluations can share a run directory
    items_path = out_path.with_name(out_path.stem + ".items.jsonl")
    with items_path.open("w", encoding="utf-8") as handle:
        for direction, num_states in sorted(result["items"]):
            for item in result["items"][(direction, num_states)]:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(json.dumps(report["overall"], ensure_ascii=False))
    for setting, summary in report["by_setting"].items():
        print(f"  {setting}: {summary}")
    print(f"report: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
