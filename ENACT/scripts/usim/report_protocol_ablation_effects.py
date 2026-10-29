"""Read-only paired analysis of a complete no-prefill/prefill development matrix.

The frozen execution/scoring modules are unchanged. All primary and secondary
rates retain the full QA denominator; bootstrap draws complete episodes jointly.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ENACT = Path(__file__).resolve().parents[2]
WORKSPACE = ENACT.parent
for path in (ENACT, WORKSPACE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts.usim import protocol_ablation_v1 as contract
from tools.verify_protocol_ablation import verify

METRICS = ("EM", "TA", "PA_item_mean", "PA_transition_micro", "secondary_EM_full_denominator",
           "strict_valid_rate", "extractable_rate", "truncation_rate")


def vector(row: dict) -> np.ndarray:
    return np.array([row["exact_match"], row["task_accuracy"], row["pairwise_accuracy"],
                     row["pairwise_accuracy"] * row["num_transitions"], row["secondary_correct"],
                     row["parsed"] is not None, row["extractable"], row["truncated"]], dtype=float)


def cluster_sums(rows: list[dict], episodes: list[str]) -> tuple[np.ndarray, np.ndarray]:
    sums = np.zeros((len(episodes), len(METRICS)))
    denominators = np.zeros_like(sums)
    index = {episode: position for position, episode in enumerate(episodes)}
    for row in rows:
        position = index[row["task_name"]]
        sums[position] += vector(row)
        denominators[position] += np.array([1, 1, 1, row["num_transitions"], 1, 1, 1, 1])
    return sums, denominators


def bootstrap_contrast(terms: list[tuple[float, list[dict]]], resamples: int, seed: int) -> dict:
    """Whole-episode bootstrap of a mean or linear contrast; no per-item rounding."""
    if not terms or any(not rows for _, rows in terms):
        raise ValueError("bootstrap terms must have nonempty rows")
    episodes = sorted({row["task_name"] for _, rows in terms for row in rows})
    rng = np.random.default_rng(seed)
    draws = rng.multinomial(len(episodes), [1.0 / len(episodes)] * len(episodes), size=resamples)
    points = np.zeros(len(METRICS))
    values = np.zeros((resamples, len(METRICS)))
    for coefficient, rows in terms:
        numerators, denominators = cluster_sums(rows, episodes)
        if np.any(denominators.sum(axis=0) == 0):
            raise ValueError("empty metric denominator")
        points += coefficient * numerators.sum(axis=0) / denominators.sum(axis=0)
        sampled_denominator = draws @ denominators
        if np.any(sampled_denominator == 0):
            raise ValueError("paired terms must share episode support; refusing a zero denominator bootstrap")
        values += coefficient * (draws @ numerators) / sampled_denominator
    return {"unit": "episode", "episodes": len(episodes), "resamples": resamples, "seed": seed,
            "metrics": {name: {"point": float(points[i]), "ci_low": float(np.quantile(values[:, i], 0.025)),
                               "ci_high": float(np.quantile(values[:, i], 0.975))} for i, name in enumerate(METRICS)}}


def metric_block(rows: list[dict]) -> dict:
    episodes = sorted({row["task_name"] for row in rows})
    if not rows:
        return {"N": 0, "episodes": 0}
    numerators, denominators = cluster_sums(rows, episodes)
    values = numerators.sum(axis=0) / denominators.sum(axis=0)
    return {"N": len(rows), "episodes": len(episodes), "transitions": sum(row["num_transitions"] for row in rows),
            "strict_correct": sum(row["exact_match"] == 1 for row in rows),
            "secondary_correct": sum(row["secondary_correct"] for row in rows),
            "strict_valid": sum(row["parsed"] is not None for row in rows),
            "extractable": sum(row["extractable"] for row in rows),
            "truncated": sum(row["truncated"] for row in rows),
            "invalid_reasons": dict(Counter(row["reason"] for row in rows if row["parsed"] is None)),
            **{name: float(values[i]) for i, name in enumerate(METRICS)}}


def pair_rows(first: list[dict], second: list[dict], *, allow_subset: bool = False) -> tuple[list, list]:
    a, b = contract.unique(first), contract.unique(second)
    if not allow_subset and set(a) != set(b):
        raise ValueError("paired ID sets differ")
    if allow_subset and not (set(a) <= set(b) or set(b) <= set(a)):
        raise ValueError("paired subsets are not nested")
    ids = sorted(set(a) & set(b))
    if not ids:
        raise ValueError("empty paired intersection")
    for qid in ids:
        if any(a[qid][key] != b[qid][key] for key in ("task_name", "num_states", "gt")):
            raise ValueError("paired reference conflict")
    return [a[qid] for qid in ids], [b[qid] for qid in ids]


def comparison(first: list[dict], second: list[dict], resamples: int, seed: int, *, allow_subset=False) -> dict:
    a, b = pair_rows(first, second, allow_subset=allow_subset)
    counts = Counter()
    for x, y in zip(a, b):
        correct_x, correct_y = bool(x["exact_match"]), bool(y["exact_match"])
        counts["both_correct" if correct_x and correct_y else "only_first" if correct_x else "only_second" if correct_y else "both_wrong"] += 1
    common_extractable = [(x, y) for x, y in zip(a, b) if x["extractable"] and y["extractable"]]
    return {"N": len(a), "first": metric_block(a), "second": metric_block(b), "paired_strict_counts": dict(counts),
            "common_extractable": len(common_extractable),
            "common_extractable_permutation_agreement": sum(x["secondary_permutation"] == y["secondary_permutation"] for x, y in common_extractable),
            "bootstrap": bootstrap_contrast([(1.0, a), (-1.0, b)], resamples, seed)}


def derived_seed(base: int, label: str) -> int:
    return (base + int(hashlib.sha256(label.encode()).hexdigest()[:8], 16)) % (2 ** 32)


def distribution(values: list[float]) -> dict:
    return {"count": len(values), "sum": float(sum(values)), "min": float(min(values)),
            "median": float(np.median(values)), "p95": float(np.quantile(values, .95)), "max": float(max(values))} if values else {"count": 0}


def usage_block(predictions: list[dict], attempts: list[dict]) -> dict:
    tokens = {}
    for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
        values = [row["usage"][name] for row in predictions if isinstance(row.get("usage"), dict) and isinstance(row["usage"].get(name), (int, float))]
        tokens[name] = dict(distribution(values), missing=len(predictions) - len(values))
    groups = defaultdict(list)
    for row in attempts:
        groups[row["job_id"]].append(row)
    logical_latency = []
    for rows in groups.values():
        start = min(datetime.fromisoformat(row["started_at"]) for row in rows)
        end = max(datetime.fromisoformat(row["finished_at"]) for row in rows)
        logical_latency.append((end - start).total_seconds())
    return {"requests": len(predictions), "http_attempts": len(attempts), "retries": len(attempts) - len(predictions),
            "http_status_counts": dict(Counter(str(row["http_status"]) for row in attempts)),
            "model_returned": dict(Counter(str(row.get("model_returned")) for row in predictions)),
            "finish_reasons": dict(Counter(str(row.get("finish_reason")) for row in predictions)),
            "status_counts": dict(Counter(row["status"] for row in predictions)), "tokens": tokens,
            "api_attempt_latency_seconds": distribution([row["elapsed_seconds"] for row in attempts]),
            "logical_latency_seconds_including_retry_wait": distribution(logical_latency),
            "latency_excludes_between_request_throttle": True}


def collect(bundle: Path, plan: dict) -> tuple[dict, dict]:
    prior_path = ENACT / "data/usim_enact/_protocol/baselines_v0.2/text_prior_predictions.jsonl"
    prior = contract.unique(contract.read_rows(prior_path))
    data_root = Path(plan["data_root"])
    cells = {}
    provenance = {str(prior_path): contract.file_sha(prior_path)}
    for protocol in contract.PROTOCOLS:
        for condition, label in contract.CONDITIONS.items():
            source = bundle / protocol / label
            scoring = bundle / "analysis" / protocol / label
            files = [source / "predictions.jsonl", source / "attempts.jsonl", source / "responses.jsonl",
                     scoring / "report.items.jsonl", scoring / "report.json"]
            provenance.update({str(path): contract.file_sha(path) for path in files})
            predictions = contract.unique(contract.read_rows(source / "predictions.jsonl"))
            items = contract.read_rows(scoring / "report.items.jsonl")
            expected = set(plan["conditions"][condition]["ids"])
            if set(contract.unique(items)) != expected or set(predictions) != expected:
                raise ValueError("analysis input ID scope differs from frozen QA")
            rows = []
            for item in items:
                prediction = predictions[item["id"]]
                if item["parsed"] != prediction["strict_permutation"] or item["reason"] != prediction["strict_reason"]:
                    raise ValueError("stock score differs from response reparsing")
                if item["id"] not in prior:
                    raise ValueError("text baseline does not cover the entire QA scope")
                annotation_path = data_root / "annotations/episodes" / (item["task_name"] + ".json")
                annotation = contract.read_json(annotation_path)
                provenance[str(annotation_path)] = contract.file_sha(annotation_path)
                rows.append(dict(item, secondary_permutation=prediction["extract_permutation"],
                                 secondary_correct=prediction["extract_status"] == "ok" and prediction["extract_permutation"] == item["gt"],
                                 extractable=prediction["extract_status"] == "ok", truncated=prediction["finish_reason"] == "length",
                                 task_text=annotation["task_text"], direction="inverse" if "inverse" in item["type"] else "forward",
                                 setting=("inverse" if "inverse" in item["type"] else "forward") + f"_L{item['num_states']}",
                                 prior_correct=prior[item["id"]].get("answer") == item["gt"]))
            cells[f"{protocol}/{condition}"] = {"rows": rows, "usage": usage_block(list(predictions.values()), contract.read_rows(source / "attempts.jsonl"))}
    return cells, provenance


def analyse_effects(bundle: Path, *, bootstrap: int | None = None) -> dict:
    verification = verify(bundle)
    if not verification["ok"]:
        raise ValueError(f"complete-run verification failed: {verification['errors']}")
    plan = contract.read_json(bundle / "plan.json")
    settings = contract.read_json(bundle / "analysis/analysis_plan.json")
    count = settings["bootstrap_resamples"]
    if bootstrap is not None and bootstrap != count:
        raise ValueError("bootstrap count differs from the previously fixed analysis plan")
    seed = settings["bootstrap_seed"]
    cells, provenance = collect(bundle, plan)
    report = {"schema": "usim-protocol-effects-report/v1", "scope": "development exploratory comparison, not final test or equivalence proof",
              "plan_sha256": plan["plan_sha256"], "settings": settings, "source_sha256": provenance,
              "verification": verification, "cells": {}, "protocol_effects": {}, "input_effects": {}, "interactions": {}}
    for name, cell in cells.items():
        rows = cell["rows"]
        strata = {}
        for field in ("direction", "num_states", "setting", "task_text", "task_name", "prior_correct"):
            groups = defaultdict(list)
            for row in rows:
                groups[str(row[field])].append(row)
            strata[field] = {key: metric_block(value) for key, value in sorted(groups.items())}
        report["cells"][name] = {"overall": metric_block(rows), "bootstrap": bootstrap_contrast([(1.0, rows)], count, derived_seed(seed, name)),
                                 "strata": strata, "usage": cell["usage"]}
    for condition in contract.CONDITIONS:
        prefill = cells[f"prefill/{condition}"]["rows"]
        control = cells[f"no_prefill/{condition}"]["rows"]
        label = f"prefill_minus_no_prefill/{condition}"
        block = comparison(prefill, control, count, derived_seed(seed, label))
        by_setting = {}
        for direction, length in sorted({(row["direction"], row["num_states"]) for row in prefill}):
            a = [row for row in prefill if row["direction"] == direction and row["num_states"] == length]
            b = [row for row in control if row["direction"] == direction and row["num_states"] == length]
            by_setting[f"{direction}_L{length}"] = comparison(a, b, count, derived_seed(seed, label + f"/{direction}/{length}"))
        block["by_setting"] = by_setting
        block["by_text_prior"] = {}
        for flag in (True, False):
            a = [row for row in prefill if row["prior_correct"] == flag]
            b = [row for row in control if row["prior_correct"] == flag]
            if a:
                block["by_text_prior"][str(flag)] = comparison(a, b, count, derived_seed(seed, label + f"/prior/{flag}"))
        report["protocol_effects"][condition] = block
    for protocol in contract.PROTOCOLS:
        comparisons = {}
        for second in ("B", "C", "D"):
            comparisons[f"A-{second}"] = comparison(cells[f"{protocol}/A"]["rows"], cells[f"{protocol}/{second}"]["rows"],
                                                     count, derived_seed(seed, protocol + f"/A-{second}"), allow_subset=second == "D")
        # A/B/C/D comparison is explicitly restricted to the common forward IDs.
        ids = {row["id"] for row in cells[f"{protocol}/D"]["rows"]}
        report["input_effects"][protocol] = {"comparisons": comparisons,
            "common_forward": {key: metric_block([row for row in cells[f"{protocol}/{key}"]["rows"] if row["id"] in ids]) for key in contract.CONDITIONS}}
    terms = [(1., cells["prefill/B"]["rows"]), (-1., cells["no_prefill/B"]["rows"]),
             (-1., cells["prefill/A"]["rows"]), (1., cells["no_prefill/A"]["rows"])]
    report["interactions"]["protocol_effect_B_minus_A"] = bootstrap_contrast(terms, count, derived_seed(seed, "interaction_B_minus_A"))
    report["claim_limits"] = ["No causal guarantee for an alias-model snapshot", "No equivalence conclusion from nonsignificance",
                              "Secondary metric is not pure perception accuracy", "All formal requests remain in metric denominators",
                              "Smoke records excluded from all formal scores", "Small number of episodes; long L5 strata are particularly sparse"]
    return report


def metric_ci(block: dict, name: str = "EM") -> str:
    value = block["metrics"][name]
    return f"{value['point']:+.4f} [{value['ci_low']:+.4f}, {value['ci_high']:+.4f}]"


def markdown(report: dict) -> str:
    lines = ["# 双协议2048开发对照：主副指标与episode配对分析", "",
             "全部结果为dev；8次冒烟不计入分母。预填是明确的请求协议因素。", "",
             "| 协议/条件 | N | episode | 严格合法 | 截断 | EM | TA | PA_item | PA_micro | 副指标全题EM |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, cell in report["cells"].items():
        row = cell["overall"]
        lines.append(f"| {name} | {row['N']} | {row['episodes']} | {row['strict_valid']} | {row['truncated']} | {row['EM']:.4f} | {row['TA']:.4f} | {row['PA_item_mean']:.4f} | {row['PA_transition_micro']:.4f} | {row['secondary_EM_full_denominator']:.4f} |")
    lines += ["", "## 协议效应：预填减无预填", "", "episode配对bootstrap 10,000次；区间为95%百分位区间，未据显著性选择报告。", "",
              "| 条件 | N | 严格ΔEM [CI] | 副指标ΔEM [CI] | 仅预填对 | 仅无预填对 | 两侧可提取 | 排列一致 |",
              "|---|---:|---|---|---:|---:|---:|---:|"]
    for condition, block in report["protocol_effects"].items():
        counts = block["paired_strict_counts"]
        lines.append(f"| {condition} | {block['N']} | {metric_ci(block['bootstrap'])} | {metric_ci(block['bootstrap'], 'secondary_EM_full_denominator')} | {counts.get('only_first', 0)} | {counts.get('only_second', 0)} | {block['common_extractable']} | {block['common_extractable_permutation_agreement']} |")
    lines += ["", "## 输入效应：同协议比较", "", "| 协议 | 比较 | 共同N | ΔEM [CI] | 副指标ΔEM [CI] |", "|---|---|---:|---|---|"]
    for protocol, content in report["input_effects"].items():
        for label, block in content["comparisons"].items():
            lines.append(f"| {protocol} | {label} | {block['N']} | {metric_ci(block['bootstrap'])} | {metric_ci(block['bootstrap'], 'secondary_EM_full_denominator')} |")
    lines += ["", "## 用量与延迟", "", "latency为单逻辑请求从第一次开始到末次结束，含重试等待，不含请求间1秒限速。", "",
              "| 协议/条件 | HTTP尝试 | 输入tokens | 输出tokens | 输出最大 | 延迟中位s | 延迟P95s |", "|---|---:|---:|---:|---:|---:|---:|"]
    for name, cell in report["cells"].items():
        usage = cell["usage"]
        lines.append(f"| {name} | {usage['http_attempts']} | {usage['tokens']['prompt_tokens'].get('sum', 0):.0f} | {usage['tokens']['completion_tokens'].get('sum', 0):.0f} | {usage['tokens']['completion_tokens'].get('max', 0):.0f} | {usage['logical_latency_seconds_including_retry_wait'].get('median', 0):.3f} | {usage['logical_latency_seconds_including_retry_wait'].get('p95', 0):.3f} |")
    lines += ["", "## 方向、长度与文本基线分层", "", "程序文本基线答对/答错是基线行为，不表示题目对所有文本方法可解/不可解。", "",
              "| 协议/条件 | 分层 | N | 严格EM | 副指标全题EM |", "|---|---|---:|---:|---:|"]
    for name, cell in report["cells"].items():
        for field in ("setting", "prior_correct"):
            for label, row in cell["strata"][field].items():
                lines.append(f"| {name} | {field}={label} | {row['N']} | {row['EM']:.4f} | {row['secondary_EM_full_denominator']:.4f} |")
    lines += ["", "## 解读边界", ""] + [f"- {text}" for text in report["claim_limits"]]
    lines += ["", "全部episode/任务分层、精确计数与未舍入区间见JSON。不得把未显著解释为等价，或把外显token减少解释为内部推理消失。", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    bundle = args.run_dir.resolve()
    report = analyse_effects(bundle)
    folder = bundle / "analysis"
    (folder / "protocol_effects.json").write_bytes(contract.json_bytes(report))
    (folder / "report.md").write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"complete": True, "cells": len(report["cells"]), "bootstrap": report["settings"]["bootstrap_resamples"],
                      "output": str(folder / "report.md")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
