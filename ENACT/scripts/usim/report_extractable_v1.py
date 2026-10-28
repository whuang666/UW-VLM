"""Apply extractable_permutation_v1 to already-stored responses (read-only, post-hoc).

This script never re-runs a model, never rewrites a report and never touches frozen inputs.
It re-reads ``predictions.jsonl`` + ``report.items.jsonl`` for each condition and reports:

* ``extractable``: how many answers yield exactly one trailing valid permutation;
* ``extractable_rate`` with the **full** question count as the denominator;
* ``strict_valid`` (from the existing v0.3 report) side by side, as a cross-check only;
* ``zero_reasons``: why the rest failed, so ambiguity and truncation stay visible;
* ``EM_extractable``: gt comparison for extracted permutations, denominator = all questions.

The numbers are supplementary and labelled ``post_hoc``.  They do not upgrade the budget
gate, and the frozen v0.3 scores are untouched.

Usage:
    python scripts/usim/report_extractable_v1.py \
        --run-dir data/usim_enact/runs/qwen3.8-max/v02_dev_001 \
        --condition A=A_full_image --condition B=B_zoom ... \
        --out-json ... --out-md ...
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.usim.extractable_v1 import SPEC_TEXT, VERSION, extract  # noqa: E402


def load_jsonl(path: Path) -> List[Dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def response_text(prediction: Dict) -> Optional[str]:
    for key in ("raw", "answer", "response"):
        value = prediction.get(key)
        if isinstance(value, str):
            return value
    return None


def analyse(run_dir: Path, name: str, relative: str) -> Dict[str, Any]:
    condition_dir = run_dir / relative
    predictions = {row["id"]: row for row in load_jsonl(condition_dir / "predictions.jsonl")}
    items = load_jsonl(condition_dir / "report.items.jsonl")

    rows: List[Dict[str, Any]] = []
    for item in items:
        prediction = predictions.get(item["id"], {})
        # Length comes from the question structure, not from the answer key: an ordering
        # question over L states asks for a permutation of 1..(L-1) future states.
        expected_length = int(item["num_states"]) - 1
        if len(item["gt"]) != expected_length:  # keeps the no-gt rule honest
            raise SystemExit(f"{item['id']}: len(gt)={len(item['gt'])} != num_states-1={expected_length}")
        outcome = extract(response_text(prediction), prediction.get("finish_reason"), expected_length)
        correct = (outcome["permutation"] == list(item["gt"])) if outcome["status"] == "ok" else False
        rows.append({
            "id": item["id"],
            "num_states": int(item["num_states"]),
            "extract_status": outcome["status"],
            "extract_reason": outcome["reason"],
            "strict_valid": item.get("parsed") is not None,
            "finish_reason": prediction.get("finish_reason"),
            "extractable_correct": correct,
        })

    total = len(rows)
    extracted = [row for row in rows if row["extract_status"] == "ok"]
    strict_valid = sum(1 for row in rows if row["strict_valid"])
    reasons = Counter(row["extract_reason"] for row in rows if row["extract_status"] != "ok")

    return {
        "condition": name,
        "relative_dir": relative,
        "questions": total,
        "extractable": len(extracted),
        "extractable_rate": round(len(extracted) / total, 4) if total else 0.0,
        "strict_valid": strict_valid,
        "strict_valid_rate": round(strict_valid / total, 4) if total else 0.0,
        "extractable_correct": sum(1 for row in extracted if row["extractable_correct"]),
        "EM_extractable": round(sum(1 for row in extracted if row["extractable_correct"]) / total, 4) if total else 0.0,
        "accuracy_among_extracted": round(
            sum(1 for row in extracted if row["extractable_correct"]) / len(extracted), 4) if extracted else None,
        "zero_reasons": dict(sorted(reasons.items())),
        "rows_where_only_extractable": [
            row["id"] for row in rows if row["extract_status"] == "ok" and not row["strict_valid"]
        ],
    }


def markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# extractable_permutation_v1（副指标，事后探索）",
        "",
        f"- 版本：`{VERSION}`；`post_hoc=true`、`frozen=false`（test 前冻结）；运行目录 `{report['run_dir']}`",
        f"- 规则：{SPEC_TEXT}",
        "- **本表不改变主指标 `usim_strict_v0.3`，也不把任何 gate 改判为通过。**",
        "",
        "| 条件 | 题数 | 严格合法 | 严格合法率 | 可提取 | 可提取率 | 提取后答对 | EM(可提取/全题) | 提取后准确率 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["conditions"].values():
        lines.append(
            f"| {row['condition']} | {row['questions']} | {row['strict_valid']} | {row['strict_valid_rate']:.4f} "
            f"| {row['extractable']} | {row['extractable_rate']:.4f} | {row['extractable_correct']} "
            f"| {row['EM_extractable']:.4f} | "
            f"{row['accuracy_among_extracted'] if row['accuracy_among_extracted'] is not None else '-'} |")
    lines.append("")
    lines.append("## 未能提取的原因分布")
    lines.append("")
    for row in report["conditions"].values():
        if row["zero_reasons"]:
            detail = "、".join(f"`{key}` {value}" for key, value in row["zero_reasons"].items())
            lines.append(f"- **{row['condition']}**：{detail}")
        else:
            lines.append(f"- **{row['condition']}**：无（全部可提取）")
    lines.append("")
    lines.append("## 仅副指标可解析、严格解析失败的题")
    lines.append("")
    for row in report["conditions"].values():
        if row["rows_where_only_extractable"]:
            lines.append(f"- **{row['condition']}**（{len(row['rows_where_only_extractable'])} 题）："
                         + "、".join(f"`…{qid[-8:]}`" for qid in row["rows_where_only_extractable"]))
        else:
            lines.append(f"- **{row['condition']}**：无")
    lines.append("")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--condition", action="append", default=[], help="NAME=relative_dir，可重复")
    parser.add_argument("--out-json", default="")
    parser.add_argument("--out-md", default="")
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir).resolve()
    specs = args.condition or ["A=A_full_image"]
    conditions: Dict[str, Any] = {}
    for spec in specs:
        if "=" not in spec:
            raise SystemExit(f"--condition 需要 NAME=dir 形式：{spec}")
        name, relative = spec.split("=", 1)
        conditions[name] = analyse(run_dir, name, relative)

    report = {
        "version": VERSION,
        "metric": "extractable_permutation_v1 (secondary)",
        "post_hoc": True,
        "frozen": False,
        "primary_metric_unchanged": "usim_strict_v0.3",
        "affects_budget_gate": False,
        "spec": SPEC_TEXT,
        "run_dir": str(run_dir),
        "conditions": conditions,
    }

    if args.out_json:
        Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_json).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.out_md:
        Path(args.out_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_md).write_text(markdown(report) + "\n", encoding="utf-8")

    for name, row in conditions.items():
        print(f"{name}: strict {row['strict_valid']}/{row['questions']} -> extractable "
              f"{row['extractable']}/{row['questions']}  reasons={row['zero_reasons']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
