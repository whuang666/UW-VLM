"""Boundary probes for the usim_strict_v0.2 scoring contract.

Produces machine-readable evidence for the four P0 items in docs/WBW §3:

* fixed denominator: L=3 perfect + L=4 missing  ->  PA_transition_micro == 0.4
* missing assets abort scoring (no partial report)
* strict parsing rejects explanations / multiple arrays / non-permutations
* duplicate prediction IDs are rejected

Usage:
    python scripts/usim/check_scoring_contract.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enact.adapters.usim_annotations import PROTOCOL_VERSION  # noqa: E402
from scripts.usim.evaluate import AssetError, USIMEvaluator, load_predictions  # noqa: E402

DEFAULT_DATA_ROOT = ROOT / "data" / "usim_enact" / PROTOCOL_VERSION
EVIDENCE = ROOT / "docs" / "WBW" / "evidence" / "scoring_contract_20261024.json"


def main() -> int:
    data_root = Path(DEFAULT_DATA_ROOT)
    qa_path = data_root / "QA" / "train" / "enact_ordering.jsonl"
    records = [json.loads(line) for line in qa_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    evaluator = USIMEvaluator(data_root)

    evidence: Dict[str, object] = {"data_root": str(data_root), "qa": str(qa_path), "probes": {}}

    # ---- probe 1: fixed denominator
    l3 = next(r for r in records if r["type"] == "forward_world_modeling_3_steps")
    l4 = next(r for r in records if r["type"] == "forward_world_modeling_4_steps")
    pair = [l3, l4]
    predictions = {l3["id"]: list(l3["gt_answer"])}  # L=4 deliberately missing
    result = evaluator.evaluate(pair, predictions)
    items = [item for bucket in result["items"].values() for item in bucket]
    summary = evaluator.summarise(items)
    evidence["probes"]["mixed_valid_missing"] = {
        "expected_PA_transition_micro": round(2 / (2 + 3), 4),
        "actual": summary,
        "pass": summary["PA_transition_micro"] == 0.4 and summary["EM"] == 0.5,
    }

    # ---- probe 2: missing asset aborts
    broken = dict(l3)
    broken["task_name"] = "usim_train_episode_999999"
    try:
        evaluator.precheck([broken])
        asset_failed = False
        asset_message = "no error raised"
    except AssetError as error:
        asset_failed = True
        asset_message = str(error).splitlines()[0]
    evidence["probes"]["missing_asset"] = {
        "precheck_raises": asset_failed,
        "message": asset_message,
        "pass": asset_failed,
    }

    # ---- probe 3: strict parser
    cases = {
        "[1, 2]": ("ok", [1, 2]),
        "  [2, 1]  ": ("ok", [2, 1]),
        "Explanation: [1, 2]": ("extra_text", None),
        "[2, 1] then [1, 2]": ("unparsable", None),
        "[0, 1]": ("not_a_permutation", None),
        "[1, 1]": ("not_a_permutation", None),
        "[1, 2, 3]": ("wrong_length", None),
        "[true, 1]": ("non_integer", None),
        "[1, ": ("unparsable", None),
        "": ("empty", None),
        "no answer": ("extra_text", None),
    }
    parser_rows = {}
    parser_pass = True
    for text, (expected_reason, expected_value) in cases.items():
        value, reason = evaluator.parse_strict(text, 2)
        ok = reason == expected_reason and value == expected_value
        parser_pass = parser_pass and ok
        parser_rows[text] = {"reason": reason, "value": value, "expected_reason": expected_reason, "pass": ok}
    evidence["probes"]["strict_parser"] = {"cases": parser_rows, "pass": parser_pass}

    # ---- probe 4: duplicate prediction IDs
    with tempfile.TemporaryDirectory() as tmp:
        dup_path = Path(tmp) / "dup.jsonl"
        dup_path.write_text(
            "\n".join(
                [
                    json.dumps({"id": l3["id"], "answer": "[1, 2]"}),
                    json.dumps({"id": l3["id"], "answer": "[2, 1]"}),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        _, duplicates = load_predictions(dup_path)
    evidence["probes"]["duplicate_predictions"] = {
        "duplicates_detected": duplicates,
        "pass": duplicates == [l3["id"]],
    }

    evidence["all_pass"] = all(block.get("pass") for block in evidence["probes"].values())
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(evidence["probes"], indent=2, ensure_ascii=False)[:2500])
    print(f"all_pass={evidence['all_pass']}  evidence={EVIDENCE}")
    return 0 if evidence["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
