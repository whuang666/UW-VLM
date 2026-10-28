"""Direction x L x task / episode statistics with episode-grouped bootstrap and paired conditions.

Every condition is paired against every other one, so this works for A/B/C as well as for
the four-condition v0.2 matrix (A/B/C/D).  The v0.2 development set has 84 questions from
19 episodes (val adds 36 from 8 episodes); treating the questions as independent
trajectories would overstate the evidence, so this script:

* rebuilds the per-question metrics from ``report.items.jsonl`` (no re-scoring);
* reports overall / direction / direction x L / episode / task tables;
* computes **cluster bootstrap** confidence intervals by resampling *episodes*
  (all questions of a sampled episode stay together), not questions;
* pairs conditions A/B/C on the identical frozen ID set and reports
  both-correct / only-first / only-second counts plus a paired episode bootstrap
  CI of the EM and PA difference;
* counts invalid / missing / format-error answers and cross-checks them against
  ``report.json`` and ``run_status.json``;
* reports the identity-answer rate and the identity-reference chance level.

Output is deterministic for a fixed ``--seed`` / ``--bootstrap``: no timestamps
are embedded, all mappings are sorted, floats are rounded.

Usage:
    python -m scripts.usim.report_stats \
        --run-dir data/usim_enact/runs/qwen3.8-max/dev_ego_thinking_false_001 \
        --condition A=full_v1 --condition B=condB_zoom --condition C=condC_text_only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enact.adapters.usim_annotations import PROTOCOL_VERSION  # noqa: E402

DEFAULT_DATA_ROOT = ROOT / "data" / "usim_enact" / PROTOCOL_VERSION
DEFAULT_RUN_ROOT = ROOT / "data" / "usim_enact" / "runs" / "qwen3.8-max" / "dev_ego_thinking_false_001"
DEFAULT_OUT_DIR = ROOT / "data" / "usim_enact" / "_protocol" / "stats"
METRIC_KEYS = ("EM", "TA", "PA_item_mean", "PA_transition_micro")


# ------------------------------------------------------------------ utilities
def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_seed(base_seed: int, label: str) -> int:
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()
    return (base_seed + int(digest[:8], 16)) % (2**31 - 1)


def percentile(sorted_values: Sequence[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = fraction * (len(sorted_values) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def direction_of(item: Dict[str, Any]) -> str:
    return "inverse" if "inverse" in item["type"] else "forward"


def setting_of(item: Dict[str, Any]) -> str:
    return f"{direction_of(item)}_L{item['num_states']}"


def identity_permutation(num_transitions: int) -> List[int]:
    return list(range(1, num_transitions + 1))


# ---------------------------------------------------------------- aggregation
def metric_block(items: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    count = len(items)
    if count == 0:
        return {"count": 0}
    transitions = sum(int(item["num_transitions"]) for item in items)
    invalid_reasons: Dict[str, int] = Counter(
        item["reason"] for item in items if item.get("parsed") is None)
    identity_answers = sum(1 for item in items if item.get("parsed") == identity_permutation(int(item["num_transitions"])))
    identity_references = sum(1 for item in items if list(item["gt"]) == identity_permutation(int(item["num_transitions"])))
    em = mean([float(item["exact_match"]) for item in items])
    semantic = mean([float(item["semantic_match"]) for item in items])
    ta = mean([float(item["task_accuracy"]) for item in items])
    pa_item = mean([float(item["pairwise_accuracy"]) for item in items])
    pa_micro = sum(float(item["pairwise_accuracy"]) * int(item["num_transitions"]) for item in items) / transitions
    return {
        "count": count,
        "episodes": len({item["task_name"] for item in items}),
        "transitions_total": transitions,
        "valid_permutations": count - sum(invalid_reasons.values()),
        "invalid_or_missing": sum(invalid_reasons.values()),
        "invalid_reasons": dict(sorted(invalid_reasons.items())),
        "EM": round(em, 4),
        "TA": round(ta, 4),
        "semantic_only": round(semantic - em, 4),
        "PA_item_mean": round(pa_item, 4),
        "PA_transition_micro": round(pa_micro, 4),
        "identity_answers": identity_answers,
        "identity_answer_rate": round(identity_answers / count, 4),
        "identity_reference_rate": round(identity_references / count, 4),
    }


def group_items(items: Sequence[Dict[str, Any]], key) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[key(item)].append(item)
    return dict(sorted(grouped.items()))


# ------------------------------------------------------------------- bootstrap
def cluster_bootstrap(items: Sequence[Dict[str, Any]], resamples: int, seed: int,
                      fraction_low: float = 0.025, fraction_high: float = 0.975) -> Dict[str, Any]:
    """Percentile CI from resampling whole episodes with replacement."""
    by_episode: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in items:
        by_episode[item["task_name"]].append(item)
    episodes = sorted(by_episode)
    if not episodes:
        return {"episodes": 0, "resamples": 0}
    rng = random.Random(seed)
    samples: Dict[str, List[float]] = {key: [] for key in METRIC_KEYS}
    for _ in range(resamples):
        drawn = [episodes[rng.randrange(len(episodes))] for _ in range(len(episodes))]
        rows = [item for episode in drawn for item in by_episode[episode]]
        if not rows:
            continue
        block = metric_block(rows)
        samples["EM"].append(block["EM"])
        samples["TA"].append(block["TA"])
        samples["PA_item_mean"].append(block["PA_item_mean"])
        samples["PA_transition_micro"].append(block["PA_transition_micro"])
    point = metric_block(items)
    result: Dict[str, Any] = {"episodes": len(episodes), "resamples": resamples, "unit": "episode"}
    for key in METRIC_KEYS:
        values = sorted(samples[key])
        result[key] = {
            "point": point[key],
            "ci_low": round(percentile(values, fraction_low), 4),
            "ci_high": round(percentile(values, fraction_high), 4),
        }
    return result


def paired_bootstrap(items_a: Sequence[Dict[str, Any]], items_b: Sequence[Dict[str, Any]],
                     resamples: int, seed: int,
                     fraction_low: float = 0.025, fraction_high: float = 0.975) -> Dict[str, Any]:
    """Paired episode bootstrap of metric differences (A minus B) on common IDs."""
    map_a = {item["id"]: item for item in items_a}
    map_b = {item["id"]: item for item in items_b}
    common = sorted(set(map_a) & set(map_b))
    if not common:
        return {"common_ids": 0}
    by_episode: Dict[str, List[str]] = defaultdict(list)
    for qid in common:
        by_episode[map_a[qid]["task_name"]].append(qid)
    episodes = sorted(by_episode)

    def delta(rows: Sequence[str]) -> Dict[str, float]:
        rows_a = [map_a[qid] for qid in rows]
        rows_b = [map_b[qid] for qid in rows]
        block_a, block_b = metric_block(rows_a), metric_block(rows_b)
        return {
            "EM": block_a["EM"] - block_b["EM"],
            "TA": block_a["TA"] - block_b["TA"],
            "PA_item_mean": block_a["PA_item_mean"] - block_b["PA_item_mean"],
            "PA_transition_micro": block_a["PA_transition_micro"] - block_b["PA_transition_micro"],
        }

    point = delta(common)
    rng = random.Random(seed)
    samples: Dict[str, List[float]] = {key: [] for key in METRIC_KEYS}
    for _ in range(resamples):
        drawn = [episodes[rng.randrange(len(episodes))] for _ in range(len(episodes))]
        rows = [qid for episode in drawn for qid in by_episode[episode]]
        block = delta(rows)
        for key in METRIC_KEYS:
            samples[key].append(block[key])
    result: Dict[str, Any] = {"common_ids": len(common), "episodes": len(episodes),
                              "resamples": resamples, "unit": "episode"}
    for key in METRIC_KEYS:
        values = sorted(samples[key])
        result[key] = {
            "point": round(point[key], 4),
            "ci_low": round(percentile(values, fraction_low), 4),
            "ci_high": round(percentile(values, fraction_high), 4),
        }
    return result


def paired_counts(items_a: Sequence[Dict[str, Any]], items_b: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    map_a = {item["id"]: item for item in items_a}
    map_b = {item["id"]: item for item in items_b}
    common = sorted(set(map_a) & set(map_b))
    counts = Counter()
    for qid in common:
        correct_a = float(map_a[qid]["exact_match"]) == 1.0
        correct_b = float(map_b[qid]["exact_match"]) == 1.0
        counts["both_correct" if correct_a and correct_b else
               "both_wrong" if not correct_a and not correct_b else
               "only_first" if correct_a else "only_second"] += 1
    return {"common_ids": len(common), **{key: counts[key] for key in
                                          ("both_correct", "both_wrong", "only_first", "only_second")}}


# ------------------------------------------------------------------- load data
def load_condition(run_dir: Path, name: str, relative: str) -> Dict[str, Any]:
    condition_dir = run_dir / relative
    items_path = condition_dir / "report.items.jsonl"
    if not items_path.exists():
        raise FileNotFoundError(f"condition {name}: missing {items_path}")
    items = load_jsonl(items_path)
    ids = [item["id"] for item in items]
    duplicate_ids = sorted({qid for qid, count in Counter(ids).items() if count > 1})
    if duplicate_ids:
        raise ValueError(f"condition {name}: duplicate item IDs {duplicate_ids[:3]}")
    report = load_json(items_path.with_name("report.items.jsonl").parent / "report.json") or {}
    run_status = load_json(condition_dir / "run_status.json")
    run_config = load_json(condition_dir / "run_config.json")
    return {
        "name": name,
        "relative_dir": relative,
        "items": items,
        "report": report,
        "run_status": run_status,
        "run_config": run_config,
        "provenance": {
            "items_sha256": sha256_file(items_path),
            "report_sha256": sha256_file(items_path.parent / "report.json")
            if (items_path.parent / "report.json").exists() else None,
            "items_path": str(items_path.relative_to(ROOT)) if items_path.is_relative_to(ROOT) else str(items_path),
            "qa_sha256": (run_config or {}).get("qa_sha256"),
            "model_requested": (run_config or {}).get("model_requested"),
        },
    }


def load_task_text(data_root: Path) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    annotation_dir = data_root / "annotations" / "episodes"
    for path in sorted(annotation_dir.glob("*.json")):
        try:
            annotation = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        episode_key = annotation.get("episode_key") or path.stem
        mapping[episode_key] = annotation.get("task_text") or "unknown"
    return mapping


def text_solvable_map(prior_path: Path, gt_lookup: Dict[str, Any]) -> Dict[str, bool]:
    """Which questions a text-only prior already answers correctly.

    v0.2's inverse questions are 60/60 solvable from the shuffled action text alone, so a
    model's inverse score carries no visual evidence unless it is reported next to this
    split.  ``solvable`` means the text prior's answer equals gt; anything the prior gets
    wrong needs more than text, which is where a visual gain would have to show up.
    """
    rows = [json.loads(line) for line in prior_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    solvable: Dict[str, bool] = {}
    for row in rows:
        qid = row.get("id")
        if qid is None or qid not in gt_lookup:
            continue
        answer = row.get("answer")
        solvable[qid] = bool(isinstance(answer, list) and answer == gt_lookup[qid])
    return solvable


def condition_tables(condition: Dict[str, Any], task_text: Dict[str, str],
                     resamples: int, seed: int,
                     solvable: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
    items = condition["items"]
    tables: Dict[str, Any] = {
        "overall": metric_block(items),
        "by_direction": {key: metric_block(rows) for key, rows in group_items(items, direction_of).items()},
        "by_setting": {key: metric_block(rows) for key, rows in group_items(items, setting_of).items()},
        "by_episode": {key: metric_block(rows) for key, rows in group_items(items, lambda item: item["task_name"]).items()},
        "by_task": {key: metric_block(rows) for key, rows in group_items(
            items, lambda item: task_text.get(item["task_name"], "unknown")).items()},
    }
    if solvable:
        def solvable_group(item: Dict[str, Any]) -> str:
            flag = solvable.get(item["id"])
            if flag is None:
                return "unlabelled"
            return "text_solvable" if flag else "text_not_solvable"

        tables["by_text_solvable"] = {
            key: metric_block(rows) for key, rows in group_items(items, solvable_group).items()
        }
    base_seed = stable_seed(seed, f"{condition['name']}:bootstrap")
    bootstrap: Dict[str, Any] = {"overall": cluster_bootstrap(items, resamples, base_seed)}
    bootstrap["by_direction"] = {
        key: cluster_bootstrap(rows, resamples, stable_seed(base_seed, f"direction:{key}"))
        for key, rows in group_items(items, direction_of).items()
    }
    bootstrap["by_setting"] = {
        key: cluster_bootstrap(rows, resamples, stable_seed(base_seed, f"setting:{key}"))
        for key, rows in group_items(items, setting_of).items()
    }
    bootstrap["by_episode"] = {
        key: cluster_bootstrap(rows, resamples, stable_seed(base_seed, f"episode:{key}"))
        for key, rows in group_items(items, lambda item: item["task_name"]).items()
    }
    if solvable:
        bootstrap["by_text_solvable"] = {
            key: cluster_bootstrap(rows, resamples, stable_seed(base_seed, f"solvable:{key}"))
            for key, rows in group_items(items, solvable_group).items()
        }
    tables["bootstrap"] = bootstrap

    report = condition["report"]
    run_status = condition["run_status"] or {}
    overall = report.get("overall", {})
    report_items_consistent = bool(overall) and (
        overall.get("count") == len(items)
        and overall.get("invalid_or_missing") == tables["overall"]["invalid_or_missing"]
        and abs(float(overall.get("EM", -1)) - tables["overall"]["EM"]) < 1e-9
        and abs(float(overall.get("TA", -1)) - tables["overall"]["TA"]) < 1e-9
    )
    tables["failure_stats"] = {
        "report_total_questions": report.get("total_questions"),
        "report_answered": report.get("answered"),
        "items_count": len(items),
        "valid_permutations": tables["overall"]["valid_permutations"],
        "invalid_or_missing": tables["overall"]["invalid_or_missing"],
        "invalid_reasons": tables["overall"]["invalid_reasons"],
        "run_status": {key: run_status.get(key) for key in
                       ("state", "planned", "answered", "success", "truncated", "invalid", "failed", "missing")},
        "report_items_consistent": report_items_consistent,
    }
    return tables


# ------------------------------------------------------------------- reporting
def markdown_table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> List[str]:
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return lines


def format_metric(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def build_markdown(result: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# ENACT-USIM 评分统计（direction×L、episode bootstrap、A/B/C 配对）")
    lines.append("")
    lines.append(f"- 运行目录：`{result['run']['run_dir']}`")
    lines.append(f"- 数据集：`{result['inputs']['data_root']}`")
    lines.append(f"- bootstrap：按 episode 重采样 {result['settings']['bootstrap_resamples']} 次，"
                 f"seed={result['settings']['bootstrap_seed']}，分位 {result['settings']['ci']}")
    lines.append("- 指标来自各条件 `report.items.jsonl`（未重新评分）；EM/TA/PA 见脚注。")
    lines.append("")

    lines.append("## 1. 条件总览")
    lines.append("")
    headers = ["条件", "N", "episodes", "有效排列", "invalid/missing", "EM", "TA", "PA_item", "PA_micro"]
    rows = []
    for name, condition in result["conditions"].items():
        overall = condition["tables"]["overall"]
        rows.append([name, overall["count"], overall["episodes"], overall["valid_permutations"],
                     overall["invalid_or_missing"], format_metric(overall["EM"]), format_metric(overall["TA"]),
                     format_metric(overall["PA_item_mean"]), format_metric(overall["PA_transition_micro"])])
    lines.extend(markdown_table(headers, rows))
    lines.append("")

    lines.append("## 2. direction×L（各条件 EM）")
    lines.append("")
    settings = sorted({setting for condition in result["conditions"].values()
                       for setting in condition["tables"]["by_setting"]})
    headers = ["setting", "N"] + [f"{name} EM" for name in result["conditions"]] + \
              [f"{name} PA_micro" for name in result["conditions"]]
    rows = []
    for setting in settings:
        row: List[Any] = [setting, result["conditions"][next(iter(result["conditions"]))]["tables"][
            "by_setting"].get(setting, {}).get("count", 0)]
        for name, condition in result["conditions"].items():
            row.append(format_metric(condition["tables"]["by_setting"].get(setting, {}).get("EM", "")))
        for name, condition in result["conditions"].items():
            row.append(format_metric(condition["tables"]["by_setting"].get(setting, {}).get("PA_transition_micro", "")))
        rows.append(row)
    lines.extend(markdown_table(headers, rows))
    lines.append("")

    lines.append("## 3. episode 分组（EM）")
    lines.append("")
    lines.append("> 单个 episode 的 bootstrap 分位恒等于其点估计（重采样单位就是该 episode），"
                 "因此这里不展示逐 episode 的 CI；不确定性看第 4 节总体/direction×L 的 episode bootstrap。")
    lines.append("")
    headers = ["episode", "任务文本"]
    for name in result["conditions"]:
        headers.append(f"{name} EM")
    episodes = sorted({episode for condition in result["conditions"].values()
                       for episode in condition["tables"]["by_episode"]})
    rows = []
    for episode in episodes:
        row: List[Any] = [episode, result["episode_task_text"].get(episode, "-")]
        for name, condition in result["conditions"].items():
            table = condition["tables"]["by_episode"].get(episode)
            row.append(f"{format_metric(table['EM'])} (n={table['count']})" if table else "-")
        rows.append(row)
    lines.extend(markdown_table(headers, rows))
    lines.append("")

    lines.append("## 3b. 任务分组（EM / PA_micro）")
    lines.append("")
    headers = ["任务文本", "N"] + [f"{name} EM" for name in result["conditions"]] + \
              [f"{name} PA_micro" for name in result["conditions"]]
    tasks = sorted({task for condition in result["conditions"].values()
                    for task in condition["tables"]["by_task"]})
    rows = []
    for task in tasks:
        count = next((condition["tables"]["by_task"][task]["count"]
                      for condition in result["conditions"].values()
                      if task in condition["tables"]["by_task"]), 0)
        row = [task, count]
        for condition in result["conditions"].values():
            row.append(format_metric(condition["tables"]["by_task"].get(task, {}).get("EM", "")))
        for condition in result["conditions"].values():
            row.append(format_metric(condition["tables"]["by_task"].get(task, {}).get("PA_transition_micro", "")))
        rows.append(row)
    lines.extend(markdown_table(headers, rows))
    lines.append("")

    lines.append("## 4. episode bootstrap（总体与 direction×L，95% CI）")
    lines.append("")
    headers = ["条件", "范围", "episodes", "指标", "点估计", "CI low", "CI high"]
    rows = []
    for name, condition in result["conditions"].items():
        bootstrap = condition["tables"]["bootstrap"]
        for scope, block in [("overall", bootstrap["overall"])] + \
                [(f"setting:{key}", value) for key, value in bootstrap["by_setting"].items()] + \
                [(f"direction:{key}", value) for key, value in bootstrap["by_direction"].items()]:
            for metric in METRIC_KEYS:
                entry = block.get(metric) if isinstance(block, dict) else None
                if entry:
                    rows.append([name, scope, block.get("episodes", "-"), metric, format_metric(entry["point"]),
                                 f"{entry['ci_low']:.4f}", f"{entry['ci_high']:.4f}"])
    lines.extend(markdown_table(headers, rows))
    lines.append("")

    lines.append("## 5. A/B/C 同 ID 配对比较")
    lines.append("")
    headers = ["比较", "common", "both_correct", "both_wrong", "only_first", "only_second",
               "ΔEM [CI]", "ΔPA_item [CI]"]
    rows = []
    for pair_name, pair in result["paired"].items():
        counts = pair["counts"]
        delta_em = pair["bootstrap"]["EM"]
        delta_pa = pair["bootstrap"]["PA_item_mean"]
        rows.append([pair_name, counts["common_ids"], counts["both_correct"], counts["both_wrong"],
                     counts["only_first"], counts["only_second"],
                     f"{delta_em['point']:+.4f} [{delta_em['ci_low']:+.4f}, {delta_em['ci_high']:+.4f}]",
                     f"{delta_pa['point']:+.4f} [{delta_pa['ci_low']:+.4f}, {delta_pa['ci_high']:+.4f}]"])
    lines.extend(markdown_table(headers, rows))
    lines.append("")

    if any("by_text_solvable" in condition["tables"] for condition in result["conditions"].values()):
        lines.append("## 5a. 程序文本基线分层（基线答对 / 基线答错）")
        lines.append("")
        lines.append("分层依据是程序化文本基线（`text_prior_baseline`）在**不看图**时是否答对同一题。"
                     "「基线答对」层的模型得分**不构成视觉证据**——这些题只看打乱后的动作文本就能答对；"
                     "视觉证据只能看「基线答错」层以及 A−C / A−D 的配对差值。")
        lines.append("")
        headers = ["条件", "分层", "N", "episodes", "EM", "PA_item", "PA_micro"]
        label = {"text_solvable": "基线答对", "text_not_solvable": "基线答错", "unlabelled": "未标注"}
        rows = []
        for name, condition in result["conditions"].items():
            for group in ("text_solvable", "text_not_solvable", "unlabelled"):
                block = condition["tables"]["by_text_solvable"].get(group)
                if not block:
                    continue
                rows.append([name, label[group], block.get("count", ""), block.get("episodes", ""),
                             format_metric(block.get("EM", "")),
                             format_metric(block.get("PA_item_mean", "")),
                             format_metric(block.get("PA_transition_micro", ""))])
        lines.extend(markdown_table(headers, rows))
        lines.append("")

    lines.append("## 5b. 配对比较 × direction×L（ΔEM = first − second，episode bootstrap 95% CI）")
    lines.append("")
    headers = ["比较", "setting", "common", "first_only", "second_only", "ΔEM [CI]"]
    rows = []
    for pair_name, pair in result["paired"].items():
        for setting, block in pair["by_setting"].items():
            counts = block["counts"]
            delta = block["bootstrap"].get("EM")
            if not delta:
                continue
            rows.append([pair_name, setting, counts["common_ids"], counts["only_first"],
                         counts["only_second"],
                         f"{delta['point']:+.4f} [{delta['ci_low']:+.4f}, {delta['ci_high']:+.4f}]"])
    lines.extend(markdown_table(headers, rows))
    lines.append("")

    lines.append("## 6. 失败 / 格式错误 / identity 统计")
    lines.append("")
    headers = ["条件", "answered", "invalid/missing", "invalid_reasons", "run_state",
               "identity answer rate", "identity reference rate"]
    rows = []
    for name, condition in result["conditions"].items():
        failure = condition["tables"]["failure_stats"]
        overall = condition["tables"]["overall"]
        rows.append([name, failure["report_answered"], failure["invalid_or_missing"],
                     failure["invalid_reasons"] or "{}", failure["run_status"].get("state"),
                     format_metric(overall["identity_answer_rate"]),
                     format_metric(overall["identity_reference_rate"])])
    lines.extend(markdown_table(headers, rows))
    lines.append("")

    lines.append("## 7. 口径说明")
    lines.append("")
    lines.append("- EM = 严格解析后与参考排列完全一致；TA = EM 或 verifier 语义接受；"
                 "PA_item_mean = 逐题 PA 均值；PA_transition_micro = 转移加权（固定分母 n_i=L_i−1）。")
    lines.append("- bootstrap 以 7 个 episode（`task_name`）为重采样单位；同一 episode 的所有题、两个方向同时进出，"
                 "因此 CI 反映的是 7 个数据簇的不确定性，不是 70 题独立同分布的不确定性。")
    lines.append("- direction×L 单元只有 0–7 个 episode 支撑，CI 更宽，仅作开发诊断。")
    lines.append("- 配对比较使用 A/B/C 三条件完全相同的冻结 ID；失败题不剔除（按 EM=0 计）。")
    lines.append("")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------ main
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_ROOT))
    parser.add_argument("--condition", action="append", default=[],
                        help="NAME=relative_dir under --run-dir; repeatable")
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT),
                        help="dataset root (annotation task_text grouping)")
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20261024)
    parser.add_argument("--ci", type=float, default=0.95)
    parser.add_argument("--out-json", default="")
    parser.add_argument("--out-md", default="")
    parser.add_argument("--text-prior", default="",
                        help="text_prior_predictions.jsonl；给了就出'文本可解/不可解'分层")
    parser.add_argument("--allow-subset", action="store_true",
                        help="允许某条件的题集是首个条件的真子集（例如条件 D 只有 forward 题）；"
                             "仍需成员⊆首条件、gt 与状态数在交集上一致，否则仍返回 2")
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"run dir not found: {run_dir}", file=sys.stderr)
        return 2

    if args.condition:
        conditions_spec = []
        for entry in args.condition:
            if "=" not in entry:
                print(f"bad --condition {entry!r}; expected NAME=relative_dir", file=sys.stderr)
                return 2
            name, relative = entry.split("=", 1)
            conditions_spec.append((name.strip(), relative.strip()))
    else:
        conditions_spec = [(child.name, child.name) for child in sorted(run_dir.iterdir())
                           if child.is_dir() and (child / "report.items.jsonl").exists()
                           and (child / "report.json").exists()]
        if not conditions_spec:
            print(f"no condition subdirectories with report.items.jsonl under {run_dir}", file=sys.stderr)
            return 2

    try:
        loaded = [load_condition(run_dir, name, relative) for name, relative in conditions_spec]
    except (FileNotFoundError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2

    task_text = load_task_text(Path(args.data_root))
    gt_lookup: Dict[str, Any] = {}
    for condition in loaded:
        for item in condition["items"]:
            gt_lookup.setdefault(item["id"], item["gt"])
    solvable: Dict[str, bool] = {}
    if args.text_prior:
        prior_path = Path(args.text_prior)
        if not prior_path.exists():
            print(f"text prior not found: {prior_path}", file=sys.stderr)
            return 2
        solvable = text_solvable_map(prior_path, gt_lookup)
    fraction_low = (1.0 - args.ci) / 2.0
    fraction_high = 1.0 - fraction_low
    conditions: Dict[str, Any] = {}
    for condition in loaded:
        tables = condition_tables(condition, task_text, args.bootstrap, args.seed, solvable or None)
        # Patch the CI fractions into every bootstrap block (kept explicit in evidence).
        tables["bootstrap"]["ci"] = args.ci
        conditions[condition["name"]] = {
            "relative_dir": condition["relative_dir"],
            "provenance": condition["provenance"],
            "run_status": condition["run_status"],
            "tables": tables,
        }

    # Cross-condition integrity: identical frozen IDs, same gt and same num_states.
    names = [condition["name"] for condition in loaded]
    by_name = {condition["name"]: condition for condition in loaded}
    id_sets = {name: {item["id"] for item in condition["items"]} for name, condition in by_name.items()}
    gt_by_condition = {name: {item["id"]: item["gt"] for item in condition["items"]}
                       for name, condition in by_name.items()}
    states_by_condition = {name: {item["id"]: item["num_states"] for item in condition["items"]}
                           for name, condition in by_name.items()}
    baseline_name = names[0]
    gt_conflicts = sorted({
        qid for name in names for qid in gt_by_condition[name]
        if qid in gt_by_condition[baseline_name]
        and gt_by_condition[name][qid] != gt_by_condition[baseline_name][qid]
    })
    num_states_conflicts = sorted({
        qid for name in names for qid in states_by_condition[name]
        if qid in states_by_condition[baseline_name]
        and states_by_condition[name][qid] != states_by_condition[baseline_name][qid]
    })
    outside_first = {name: sorted(id_sets[name] - id_sets[baseline_name]) for name in names}
    integrity: Dict[str, Any] = {
        "id_sets_equal": all(id_sets[name] == id_sets[baseline_name] for name in names),
        "id_set_sizes": {name: len(id_sets[name]) for name in names},
        "ids_outside_first": {name: len(values) for name, values in outside_first.items()},
        "declared_subset_ok": not any(outside_first.values()),
        "subset_declared_by_flag": bool(args.allow_subset),
        "gt_conflicts": gt_conflicts,
        "num_states_conflicts": num_states_conflicts,
        "baseline_condition": baseline_name,
    }

    pairs: Dict[str, Any] = {}
    for index, name_a in enumerate(names):
        for name_b in names[index + 1:]:
            pair_name = f"{name_a}_vs_{name_b}"
            items_a, items_b = by_name[name_a]["items"], by_name[name_b]["items"]
            pairs[pair_name] = {
                "first": name_a,
                "second": name_b,
                "counts": paired_counts(items_a, items_b),
                "bootstrap": paired_bootstrap(items_a, items_b, args.bootstrap,
                                              stable_seed(args.seed, f"pair:{pair_name}"),
                                              fraction_low, fraction_high),
                "by_setting": {},
            }
            setting_map_a = group_items(items_a, setting_of)
            setting_map_b = group_items(items_b, setting_of)
            for setting in sorted(set(setting_map_a) | set(setting_map_b)):
                rows_a = setting_map_a.get(setting, [])
                rows_b = setting_map_b.get(setting, [])
                pairs[pair_name]["by_setting"][setting] = {
                    "counts": paired_counts(rows_a, rows_b),
                    "bootstrap": paired_bootstrap(rows_a, rows_b, args.bootstrap,
                                                  stable_seed(args.seed, f"pair:{pair_name}:{setting}"),
                                                  fraction_low, fraction_high),
                }

    result: Dict[str, Any] = {
        "schema": "usim_report_stats/v1",
        "run": {"run_dir": str(run_dir), "run_name": run_dir.name,
                "conditions": names, "conditions_spec": args.condition or [f"{name}={name}" for name in names]},
        "episode_task_text": {episode: task_text.get(episode, "unknown")
                              for condition in loaded for episode in
                              {item["task_name"] for item in condition["items"]}},
        "inputs": {
            "data_root": str(Path(args.data_root)),
            "task_text_episodes": len(task_text),
            "conditions": {name: {"relative_dir": condition["relative_dir"],
                                  "items_sha256": condition["provenance"]["items_sha256"],
                                  "report_sha256": condition["provenance"]["report_sha256"],
                                  "qa_sha256": condition["provenance"]["qa_sha256"]}
                           for name, condition in zip(names, loaded)},
        },
        "settings": {
            "bootstrap_resamples": args.bootstrap,
            "bootstrap_seed": args.seed,
            "ci": args.ci,
            "bootstrap_unit": "episode (task_name), resampled with replacement; all questions/directions of an episode stay together",
            "metrics_source": "report.items.jsonl (exact_match / task_accuracy / pairwise_accuracy / num_transitions)",
            "rounding": 4,
        },
        "integrity": integrity,
        "conditions": conditions,
        "paired": pairs,
        "notes": [
            "7 episodes only: episode-level CIs are development diagnostics, not a claim of 70 independent trajectories.",
            "direction x L cells are supported by 0-7 episodes and are reported with the same episode bootstrap.",
            "paired comparisons use identical frozen IDs across A/B/C; invalid answers stay in the denominator as 0.",
        ],
    }

    out_json = Path(args.out_json) if args.out_json else DEFAULT_OUT_DIR / f"report_stats_{run_dir.name}.json"
    out_md = Path(args.out_md) if args.out_md else out_json.with_suffix(".md")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    out_md.write_text(build_markdown(result), encoding="utf-8")

    summary = {
        "run": str(run_dir),
        "conditions": {
            name: {key: condition["tables"]["overall"][key] for key in
                   ("count", "EM", "TA", "PA_item_mean", "PA_transition_micro", "invalid_or_missing",
                    "identity_answer_rate")}
            for name, condition in conditions.items()
        },
        "bootstrap_overall_EM": {
            name: condition["tables"]["bootstrap"]["overall"]["EM"]
            for name, condition in conditions.items()
        },
        "paired": {pair_name: pair["counts"] for pair_name, pair in pairs.items()},
        "integrity": integrity,
        "outputs": {"json": str(out_json), "markdown": str(out_md)},
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    ids_contract_ok = integrity["id_sets_equal"] or (
        args.allow_subset and integrity["declared_subset_ok"])
    return 0 if ids_contract_ok and not integrity["gt_conflicts"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
