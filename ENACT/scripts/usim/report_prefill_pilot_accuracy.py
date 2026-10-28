"""P1: offline accuracy report for the existing 16-question prefill pilot.

No model calls.  The original predictions are read-only; for the prefill protocol we build a
**derived** scoring input whose ``answer`` is the fixed ``"[" + raw_completion``, in the shape
``evaluate.py`` already accepts (``id`` / ``status`` / ``answer``).  Nothing is written back into
the run directories, and no field is added to the stored predictions.

Reported separately, per protocol and condition:
  * strict EM over the full 16-question denominator (v0.3 contract, unchanged)
  * secondary metric over the same full denominator, plus validity / extractable rates
  * truncation rate, and the format-failure reasons
  * per-item pairing (both correct / only prefill / only no-prefill / both wrong)
  * permutation agreement when both sides are extractable

``post_hoc=true``: these numbers were produced after seeing the outputs.  They do not rewrite the
original format gate and they cannot establish that prefill is neutral.

Usage:
    python scripts/usim/report_prefill_pilot_accuracy.py
"""

from __future__ import annotations

import hashlib
import json
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.usim.evaluate import USIMEvaluator  # noqa: E402
from scripts.usim.extractable_v1 import VERSION as SECONDARY_VERSION, extract  # noqa: E402

