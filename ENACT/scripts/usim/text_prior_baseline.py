"""Deterministic, image-free text-order baseline for the USIM-ENACT ordering questions.

The inverse questions already contain ``[Action N] <description>`` lines for every
transition; the task is to order those labels.  Because the USIM state vocabulary
is a monotone object lifecycle (annotation schema / ``usim_translator.py``:

    OnSeabed -> NextTo(approach) -> [Touching] -> InGripper -> Lifted -> [NearBox] -> InBox

) the *text alone* fixes the chronological order for the inverse questions.  This
script builds a deterministic baseline from the ``question`` field only:

* **inverse**: parse each ``[Action N]`` line, score the highest positive lifecycle
  stage mentioned in a non-negated sentence, then order labels by
  ``(stage, label)`` ascending;
* **forward**: the question lists the actions in chronological order but carries
  no action -> image-label mapping, so text cannot order the future images.  The
  only text-consistent answer is the fixed label prior (identity permutation);
  this baseline makes that assumption explicit instead of pretending it solved
  the question.

**Rule version ``text_lifecycle_v2`` supports both question-template generations**
so the frozen v0.1 evidence can be re-run and v0.2 can be scored with the same
script:

* v0.1 template: ``next to`` for ``NextTo``, ``touching`` for ``Touching``;
* v0.2 template (``docs/WBR/ENACT-USIM-v0.2标注与关键帧规范-20261027.md``):
  ``in position for the pre-grasp approach beside`` for ``NextTo``,
  ``in contact with`` for ``Touching`` and ``near`` for ``NearBox`` (the
  at-box release-position state used for the transfer L=5 route).

Stage ranks are monotone: ``OnSeabed(0) < NextTo(10) < Touching(15) <
InGripper(20) < Lifted(30) < NearBox(35) < InBox(40)``.  ``Touching`` sits between
the approach and the grasp because the v0.2 guideline defines it as "contact before
holding"; ``NearBox`` sits after ``Lifted`` because it is the at-box release
position of a transferred object.  The v0.1/v0.2 lifecycle order without those
optional states is preserved.  Negated sentences (``no longer`` / ``not ...
anymore`` / ``stopped being``) never contribute a stage.

The rule never reads ``gt_answer``, ``images`` or ``key_frame_ids``; it was frozen
from the documented predicate lifecycle and templates before being compared with
any model condition.  A built-in ``template_compatibility`` probe asserts that the
rule resolves the exact documented sentence templates of both generations (and
that negated removal sentences stay unresolved); a probe failure exits non-zero.
The baseline is scored with the real ``evaluate.py`` path and compared with the
image-free model condition C to quantify how much of C's score is the text prior.
QA is never modified.

Usage:
    python -m scripts.usim.text_prior_baseline
    python -m scripts.usim.text_prior_baseline --data-root data/usim_enact/usim-enact-v0.2 \
        --qa data/usim_enact/usim-enact-v0.2/QA/train/enact_ordering_curated.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
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

DEFAULT_RUN_DIR = ROOT / "data" / "usim_enact" / "runs" / "qwen3.8-max" / "dev_ego_thinking_false_001"
DEFAULT_OUT_DIR = ROOT / "data" / "usim_enact" / "_protocol"
TZ_SHANGHAI = timezone(timedelta(hours=8))
RULE_VERSION = "text_lifecycle_v2"

# Lifecycle rank from the annotated USIM predicate vocabulary.  Higher = later.
# v0.2 fixates the approach semantics of NextTo and (optionally) a distinct
# contact phase Touching that sits between approach and grasp.
STAGE_ORDER: Dict[str, int] = {
    "OnSeabed": 0,
    "NextTo": 10,
    "Touching": 15,
    "InGripper": 20,
    "Lifted": 30,
    "NearBox": 35,
    "InBox": 40,
}

# (rank, predicate, regex, template generation).  Multiple patterns per predicate
# because the question wording differs between v0.1 and v0.2; both must resolve.
STAGE_PATTERNS: Tuple[Tuple[int, str, str, str], ...] = (
    (0, "OnSeabed", r"\bon the seabed\b", "v0.1+v0.2"),
    (10, "NextTo", r"\bnext to\b", "v0.1"),
    (10, "NextTo", r"\bin position for the (?:pre-grasp )?approach beside\b", "v0.2"),
    (15, "Touching", r"\btouching\b", "v0.1"),
    (15, "Touching", r"\bin contact with\b", "v0.2"),
    (20, "InGripper", r"\bgrasped by the robot\b", "v0.1+v0.2"),
    (30, "Lifted", r"\blifted above the seabed\b", "v0.1+v0.2"),
    (35, "NearBox", r"\bnear\b", "v0.2"),
    (40, "InBox", r"\binside the (?:green )?box\b", "v0.1+v0.2"),
)

NEGATION_PATTERNS: Tuple[str, ...] = (
    r"\bno longer\b",
    r"\bnot\b.{0,60}?\banymore\b",
    r"\bstopped being\b",
    r"\bnever\b",
    r"\bno more\b",
)

# Documented sentence templates per generation, used as a frozen self-check of the
# regex rules (see docs/WBR/ENACT-USIM-v0.2标注与关键帧规范-20261027.md §9).
TEMPLATE_PROBES: Tuple[Dict[str, Any], ...] = (
    {"generation": "v0.1", "predicate": "NextTo", "expected_rank": 10,
     "text": "The robot now becomes next to the blue cylinder."},
    {"generation": "v0.2", "predicate": "NextTo", "expected_rank": 10,
     "text": "The robot is now in position for the pre-grasp approach beside the blue cylinder."},
    {"generation": "v0.2", "predicate": "NextTo", "expected_rank": 10,
     "text": "The robot becomes in position for the pre-grasp approach beside the red cylinder."},
    {"generation": "v0.1", "predicate": "Touching", "expected_rank": 15,
     "text": "The robot is now touching the blue cylinder."},
    {"generation": "v0.2", "predicate": "Touching", "expected_rank": 15,
     "text": "The robot is now in contact with the blue cylinder."},
    {"generation": "v0.1", "predicate": "InGripper", "expected_rank": 20,
     "text": "The blue cylinder becomes grasped by the robot."},
    {"generation": "v0.2", "predicate": "InGripper", "expected_rank": 20,
     "text": "The blue cylinder is now grasped by the robot."},
    {"generation": "v0.1", "predicate": "Lifted", "expected_rank": 30,
     "text": "The blue cylinder is now lifted above the seabed."},
    {"generation": "v0.2", "predicate": "InBox", "expected_rank": 40,
     "text": "The red cylinder is now inside the green box."},
    {"generation": "v0.2", "predicate": "NearBox", "expected_rank": 35,
     "text": "The robot is now near the green box."},
    {"generation": "v0.2", "predicate": "NearBox", "expected_rank": None,
     "text": "The robot is no longer near the green box."},
    {"generation": "v0.2", "predicate": "NextTo", "expected_rank": None,
     "text": "The robot is no longer in position for the pre-grasp approach beside the blue cylinder."},
    {"generation": "v0.2", "predicate": "Touching", "expected_rank": None,
     "text": "The robot is not in contact with the blue cylinder anymore."},
    {"generation": "v0.1", "predicate": "OnSeabed", "expected_rank": None,
     "text": "The blue cylinder is not on the seabed anymore."},
)

ACTION_LINE_RE = re.compile(r"^\[Action\s+(\d+)\]\s*(.+?)\s*$", re.MULTILINE)
SECTION_HEADERS = ("## Shuffled Actions", "## Actions in Order")


def now_iso() -> str:
    return datetime.now(TZ_SHANGHAI).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_repo_path(path: Path) -> str:
    """Repository-relative POSIX path when possible (stable evidence across machines)."""
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def direction_of(record: Dict[str, Any]) -> str:
    return "inverse" if "inverse" in record["type"] else "forward"


def setting_of(record: Dict[str, Any]) -> str:
    return f"{direction_of(record)}_L{len(record['key_frame_ids'])}"


def identity_permutation(num_transitions: int) -> List[int]:
    return list(range(1, num_transitions + 1))


def split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [part for part in parts if part]


def is_negated(sentence: str) -> bool:
    lowered = sentence.lower()
    return any(re.search(pattern, lowered) for pattern in NEGATION_PATTERNS)


def parse_action_lines(question: str) -> Tuple[Dict[int, str], str]:
    """Return ``{label: description}`` from the first action section, plus the header used."""
    header_used = ""
    for header in SECTION_HEADERS:
        index = question.find(header)
        if index < 0:
            continue
        header_used = header
        block = question[index:]
        # Stop at the next "## " heading if one exists after the action list.
        next_heading = block.find("\n## ", len(header))
        if next_heading >= 0:
            block = block[:next_heading]
        actions: Dict[int, str] = {}
        for match in ACTION_LINE_RE.finditer(block):
            actions[int(match.group(1))] = match.group(2).strip()
        return actions, header_used
    return {}, ""


def action_stage(description: str) -> Tuple[Optional[int], List[str]]:
    """Highest positive lifecycle rank in a non-negated sentence.

    Supports both v0.1 and v0.2 action-text template generations (see
    ``STAGE_PATTERNS``).  Returns ``(rank, evidence_predicates)``.  ``None`` means
    the rule could not resolve the action description (a vocabulary extension
    would be needed).
    """
    best: Optional[int] = None
    evidence: List[str] = []
    for sentence in split_sentences(description):
        if is_negated(sentence):
            continue
        for rank, predicate, pattern, _generation in STAGE_PATTERNS:
            if re.search(pattern, sentence, flags=re.IGNORECASE):
                if best is None or rank > best:
                    best = rank
                evidence.append(predicate)
    return best, evidence


def template_compatibility_probe() -> Dict[str, Any]:
    """Run the frozen rule over the documented sentence templates of both generations."""
    rows: List[Dict[str, Any]] = []
    all_pass = True
    for probe in TEMPLATE_PROBES:
        rank, evidence = action_stage(probe["text"])
        expected = probe["expected_rank"]
        passed = rank == expected and (expected is None or probe["predicate"] in evidence)
        all_pass = all_pass and passed
        rows.append({
            "generation": probe["generation"],
            "predicate": probe["predicate"],
            "text": probe["text"],
            "expected_rank": expected,
            "actual_rank": rank,
            "evidence_predicates": evidence,
            "pass": passed,
        })
    generations = sorted({row["generation"] for row in rows})
    return {
        "rule_version": RULE_VERSION,
        "probes_total": len(rows),
        "generations_covered": generations,
        "rows": rows,
        "all_pass": all_pass,
    }


def synthetic_order_probes() -> Dict[str, Any]:
    """End-to-end rule probes on synthetic inverse questions (no scoring/assets needed).

    These check the full parse+order path for both template generations and for the
    v0.2-only Touching phase, without needing a v0.2 dataset or verifier.
    """
    cases = [
        {
            "name": "v0.1_generation_order",
            "expected_prediction": [2, 1, 3],
            "question": "## Shuffled Actions\n"
                        "[Action 1] The blue cylinder is now grasped by the robot. The blue cylinder is not on the seabed anymore. The robot stopped being next to the blue cylinder.\n"
                        "[Action 2] The robot now becomes next to the blue cylinder.\n"
                        "[Action 3] The blue cylinder is now lifted above the seabed.\n",
        },
        {
            "name": "v0.2_generation_order",
            "expected_prediction": [2, 1, 3],
            "question": "## Shuffled Actions\n"
                        "[Action 1] The blue cylinder is now grasped by the robot. The blue cylinder is no longer on the seabed. The robot stopped being in position for the pre-grasp approach beside the blue cylinder.\n"
                        "[Action 2] The robot now becomes in position for the pre-grasp approach beside the blue cylinder.\n"
                        "[Action 3] The blue cylinder is now lifted above the seabed.\n",
        },
        {
            "name": "v0.2_touching_phase_order",
            "expected_prediction": [2, 3, 1],
            "question": "## Shuffled Actions\n"
                        "[Action 1] The blue cylinder is now lifted above the seabed.\n"
                        "[Action 2] The robot is now in contact with the blue cylinder.\n"
                        "[Action 3] The blue cylinder is now grasped by the robot.\n",
        },
        {
            "name": "v0.2_full_l5_chain_order",
            "expected_prediction": [3, 1, 4, 2],
            "question": "## Shuffled Actions\n"
                        "[Action 1] The red cylinder is now lifted above the seabed.\n"
                        "[Action 2] The red cylinder is now inside the green box.\n"
                        "[Action 3] The robot now becomes in position for the pre-grasp approach beside the red cylinder.\n"
                        "[Action 4] The robot is now near the green box.\n",
        },
    ]
    rows: List[Dict[str, Any]] = []
    all_pass = True
    for case in cases:
        action_count = len(re.findall(r"\[Action\s+\d+\]", case["question"]))
        record = {"question": case["question"], "gt_answer": list(range(1, action_count + 1))}
        detail = predict_inverse(record)
        passed = detail["predicted"] == case["expected_prediction"] and not detail["unresolved_labels"]
        all_pass = all_pass and passed
        rows.append({
            "name": case["name"],
            "expected_prediction": case["expected_prediction"],
            "actual_prediction": detail["predicted"],
            "stages": detail["stages"],
            "stage_evidence": detail["stage_evidence"],
            "unresolved_labels": detail["unresolved_labels"],
            "pass": passed,
        })
    return {"probes_total": len(rows), "rows": rows, "all_pass": all_pass}


def question_template_generation(question: str) -> str:
    """Best-effort label of which action-text template a question uses (evidence only).

    The two generations differ only in the ``NextTo``/``Touching`` wording; questions
    whose action text contains neither marker are labelled ``undetermined_shared_template``
    (the rest of the vocabulary is identical between v0.1 and v0.2).
    """
    lowered = question.lower()
    if "pre-grasp approach beside" in lowered or "in contact with" in lowered:
        return "v0.2"
    if re.search(r"\bnext to\b", lowered) or re.search(r"\btouching\b", lowered):
        return "v0.1"
    if any(marker in lowered for marker in ("grasped by the robot", "lifted above the seabed", "on the seabed")):
        return "undetermined_shared_template"
    return "unknown"


def predict_inverse(record: Dict[str, Any]) -> Dict[str, Any]:
    actions, header = parse_action_lines(record["question"])
    num_transitions = len(record["gt_answer"])
    resolved: Dict[int, Optional[int]] = {}
    evidence: Dict[int, List[str]] = {}
    for label in range(1, num_transitions + 1):
        description = actions.get(label)
        if description is None:
            resolved[label] = None
            evidence[label] = ["missing_action_line"]
            continue
        stage, phrases = action_stage(description)
        resolved[label] = stage
        evidence[label] = phrases or ["unresolved"]
    predicted = sorted(resolved, key=lambda label: (
        99 if resolved[label] is None else resolved[label], label))
    return {
        "predicted": predicted,
        "header": header,
        "actions": {str(label): actions.get(label) for label in sorted(actions)},
        "stages": {str(label): resolved[label] for label in sorted(resolved)},
        "stage_evidence": {str(label): evidence[label] for label in sorted(evidence)},
        "unresolved_labels": [label for label in sorted(resolved) if resolved[label] is None],
        "tie_groups": [
            labels for labels in
            [[label for label in sorted(resolved) if resolved[label] == stage]
             for stage in sorted({value for value in resolved.values() if value is not None})]
            if len(labels) > 1
        ],
    }


def predict_forward(record: Dict[str, Any]) -> Dict[str, Any]:
    num_transitions = len(record["gt_answer"])
    actions, header = parse_action_lines(record["question"])
    stages = {label: action_stage(description)[0] for label, description in actions.items()}
    # The action list is chronological, but its labels are not the future-image
    # labels: text cannot map them.  The fixed label prior is the identity.
    chronological_actions = all(
        stages.get(label) is not None and stages.get(label, -1) >= stages.get(previous, 10**6)
        for previous, label in zip(range(1, len(stages)), range(2, len(stages) + 1))
    )
    return {
        "predicted": identity_permutation(num_transitions),
        "header": header,
        "actions": {str(label): actions.get(label) for label in sorted(actions)},
        "stages": {str(label): stages.get(label) for label in sorted(stages)},
        "unresolved_labels": [label for label in sorted(stages) if stages[label] is None],
        "action_list_is_chronological": chronological_actions,
        "label_mapping_available_in_text": False,
    }


def metric_block(items: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    count = len(items)
    if count == 0:
        return {"count": 0}
    transitions = sum(int(item["num_transitions"]) for item in items)
    invalid_reasons = Counter(item["reason"] for item in items if item.get("parsed") is None)
    em = sum(float(item["exact_match"]) for item in items) / count
    ta = sum(float(item["task_accuracy"]) for item in items) / count
    pa_item = sum(float(item["pairwise_accuracy"]) for item in items) / count
    pa_micro = sum(float(item["pairwise_accuracy"]) * int(item["num_transitions"])
                   for item in items) / transitions
    identity_answers = sum(1 for item in items
                           if item.get("parsed") == identity_permutation(int(item["num_transitions"])))
    return {
        "count": count,
        "transitions_total": transitions,
        "EM": round(em, 4),
        "TA": round(ta, 4),
        "PA_item_mean": round(pa_item, 4),
        "PA_transition_micro": round(pa_micro, 4),
        "invalid_or_missing": sum(invalid_reasons.values()),
        "invalid_reasons": dict(sorted(invalid_reasons.items())),
        "identity_answer_rate": round(identity_answers / count, 4),
    }


def group(items: Sequence[Dict[str, Any]], key) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(key(item), []).append(item)
    return dict(sorted(grouped.items()))


def chance_block(records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    by_setting: Dict[str, List[Dict[str, Any]]] = {}
    for record in records:
        by_setting.setdefault(setting_of(record), []).append(record)

    def cell(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        em = sum(1.0 / math.factorial(len(row["gt_answer"])) for row in rows) / len(rows)
        identity = sum(1 for row in rows
                       if list(row["gt_answer"]) == identity_permutation(len(row["gt_answer"]))) / len(rows)
        return {"count": len(rows), "uniform_EM": round(em, 4), "identity_EM": round(identity, 4)}

    overall = cell(records)
    return {
        "uniform_permutation_EM": overall["uniform_EM"],
        "identity_answer_EM": overall["identity_EM"],
        "by_setting": {name: cell(rows) for name, rows in sorted(by_setting.items())},
    }


def load_condition_items(path: Path) -> Dict[str, Dict[str, Any]]:
    items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {item["id"]: item for item in items}


def comparison_with_condition_c(baseline_items: Dict[str, Dict[str, Any]],
                                condition_items: Dict[str, Dict[str, Any]],
                                qa_by_id: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    common = sorted(set(baseline_items) & set(condition_items))
    if not common:
        return {"skipped": "no common ids between this QA set and the condition-C items "
                           "(pass --condition-c-items for the matching model run)"}
    counts = Counter()
    per_setting: Dict[str, Counter] = {}
    disagreement_ids: List[str] = []
    baseline_em_vs_c = {"baseline_correct": 0, "baseline_wrong": 0,
                        "c_correct_when_baseline_correct": 0, "c_correct_when_baseline_wrong": 0}
    for qid in common:
        baseline = baseline_items[qid]
        model = condition_items[qid]
        setting = setting_of(qa_by_id[qid])
        counts["common"] += 1
        counts["baseline_correct"] += int(float(baseline["exact_match"]) == 1.0)
        counts["c_correct"] += int(float(model["exact_match"]) == 1.0)
        counts["baseline_correct_and_c_correct"] += int(float(baseline["exact_match"]) == 1.0
                                                        and float(model["exact_match"]) == 1.0)
        counts["baseline_correct_c_wrong"] += int(float(baseline["exact_match"]) == 1.0
                                                  and float(model["exact_match"]) != 1.0)
        counts["baseline_wrong_c_correct"] += int(float(baseline["exact_match"]) != 1.0
                                                  and float(model["exact_match"]) == 1.0)
        baseline_em_vs_c["baseline_correct" if float(baseline["exact_match"]) == 1.0 else "baseline_wrong"] += 1
        baseline_em_vs_c["c_correct_when_baseline_correct" if float(baseline["exact_match"]) == 1.0
                         else "c_correct_when_baseline_wrong"] += int(float(model["exact_match"]) == 1.0)
        setting_counter = per_setting.setdefault(setting, Counter())
        setting_counter["common"] += 1
        setting_counter["baseline_correct"] += int(float(baseline["exact_match"]) == 1.0)
        setting_counter["c_correct"] += int(float(model["exact_match"]) == 1.0)
        if baseline.get("parsed") is not None and model.get("parsed") is not None \
                and baseline["parsed"] != model["parsed"]:
            disagreement_ids.append(qid)
    baseline_items_list = [baseline_items[qid] for qid in common]
    model_items_list = [condition_items[qid] for qid in common]
    baseline_block = metric_block(baseline_items_list)
    model_block = metric_block(model_items_list)
    return {
        "condition": "C_text_only",
        "common_ids": len(common),
        "paired": {
            "both_correct": counts["baseline_correct_and_c_correct"],
            "baseline_only_correct": counts["baseline_correct_c_wrong"],
            "c_only_correct": counts["baseline_wrong_c_correct"],
            "baseline_correct": counts["baseline_correct"],
            "c_correct": counts["c_correct"],
        },
        "EM_delta_baseline_minus_C": round(baseline_block["EM"] - model_block["EM"], 4),
        "PA_item_delta_baseline_minus_C": round(baseline_block["PA_item_mean"] - model_block["PA_item_mean"], 4),
        "baseline_overall": baseline_block,
        "condition_overall": model_block,
        "by_setting": {
            setting: {
                "common": counter["common"],
                "baseline_EM": round(counter["baseline_correct"] / counter["common"], 4),
                "c_EM": round(counter["c_correct"] / counter["common"], 4),
                "delta_baseline_minus_C": round((counter["baseline_correct"] - counter["c_correct"])
                                                / counter["common"], 4),
            }
            for setting, counter in sorted(per_setting.items())
        },
        "different_answer_ids": disagreement_ids,
        "different_answer_count": len(disagreement_ids),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--qa", default="", help="QA JSONL; defaults to <data-root>/QA/train/enact_ordering.jsonl")
    parser.add_argument("--condition-c-items", default="",
                        help="optional report.items.jsonl of the image-free condition C for the SAME QA set "
                             "(v0.1 default evidence: data/usim_enact/runs/qwen3.8-max/"
                             "dev_ego_thinking_false_001/condC_text_only/report.items.jsonl). "
                             "Omit when no matching model run exists.")
    parser.add_argument("--predictions-out", default="",
                        help="optional JSONL of the baseline answers compatible with "
                             "run_inference/evaluate (for report_stats baselines)")
    parser.add_argument("--out", default="")
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

    dataset_version = PROTOCOL_VERSION
    manifest_path = data_root / "manifest.json"
    if manifest_path.exists():
        try:
            dataset_version = json.loads(manifest_path.read_text(encoding="utf-8")).get(
                "protocol_version", dataset_version)
        except json.JSONDecodeError:
            pass

    predictions: Dict[str, List[int]] = {}
    details: Dict[str, Dict[str, Any]] = {}
    template_probe = template_compatibility_probe()
    order_probe = synthetic_order_probes()
    template_generations: Counter = Counter()
    for record in records:
        direction = direction_of(record)
        generation = question_template_generation(record["question"])
        template_generations[generation] += 1
        if direction == "inverse":
            detail = predict_inverse(record)
        else:
            detail = predict_forward(record)
        predictions[record["id"]] = detail["predicted"]
        details[record["id"]] = {
            "id": record["id"],
            "type": record["type"],
            "direction": direction,
            "num_states": len(record["key_frame_ids"]),
            "gt": list(record["gt_answer"]),
            "baseline_prediction": detail["predicted"],
            "unresolved_labels": detail["unresolved_labels"],
            "action_header": detail["header"],
            "question_template_generation": generation,
        }
        if direction == "inverse":
            details[record["id"]].update({
                "stages": detail["stages"],
                "stage_evidence": detail["stage_evidence"],
                "tie_groups": detail["tie_groups"],
            })
        else:
            details[record["id"]].update({
                "stages": detail["stages"],
                "action_list_is_chronological": detail["action_list_is_chronological"],
                "label_mapping_available_in_text": detail["label_mapping_available_in_text"],
            })

    predictions_out = Path(args.predictions_out) if args.predictions_out else None
    if predictions_out is not None:
        predictions_out.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        for record in records:
            detail = details[record["id"]]
            rows.append({
                "id": record["id"],
                "type": record["type"],
                "task_name": record["task_name"],
                "num_states": detail["num_states"],
                "answer": predictions[record["id"]],
                "status": "success",
                "backend": f"text_prior_baseline/{RULE_VERSION}",
            })
        predictions_out.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                                   encoding="utf-8")

    evaluator = USIMEvaluator(data_root)
    try:
        evaluator.precheck(records)
    except Exception as error:
        print(f"资产预检查失败，拒绝基线评分：{error}", file=sys.stderr)
        return 2
    result = evaluator.evaluate(records, predictions)
    items = {item["id"]: item for bucket in result["items"].values() for item in bucket}
    item_list = [items[record["id"]] for record in records]

    metrics = {
        "overall": metric_block(item_list),
        "by_direction": {key: metric_block(rows) for key, rows in group(item_list, lambda item: (
            "inverse" if "inverse" in item["type"] else "forward")).items()},
        "by_setting": {key: metric_block(rows) for key, rows in group(
            item_list, lambda item: f"{'inverse' if 'inverse' in item['type'] else 'forward'}_L{item['num_states']}").items()},
    }

    identity_stats = {
        "overall": {
            "identity_answer_rate": metrics["overall"]["identity_answer_rate"],
            "identity_reference_rate": round(sum(
                1 for record in records
                if list(record["gt_answer"]) == identity_permutation(len(record["gt_answer"]))) / len(records), 4),
        },
        "by_setting": {
            setting: {
                "identity_answer_rate": block["identity_answer_rate"],
                "identity_reference_rate": round(sum(
                    1 for record in records if setting_of(record) == setting
                    and list(record["gt_answer"]) == identity_permutation(len(record["gt_answer"]))) /
                    max(1, sum(1 for record in records if setting_of(record) == setting)), 4),
            }
            for setting, block in metrics["by_setting"].items()
        },
    }

    qa_by_id = {record["id"]: record for record in records}
    condition_c_items = Path(args.condition_c_items) if args.condition_c_items else None
    comparison: Dict[str, Any] = {}
    if condition_c_items is not None and condition_c_items.is_file():
        comparison = comparison_with_condition_c(items, load_condition_items(condition_c_items), qa_by_id)
    else:
        comparison = {"skipped": "no matching condition-C items provided (pass --condition-c-items "
                                 "with the report.items.jsonl of a run on this exact QA set)"}

    forward_details = [details[record["id"]] for record in records if direction_of(record) == "forward"]
    inverse_details = [details[record["id"]] for record in records if direction_of(record) == "inverse"]
    observations: List[str] = []
    observations.append(
        f"规则 {RULE_VERSION} 同时支持 v0.1/v0.2 两套动作文本模板；模板自检 "
        f"{sum(1 for row in template_probe['rows'] if row['pass'])}/{template_probe['probes_total']} 通过；"
        f"合成 inverse 排序自检 {sum(1 for row in order_probe['rows'] if row['pass'])}/{order_probe['probes_total']} 通过；"
        f"本轮 question 模板代际分布 {dict(sorted(template_generations.items()))}。")
    if inverse_details:
        inverse_correct = sum(1 for detail in inverse_details if detail["baseline_prediction"] == detail["gt"])
        observations.append(
            f"inverse 文本基线 EM = {inverse_correct}/{len(inverse_details)}：动作行按生命周期词序即可唯一排序，"
            "该组题在无图条件下是文本可解的。")
        if inverse_correct < len(inverse_details):
            unresolved = sorted({label for detail in inverse_details for label in detail["unresolved_labels"]})
            observations.append(f"inverse 基线存在 {len(inverse_details) - inverse_correct} 题未完全命中，"
                                f"未解析标签 {unresolved[:10]}；若为新模板导致，请扩展 STAGE_PATTERNS 并升 rule_version。")
    if forward_details:
        observations.append(
            f"forward 文本基线采用恒等先验：{len(forward_details)} 题中动作列表全部按时间顺序给出，"
            "但题目不含 future-image 标签到动作的映射，文本无法消解标签顺序；"
            f"forward EM = {sum(1 for detail in forward_details if detail['baseline_prediction'] == detail['gt'])}"
            f"/{len(forward_details)}（等于恒等参考率）。")
    if inverse_details and any(detail["tie_groups"] for detail in inverse_details):
        observations.append("inverse 存在同生命周期阶段的并列动作，按标签升序打破并列（确定性规则）。")
    if comparison and "EM_delta_baseline_minus_C" in comparison:
        observations.append(
            f"条件 C（去图模型）总体 EM {comparison['condition_overall']['EM']:.4f} vs 确定性文本基线 "
            f"{comparison['baseline_overall']['EM']:.4f}（Δ={comparison['EM_delta_baseline_minus_C']:+.4f}）；"
            "C 的分数没有超出文本先验可解释的范围。")

    script_path = Path(__file__).resolve()
    evidence = {
        "schema": "usim_text_prior_baseline/v2",
        "rule_version": RULE_VERSION,
        "rule_script_sha256": sha256_file(script_path),
        "rule_script_path": relative_repo_path(script_path),
        "generated_at": now_iso(),
        "dataset_version": dataset_version,
        "qa_file": str(qa_path),
        "qa_sha256": sha256_file(qa_path),
        "evaluation_protocol": EVALUATION_PROTOCOL,
        "predictions_out": ({"path": relative_repo_path(predictions_out),
                             "sha256": sha256_file(predictions_out),
                             "rows": len(predictions)} if predictions_out is not None else None),
        "scored_by": "scripts/usim/evaluate.py USIMVerifier (real verifier, same path as the model conditions)",
        "template_compatibility": template_probe,
        "synthetic_order_probes": order_probe,
        "question_template_generations": dict(sorted(template_generations.items())),
        "rules": {
            "target": "predict the answer permutation from the question text only",
            "forbidden_inputs": ["gt_answer", "images", "key_frame_ids", "model predictions"],
            "stage_ranks": STAGE_ORDER,
            "lifecycle_without_touching": "OnSeabed(0) < NextTo(10) < InGripper(20) < Lifted(30) < InBox(40)",
            "touching_rank": "Touching(15) sits between NextTo(10) and InGripper(20) per the v0.2 "
                             "guideline ('contact before holding')",
            "stage_patterns": [{"rank": rank, "predicate": predicate, "regex": pattern,
                                "template_generation": generation}
                               for rank, predicate, pattern, generation in STAGE_PATTERNS],
            "negation_guard": {"patterns": list(NEGATION_PATTERNS),
                               "effect": "negated sentences do not contribute a stage"},
            "inverse_rule": "parse [Action N] lines; rank(N)=max positive lifecycle rank; "
                            "order labels by (rank asc, label asc)",
            "forward_rule": "identity permutation (fixed label prior); the text gives no "
                            "action->future-image-label mapping",
            "rule_source": [
                "enact/adapters/usim_translator.py USIM_STATE_TEMPLATES (v0.1 'next to'/'touching'; "
                "v0.2 'in position for the pre-grasp approach beside'/'in contact with')",
                "docs/WBR/ENACT-USIM-v0.2标注与关键帧规范-20261027.md §2.1-2.2 (NextTo approach semantics, "
                "Touching before grasp), §9.6 (template changes)",
                "docs/06_data_and_evaluation_contract.md §4",
            ],
            "tie_break": "ascending label order",
        },
        "counts": {
            "questions": len(records),
            "by_type": dict(sorted(Counter(record["type"] for record in records).items())),
        },
        "predictions": details,
        "metrics": metrics,
        "identity": identity_stats,
        "chance": chance_block(records),
        "comparison_condition_c": comparison,
        "observations": observations,
    }

    out_path = Path(args.out) if args.out else DEFAULT_OUT_DIR / f"text_prior_baseline_{dataset_version}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    summary = {
        "dataset_version": dataset_version,
        "rule_version": RULE_VERSION,
        "rule_script_sha256": evidence["rule_script_sha256"],
        "template_compatibility": {
            "all_pass": template_probe["all_pass"],
            "probes": template_probe["probes_total"],
            "generations_covered": template_probe["generations_covered"],
        },
        "synthetic_order_probes": {
            "all_pass": order_probe["all_pass"],
            "probes": order_probe["probes_total"],
            "rows": [{"name": row["name"], "pass": row["pass"],
                      "expected": row["expected_prediction"], "actual": row["actual_prediction"]}
                     for row in order_probe["rows"]],
        },
        "question_template_generations": evidence["question_template_generations"],
        "baseline_overall": metrics["overall"],
        "by_setting": metrics["by_setting"],
        "identity": identity_stats,
        "chance": evidence["chance"],
        "condition_c": {
            "overall_EM": comparison.get("condition_overall", {}).get("EM") if comparison else None,
            "delta_baseline_minus_C": comparison.get("EM_delta_baseline_minus_C") if comparison else None,
            "paired": comparison.get("paired") if comparison else None,
            "by_setting": comparison.get("by_setting") if comparison else None,
        },
        "observations": observations,
        "evidence": str(out_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not template_probe["all_pass"]:
        failed = [row for row in template_probe["rows"] if not row["pass"]]
        print(f"template compatibility probe failed: {failed}", file=sys.stderr)
        return 2
    if not order_probe["all_pass"]:
        failed = [row for row in order_probe["rows"] if not row["pass"]]
        print(f"synthetic order probe failed: {failed}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
