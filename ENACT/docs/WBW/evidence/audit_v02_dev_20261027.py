"""Audit saved v0.2 development runs offline without rewriting frozen artifacts."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scripts.usim import evaluate, freeze_protocol  # noqa: E402
from scripts.usim.report_stats import paired_bootstrap, stable_seed  # noqa: E402


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def digest(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(Path(__file__).with_name("v02_dev_audit_20261027.json")))
    args = parser.parse_args()
    data = ROOT / "data/usim_enact"
    run = data / "runs/qwen3.8-max/v02_dev_001"
    data_root = data / "usim-enact-v0.2"
    freeze_path = data / "_protocol/freeze_usim-enact-v0.2_20261027b.json"
    freeze = read_json(freeze_path)
    frozen_report = freeze_protocol.verify_manifest(freeze)
    failures = []

    def check(ok, message):
        if not ok:
            failures.append(message)

    check(frozen_report["ok"], "frozen input manifest no longer verifies")
    result = {
        "checked_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "scope": "Read-only local audit; no API calls; re-score outputs go to a temporary directory.",
        "run": str(run.relative_to(ROOT)),
        "freeze": {
            "file": str(freeze_path.relative_to(ROOT)),
            "sha256": digest(freeze_path),
            "payload_sha256": freeze["manifest_payload_sha256"],
            "ok": frozen_report["ok"],
            "groups": len(frozen_report["groups"]),
            "files": sum(group["actual_count"] for group in frozen_report["groups"].values()),
            "errors": frozen_report["errors"],
        },
        "dataset": freeze["dataset"]["counts"],
        "conditions": {},
    }
    items, configs, sources = {}, {}, {}
    prior_path = data / "_protocol/baselines_v0.2/text_prior_predictions.jsonl"
    prior = {row["id"]: row["answer"] for row in read_jsonl(prior_path)}
    result["text_prior"] = {"path": str(prior_path.relative_to(ROOT)), "sha256": digest(prior_path)}
    conditions = {"A": "A_full_image", "B": "B_zoom", "C": "C_text_only", "D": "D_no_action_text"}
    with tempfile.TemporaryDirectory(prefix="uwvlm-v02-audit-") as temp:
        for label, folder in conditions.items():
            directory = run / folder
            report = read_json(directory / "report.json")
            configs[label] = read_json(directory / "run_config.json")
            config = configs[label]
            status = read_json(directory / "run_status.json")
            predictions = read_jsonl(directory / "predictions.jsonl")
            attempts = read_jsonl(directory / "attempts.jsonl")
            raw_items = read_jsonl(directory / "report.items.jsonl")
            items[label] = {row["id"]: row for row in raw_items}
            qa_path = Path(config["qa_path"])
            qa_ids = [row["id"] for row in read_jsonl(qa_path)]
            pred_ids = [row["id"] for row in predictions]
            check(len(pred_ids) == len(set(pred_ids)) == len(qa_ids), f"{label}: duplicate or missing predictions")
            check(set(pred_ids) == set(qa_ids) == set(items[label]), f"{label}: prediction/QA/scored ID mismatch")
            check(digest(qa_path) == config["qa_sha256"], f"{label}: QA hash changed")
            sources[label] = config["code_sha256"]
            check(all(digest(ROOT / path) == sha for path, sha in sources[label].items()), f"{label}: source hash changed")
            images = read_json(directory / "input_manifest.json")["records"]
            check(all(digest(data_root / image["path"]) == image["sha256"]
                      for record in images for image in record["images"]), f"{label}: image input hash mismatch")
            out = Path(temp) / f"{label}.json"
            with redirect_stdout(io.StringIO()):
                exit_code = evaluate.main([
                    "--data-root", str(data_root), "--qa", str(qa_path),
                    "--predictions", str(directory / "predictions.jsonl"), "--out", str(out),
                ])
            rescored = read_json(out)
            identical = report["overall"] == rescored["overall"] and report["by_setting"] == rescored["by_setting"]
            check(exit_code == 0 and identical, f"{label}: saved score not reproduced")
            strata = {}
            for hit in (True, False):
                rows = [row for row in raw_items if (prior[row["id"]] == row["gt"]) == hit]
                correct = sum(bool(row["exact_match"]) for row in rows)
                strata["prior_correct" if hit else "prior_incorrect"] = {
                    "count": len(rows), "correct": correct,
                    "EM": round(correct / len(rows), 4) if rows else None,
                    "invalid": sum(row["parsed"] is None for row in rows),
                    "identity_gt": sum(row["gt"] == list(range(1, len(row["gt"]) + 1)) for row in rows),
                }
            pred_by_id = {row["id"]: row for row in predictions}
            invalid = [{
                "id": row["id"], "reason": row["reason"],
                "finish_reason": pred_by_id[row["id"]].get("finish_reason"),
                "completion_tokens": (pred_by_id[row["id"]].get("usage") or {}).get("completion_tokens"),
                "num_states": row["num_states"],
            } for row in raw_items if row["parsed"] is None]
            result["conditions"][label] = {
                "overall": report["overall"], "episodes": len({row["task_name"] for row in raw_items}),
                "re_score_identical": identical, "run_status": status,
                "decode": {key: config[key] for key in ("enable_thinking", "temperature", "max_completion_tokens")},
                "model_returned": dict(Counter(row.get("model_returned") for row in predictions)),
                "attempts": len(attempts), "attempt_numbers": dict(Counter(row["attempt"] for row in attempts)),
                "http_status": dict(Counter(row["http_status"] for row in attempts)),
                "strata": strata, "invalid_items": invalid,
                "report_sha256": digest(directory / "report.json"),
                "predictions_sha256": digest(directory / "predictions.jsonl"),
            }
    check(all(source == sources["A"] for source in sources.values()), "matrix source versions differ")
    result["same_source_version"] = all(source == sources["A"] for source in sources.values())
    result["matrix_requests"] = sum(block["attempts"] for block in result["conditions"].values())
    ids_d = set(items["D"])
    check(ids_d < set(items["A"]), "D is not a strict subset of A")
    check(set(items["A"]) == set(items["B"]) == set(items["C"]), "A/B/C IDs differ")
    check(all(items[label][qid]["gt"] == items["A"][qid]["gt"]
              and items[label][qid]["num_states"] == items["A"][qid]["num_states"]
              for label in conditions for qid in items[label]), "shared ID ground truths or widths differ")
    result["D_matched_forward"] = {
        label: {"count": len(ids_d), "correct": sum(bool(items[label][qid]["exact_match"]) for qid in ids_d),
                "EM": round(sum(bool(items[label][qid]["exact_match"]) for qid in ids_d) / len(ids_d), 4)}
        for label in conditions
    }
    result["paired_A_minus_C"] = paired_bootstrap(
        list(items["A"].values()), list(items["C"].values()), 2000,
        stable_seed(20261024, "pair:A_vs_C"),
    )
    result["paired_A_minus_C"]["base_seed"] = 20261024
    result["paired_A_minus_C"]["exact_delta_EM"] = (
        sum(bool(row["exact_match"]) for row in items["A"].values())
        - sum(bool(row["exact_match"]) for row in items["C"].values())
    ) / len(items["A"])
    result["test_reserve"] = {
        "target_episodes": freeze["test_reserve"]["registered_count"],
        "annotation_files": sorted(path.name for path in (data / "_expansion/annotation_work/test_reserve").glob("usim_train_episode_*.json")),
        "meaning": "Existing annotation files only; independent quality acceptance and final test evaluation are separate steps.",
    }
    result["interpretation"] = [
        "Returned model name is an alias; no immutable provider snapshot is established.",
        "prior_incorrect means the selected program baseline failed, not that text-only reasoning is impossible.",
        "D strata have 13/29 items; A/B/C strata have 55/29 items.",
        "All 13 prior-correct D references are identity permutations; their perfect score does not rule out that shortcut.",
        "B has 8 truncated prose responses and one stopped wrong-length L3 answer; perception and output-budget effects are confounded.",
        "Matrix exit 0 allows a condition exit 3; it does not mean every answer passed strict scoring.",
        "Statistics exit 2 is an integrity signal for unequal condition ID sets; use equal-scope A/B/C and forward-only A/D reports.",
    ]
    result["failures"] = failures
    result["all_checks_pass"] = not failures
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"all_checks_pass": not failures, "freeze_ok": frozen_report["ok"],
                      "requests": result["matrix_requests"], "out": str(out), "failures": failures}, ensure_ascii=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