DATA_ROOT = ROOT / "data/usim_enact/usim-enact-v0.2"
QA = DATA_ROOT / "QA/train/enact_ordering_curated.jsonl"
NO_PREFILL = ROOT / "data/usim_enact/runs/qwen3.8-max/v02_budget2048_diag_v1"
PREFILL = ROOT / "data/usim_enact/runs/qwen3.8-max/v02_prefill2048_diag_v1"
OUT = ROOT / "docs/WBW/evidence/prefill_pilot_accuracy_v1"
CONDITIONS = {"A": "A_full_image", "B": "B_zoom"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: Path) -> List[Dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def answer_of(entry: Dict, protocol: str) -> Optional[str]:
    """The text the primary parser sees, per protocol, with no repair of any kind."""
    if protocol == "prefill":
        return entry.get("completed_answer")
    return entry.get("raw_completion") or entry.get("answer")


def score_text(entry: Dict, qa: Dict, protocol: str) -> Dict[str, Any]:
    expected = len(qa["gt_answer"])
    text = answer_of(entry, protocol)
    finish = entry.get("finish_reason")
    permutation, reason = USIMEvaluator.parse_strict(text, expected)
    secondary = extract(text, finish, expected)
    return {
        "expected_length": expected,
        "strict_reason": reason,
        "strict_permutation": permutation,
        "strict_correct": permutation == list(qa["gt_answer"]),
        "extractable": secondary["status"] == "ok",
        "extract_reason": secondary["reason"],
        "extract_permutation": secondary["permutation"],
        "extract_correct": secondary["permutation"] == list(qa["gt_answer"]) if secondary["status"] == "ok" else False,
        "finish_reason": finish,
        "http_status": entry.get("http_status"),
        "completion_tokens": (entry.get("usage") or {}).get("completion_tokens"),
    }


def build_derived(protocol: str, label: str, entries: List[Dict]) -> Path:
    """Derived scoring input in the shape evaluate.py expects; originals untouched."""
    out_dir = OUT / "derived" / f"{protocol}_{label}"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for entry in entries:
        rows.append({
            "id": entry["id"],
            "status": entry.get("status") or ("success" if entry.get("http_status") == 200 else "failed"),
            "answer": answer_of(entry, protocol),
            # provenance only; evaluate.py ignores these
            "derived_from_protocol": protocol,
            "derived_from_file_sha256": entry["_source_sha256"],
            "raw_continuation_sha256": hashlib.sha256((entry.get("raw_completion") or "").encode()).hexdigest(),
        })
    path = out_dir / "predictions.jsonl"
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return path


def write_pilot_qa(qa: Dict[str, Dict], ids: List[str]) -> Path:
    """A 16-question QA subset so the stock evaluator scores the pilot, not all 120 questions."""
    path = OUT / "derived" / "pilot_qa.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [qa[qid] for qid in ids]
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8")
    return path


def main() -> int:
    qa = {row["id"]: row for row in load_jsonl(QA)}
    OUT.mkdir(parents=True, exist_ok=True)
    digests_before = {}

    summary: Dict[str, Any] = {
        "schema": "usim-prefill-pilot-accuracy/v1",
        "post_hoc": True,
        "api_requests": 0,
        "primary_metric": "usim_strict_v0.3 (unchanged, full denominator)",
        "secondary_metric": SECONDARY_VERSION,
        "note": "16 items per condition; paired pilot only. Does not rewrite the format gate and "
                "cannot establish that prefill is neutral.",
        "conditions": {},
    }
    all_rows: Dict[str, List[Dict]] = {}

    for name, label in CONDITIONS.items():
        blocks = {}
        for protocol, base in (("no_prefill", NO_PREFILL), ("prefill", PREFILL)):
            pred_path = base / label / "predictions.jsonl"
            digests_before[str(pred_path.relative_to(REPO))] = sha(pred_path)
            entries = load_jsonl(pred_path)
            seen = set()
            for entry in entries:
                if entry["id"] in seen:
                    raise SystemExit(f"duplicate id in {pred_path}: {entry['id']}")
                seen.add(entry["id"])
                if entry["id"] not in qa:
                    raise SystemExit(f"unknown id in {pred_path}: {entry['id']}")
                entry["_source_sha256"] = digests_before[str(pred_path.relative_to(REPO))]
            blocks[protocol] = entries
        if {entry["id"] for entry in blocks["no_prefill"]} != {entry["id"] for entry in blocks["prefill"]}:
            raise SystemExit(f"{name}: protocols do not cover the same question ids")

        rows = []
        for entry in blocks["no_prefill"]:
            qa_row = qa[entry["id"]]
            prefill_entry = next(item for item in blocks["prefill"] if item["id"] == entry["id"])
            no_pre = score_text(entry, qa_row, "no_prefill")
            pre = score_text(prefill_entry, qa_row, "prefill")
            rows.append({
                "id": entry["id"],
                "type": qa_row["type"],
                "episode": qa_row["task_name"],
                "gt": qa_row["gt_answer"],
                "no_prefill": no_pre,
                "prefill": pre,
                "pair": ("both_correct" if no_pre["strict_correct"] and pre["strict_correct"] else
                         "only_prefill" if pre["strict_correct"] else
                         "only_no_prefill" if no_pre["strict_correct"] else "both_wrong"),
                "extractable_agreement": (
                    None if not (no_pre["extractable"] and pre["extractable"])
                    else no_pre["extract_permutation"] == pre["extract_permutation"]),
            })

        n = len(rows)
        def rate(key: str, protocol: str) -> float:
            return round(sum(1 for row in rows if row[protocol][key]) / n, 4)

        blocks_summary = {
            "N": n,
            "episodes": len({row["episode"] for row in rows}),
            "no_prefill": {
                "strict_EM": rate("strict_correct", "no_prefill"),
                "secondary_EM": rate("extract_correct", "no_prefill"),
                "extractable_rate": rate("extractable", "no_prefill"),
                "truncation_rate": round(sum(1 for row in rows if row["no_prefill"]["finish_reason"] == "length") / n, 4),
                "strict_reasons": {reason: sum(1 for row in rows if row["no_prefill"]["strict_reason"] == reason)
                                   for reason in sorted({row["no_prefill"]["strict_reason"] for row in rows})},
            },
            "prefill": {
                "strict_EM": rate("strict_correct", "prefill"),
                "secondary_EM": rate("extract_correct", "prefill"),
                "extractable_rate": rate("extractable", "prefill"),
                "truncation_rate": round(sum(1 for row in rows if row["prefill"]["finish_reason"] == "length") / n, 4),
                "strict_reasons": {reason: sum(1 for row in rows if row["prefill"]["strict_reason"] == reason)
                                   for reason in sorted({row["prefill"]["strict_reason"] for row in rows})},
            },
            "paired": {kind: sum(1 for row in rows if row["pair"] == kind)
                       for kind in ("both_correct", "only_prefill", "only_no_prefill", "both_wrong")},
            "extractable_pairs": sum(1 for row in rows if row["extractable_agreement"] is not None),
            "extractable_agreement_true": sum(1 for row in rows if row["extractable_agreement"] is True),
            "strict_delta_EM": round(rate("strict_correct", "prefill") - rate("strict_correct", "no_prefill"), 4),
            "secondary_delta_EM": round(rate("extract_correct", "prefill") - rate("extract_correct", "no_prefill"), 4),
            "token_totals": {protocol: sum((entry.get("usage") or {}).get("completion_tokens", 0)
                                          for entry in blocks[protocol]) for protocol in ("no_prefill", "prefill")},
        }
        summary["conditions"][name] = blocks_summary
        all_rows[name] = rows

        # derived scoring inputs for the stock evaluator, then score them with it
        pilot_qa = write_pilot_qa(qa, [entry["id"] for entry in blocks["no_prefill"]])
        for protocol, base in (("no_prefill", NO_PREFILL), ("prefill", PREFILL)):
            derived = build_derived(protocol, label, blocks[protocol])
            report_path = derived.parent / "report.json"
            command = [sys.executable, str(ROOT / "scripts/usim/evaluate.py"),
                       "--data-root", str(DATA_ROOT), "--qa", str(pilot_qa),
                       "--predictions", str(derived), "--out", str(report_path)]
            completed = subprocess.run(command, capture_output=True, text=True)
            blocks_summary[protocol]["stock_evaluate_report"] = str(report_path.relative_to(REPO))
            blocks_summary[protocol]["stock_evaluate_exit"] = completed.returncode
            if report_path.exists():
                report = json.loads(report_path.read_text(encoding="utf-8"))
                blocks_summary[protocol]["stock_evaluate_EM"] = report.get("overall", {}).get("EM")

    digests_after = {key: sha(REPO / key) for key in digests_before}
    summary["sources_unchanged"] = digests_after == digests_before
    summary["source_sha256"] = digests_after
    summary["qa_sha256"] = sha(QA)

    OUT.joinpath("summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with OUT.joinpath("paired_items.jsonl").open("w", encoding="utf-8") as handle:
        for name in CONDITIONS:
            for row in all_rows[name]:
                handle.write(json.dumps({"condition": name, **row}, ensure_ascii=False) + "\n")
    OUT.joinpath("report.md").write_text(render(summary), encoding="utf-8")
    print(json.dumps(summary["conditions"], indent=2, ensure_ascii=False))
    print(json.dumps({"sources_unchanged": summary["sources_unchanged"], "out": str(OUT.relative_to(REPO))},
                     ensure_ascii=False))
    return 0


def render(summary: Dict[str, Any]) -> str:
    lines = [
        "# 预填 pilot 离线评分（事后，16 题 × A/B）",
        "",
        "`post_hoc=true`、`api_requests=0`。主指标 `usim_strict_v0.3`（全题分母，不变）；副指标 "
        f"`{summary['secondary_metric']}`。原预测未改写，派生的评分输入在 `derived/` 下。",
        "",
        "| 条件 | N | 协议 | 严格 EM | 副指标 EM | 可提取率 | 截断率 |",
        "|---|---:|---|---:|---:|---:|---:|",
    ]
    for name, block in summary["conditions"].items():
        for protocol in ("no_prefill", "prefill"):
            data = block[protocol]
            lines.append(f"| {name} | {block['N']} | {protocol} | {data['strict_EM']:.4f} "
                         f"| {data['secondary_EM']:.4f} | {data['extractable_rate']:.4f} | {data['truncation_rate']:.4f} |")
    lines += ["", "## 逐题配对", "", "| 条件 | 均对 | 仅预填对 | 仅无预填对 | 均错 | 严格 ΔEM | 副指标 ΔEM |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for name, block in summary["conditions"].items():
        paired = block["paired"]
        lines.append(f"| {name} | {paired['both_correct']} | {paired['only_prefill']} "
                     f"| {paired['only_no_prefill']} | {paired['both_wrong']} "
                     f"| {block['strict_delta_EM']:+.4f} | {block['secondary_delta_EM']:+.4f} |")
    lines += ["", "## 可提取排列一致性", ""]
    for name, block in summary["conditions"].items():
        lines.append(f"- **{name}**：两侧均可提取 {block['extractable_pairs']}/{block['N']} 题，"
                     f"其中排列完全一致 {block['extractable_agreement_true']} 题。")
    lines += ["", "## 边界", "",
              "1. 这是**事后**分析，且只有 16 题；不能据此断言预填「中立」或「等价」，也不能据此改写原格式 gate。",
              "2. 严格 EM 与副指标 EM 并列报告；副指标的分母始终是全题，条件于可提取子集的准确率只作辅助。",
              "3. 格式合法、正常停止、最终答对是三种不同状态，本表分列，不互相替代。"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
