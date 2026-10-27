"""Generate and verify a protocol-freeze manifest for a frozen ENACT-USIM dataset.

The manifest records the SHA-256 of everything that defines a benchmark result so
that a later run can prove it used the *same* protocol:

* **labels** - episode annotations, raw and segmented scene graphs;
* **QA** - frozen QA JSONL, build summaries, run input lists (preflight/smoke/full_dev);
* **images** - every QA image (A and B condition) and every replayed/segmented frame;
* **prompt** - prompt policy, system prompt (null for option A) and the exact format directive;
* **model / decoding** - model name, temperature, enable_thinking, max_completion_tokens, ...;
* **scoring** - ``evaluate.py`` hash, protocol name, parser semantics and known gaps;
* **split / seed** - split generator hash, split seed and split manifest;
* **code** - hashes of the adapters/evaluator/generators that implement the protocol;
* **run artifacts** - per-condition config, predictions, reports and raw attempt logs.

A ``manifest_payload_sha256`` over the canonical JSON of the manifest makes
tampering or post-hoc editing detectable.  ``--verify`` re-hashes every recorded
file, re-scans the recorded glob patterns for added/removed files and reports a
non-zero exit code on any drift, so it can be used as a CI/checklist gate.

Usage:
    python -m scripts.usim.freeze_protocol
    python -m scripts.usim.freeze_protocol --freeze-id 20261027
    python -m scripts.usim.freeze_protocol --verify data/usim_enact/_protocol/freeze_usim-enact-v0.1_20261027.json
    python -m scripts.usim.freeze_protocol --self-test

    # v0.2 protocol freeze (after audit -> condition D -> splits exist):
    python -m scripts.usim.freeze_protocol --data-root data/usim_enact/usim-enact-v0.2 \
        --curated-qa data/usim_enact/usim-enact-v0.2/QA/train/enact_ordering_curated.jsonl \
        --split-inputs-dir data/usim_enact/runs/qwen3.8-max/v02_dev_001/inputs \
        --condition-d-qa data/usim_enact/_protocol/conditions/D_no_action_text_v0.2/enact_ordering.jsonl \
        --model-config data/usim_enact/runs/qwen3.8-max/v02_dev_001/run_config.json \
        --freeze-id 20261027
    python -m scripts.usim.freeze_protocol --template            # write the v0.2 field template
    python -m scripts.usim.freeze_protocol --self-test-v02       # exercise the v0.2 profile on a mock fixture
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enact.adapters.usim_annotations import PROTOCOL_VERSION  # noqa: E402
from scripts.usim.evaluate import EVALUATION_PROTOCOL  # noqa: E402

DEFAULT_DATA_ROOT = ROOT / "data" / "usim_enact" / PROTOCOL_VERSION
DEFAULT_RUN_DIR = ROOT / "data" / "usim_enact" / "runs" / "qwen3.8-max" / "dev_ego_thinking_false_001"
DEFAULT_OUT_DIR = ROOT / "data" / "usim_enact" / "_protocol"
DEFAULT_CONDITIONS = ("full_v1", "condB_zoom", "condC_text_only")
TZ_SHANGHAI = timezone(timedelta(hours=8))
SCHEMA = "usim-protocol-freeze/v1"
MODEL_PARAM_KEYS = ("model_requested", "enable_thinking", "temperature", "max_completion_tokens",
                    "stream", "timeout_seconds", "max_attempts", "api_url", "backend",
                    "prompt_policy", "system_prompt", "format_directive")

PROTOCOL_NOTES = {
    "qa_unit": "one question = one current state + (L-1) shuffled future states (forward) "
               "or L chronological images + (L-1) shuffled action labels (inverse)",
    "answer_format": "single Python list of integers, a permutation of 1..L-1, strict whole-string parse",
    "fixed_denominator": "every frozen question contributes n_i = L_i - 1 transitions to PA_transition_micro",
    "verifier": "enact.core.evaluators.TaskWiseOrderingVerifier with USIM state vocabulary",
    "scoring_parser_version": "strict_permutation_v1",
    "seed_policy": "split seed 20261024; episode bootstrap seed 20261024 (development diagnostics)",
}
KNOWN_LIMITATIONS = [
    "usim_strict_v0.3 (current scorer) rejects empty visible reference transitions in "
    "USIMEvaluator.precheck (AssetError, non-zero exit, no report); the frozen v0.1 run "
    "artifacts were produced/scored under usim_strict_v0.2, and a v0.3 re-score reproduces the "
    "archival EM/TA/PA values exactly (data/usim_enact/_protocol/contract/regression_v0.1/)",
    "v0.1 QA contains 0 multi-answer questions, so TA is numerically equal to EM and the "
    "multi-answer path is exercised only by synthetic contract fixtures, not by the frozen set",
    "v0.1 has 7 episodes / 70 questions; episode-grouped statistics are development diagnostics only",
    "full_v1/run_config.json predates the image_condition field; the condition can be cross-checked "
    "from input_manifest image tokens but is not a recorded config key",
    "current code hashes drift from the v0.1 run_config records for run_inference.py, evaluate.py, "
    "build_qa.py, build_dataset.py and usim_translator.py; the drift is recorded per condition in "
    "generation_checks.code_drift (evaluate.py drift is the approved usim_strict_v0.3 gate, the "
    "generator/translator drift is concurrent v0.2 migration work). The v0.3 re-score of the frozen "
    "v0.1 predictions with the current code reproduces the archival values exactly "
    "(data/usim_enact/_protocol/contract/regression_v0.1/)",
]

CODE_FILES = (
    "scripts/usim/evaluate.py",
    "scripts/usim/run_inference.py",
    "scripts/usim/build_qa.py",
    "scripts/usim/build_dataset.py",
    "scripts/usim/reseed_answers.py",
    "scripts/usim/build_crops.py",
    "scripts/usim/make_splits.py",
    "enact/core/evaluators.py",
    "enact/adapters/__init__.py",
    "enact/adapters/usim_annotations.py",
    "enact/adapters/usim_reader.py",
    "enact/adapters/usim_scene_graph.py",
    "enact/adapters/usim_translator.py",
    "enact/adapters/usim_visibility.py",
    "enact/adapters/usim_visual_prompt.py",
    "enact/utils/state_change_translator.py",
    "enact/utils/scene_graph_utils.py",
    "enact/utils/qa_gen_utils.py",
)


# --------------------------------------------------------------------- hashing
def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_bytes(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def group_digest(files: Dict[str, str]) -> str:
    lines = [f"{relative}\t{digest}" for relative, digest in sorted(files.items())]
    return sha256_text("\n".join(lines))


def now_iso() -> str:
    return datetime.now(TZ_SHANGHAI).isoformat(timespec="seconds")


def relative_to_root(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def expand_paths(patterns: Sequence[str], paths: Sequence[str], base: Path) -> List[Path]:
    found: List[Path] = []
    for pattern in patterns:
        found.extend(sorted(candidate for candidate in base.glob(pattern) if candidate.is_file()))
    for relative in paths:
        candidate = base / relative
        if candidate.is_file():
            found.append(candidate)
    return sorted(set(found))


def build_group(patterns: Sequence[str] = (), paths: Sequence[str] = (), base: Optional[Path] = None) -> Dict[str, Any]:
    base = base or ROOT
    found = expand_paths(patterns, paths, base)
    files = {relative_to_root(path): sha256_file(path) for path in found}
    return {
        "patterns": list(patterns),
        "paths": list(paths),
        "files": dict(sorted(files.items())),
        "count": len(files),
        "digest": group_digest(files),
    }


# -------------------------------------------------------------------- manifest
def data_relative(data_root: Path) -> str:
    return relative_to_root(data_root)


def build_manifest(data_root: Path, run_dir: Path, conditions: Sequence[str],
                   freeze_id: str = "") -> Dict[str, Any]:
    data_rel = data_relative(data_root)
    inputs_dir = run_dir / "inputs"
    inputs_rel = relative_to_root(inputs_dir)
    run_rel = relative_to_root(run_dir)
    manifest_path = data_root / "manifest.json"
    dataset_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    dataset_version = dataset_manifest.get("protocol_version", PROTOCOL_VERSION)

    groups: Dict[str, Any] = {
        "dataset_manifest": build_group(paths=[f"{data_rel}/manifest.json"]),
        "labels": build_group(patterns=[
            f"{data_rel}/annotations/episodes/*.json",
            f"{data_rel}/replayed_activities/*/scene_graph_0.json",
            f"{data_rel}/segmented_activities/*/segmented_scene_graph_0.json",
        ]),
        "images": build_group(patterns=[
            f"{data_rel}/replayed_activities/*/external_sensor1/*.png",
            f"{data_rel}/segmented_activities/*/external_sensor1/*.png",
            f"{data_rel}/QA/images/**/*.png",
            f"{data_rel}/QA/conditions/**/images/**/*.png",
        ]),
        "qa": build_group(patterns=[
            f"{data_rel}/QA/**/*.jsonl",
            f"{data_rel}/QA/**/build_summary.json",
            f"{data_rel}/QA/**/build_manifest.json",
        ]),
        "run_inputs": build_group(patterns=[f"{inputs_rel}/*.jsonl", f"{inputs_rel}/*.json"]),
        "run_artifacts": build_group(patterns=[
            f"{run_rel}/{condition}/*.jsonl" for condition in conditions
        ] + [
            f"{run_rel}/{condition}/*.json" for condition in conditions
        ]),
        "code": build_group(paths=[relative for relative in CODE_FILES if (ROOT / relative).exists()]),
    }

    # ---- run configuration / model / prompt
    condition_configs: Dict[str, Any] = {}
    predictions_model_fields: Dict[str, Any] = {}
    run_statuses: Dict[str, Any] = {}
    run_report_protocols: Dict[str, Any] = {}
    cross_checks: Dict[str, Any] = {}

    def qa_file_from_config(config: Dict[str, Any]) -> Optional[Path]:
        raw = config.get("qa_path") or ""
        if not raw:
            return None
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        return candidate if candidate.exists() else None

    for condition in conditions:
        condition_dir = run_dir / condition
        config = json.loads((condition_dir / "run_config.json").read_text(encoding="utf-8")) \
            if (condition_dir / "run_config.json").exists() else {}
        condition_configs[condition] = {key: config.get(key) for key in MODEL_PARAM_KEYS}
        input_manifest_path = condition_dir / "input_manifest.json"
        if input_manifest_path.exists():
            input_manifest = json.loads(input_manifest_path.read_text(encoding="utf-8"))
            recomputed_image_hash = sha256_text(json.dumps(input_manifest.get("records", []),
                                                           sort_keys=True, ensure_ascii=False))
            input_manifest_sha = sha256_file(input_manifest_path)
            qa_sha = input_manifest.get("qa_sha256")
        else:
            recomputed_image_hash, input_manifest_sha, qa_sha = None, None, None
        qa_file = qa_file_from_config(config)
        predictions_path = condition_dir / "predictions.jsonl"
        models: List[str] = []
        returned_models: List[str] = []
        if predictions_path.exists():
            for line in predictions_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("model"):
                    models.append(str(row["model"]))
                if row.get("model_returned"):
                    returned_models.append(str(row["model_returned"]))
        predictions_model_fields[condition] = {
            "model": sorted(set(models)), "model_returned": sorted(set(returned_models)),
            "rows": len(models),
        }
        run_status_path = condition_dir / "run_status.json"
        if run_status_path.exists():
            run_statuses[condition] = json.loads(run_status_path.read_text(encoding="utf-8"))
        report_path = condition_dir / "report.json"
        if report_path.exists():
            run_report = json.loads(report_path.read_text(encoding="utf-8"))
            run_report_protocols[condition] = {
                "evaluation_protocol": run_report.get("evaluation_protocol"),
                "report_sha256": sha256_file(report_path),
                "total_questions": run_report.get("total_questions"),
                "overall": run_report.get("overall"),
            }
        checks = {
            "qa_sha_matches_input_file": bool(qa_sha and qa_file and sha256_file(qa_file) == qa_sha),
            "image_manifest_sha_recomputed": bool(recomputed_image_hash and
                                                 recomputed_image_hash == config.get("image_manifest_sha256")),
            "input_manifest_sha": input_manifest_sha,
            "format_directive_sha_recomputed": bool(config.get("format_directive") is not None
                                                    and sha256_text(config["format_directive"]) ==
                                                    config.get("format_directive_sha256")),
            "run_status_state": (run_statuses.get(condition) or {}).get("state"),
            "run_status_counts": {key: (run_statuses.get(condition) or {}).get(key) for key in
                                  ("planned", "answered", "success", "truncated", "invalid", "failed", "missing")},
            "code_matches_run_config": {},
        }
        recorded_code = config.get("code_sha256") or {}
        for relative, recorded in sorted(recorded_code.items()):
            normalized = relative.replace("\\", "/")
            current = sha256_file(ROOT / normalized) if (ROOT / normalized).exists() else None
            checks["code_matches_run_config"][normalized] = {
                "recorded": recorded, "current": current, "match": current == recorded,
                "recorded_path": relative,
            }
        cross_checks[f"condition:{condition}"] = checks

    # ---- dataset manifest internal hash checks
    annotation_hashes = dataset_manifest.get("annotation_sha256", {})
    annotation_paths = {relative: digest for relative, digest in groups["labels"]["files"].items()
                        if "/annotations/episodes/" in relative}
    annotation_check = {
        name: {
            "expected": digest,
            "actual": annotation_paths.get(f"{data_rel}/annotations/episodes/{name}"),
            "match": annotation_paths.get(f"{data_rel}/annotations/episodes/{name}") == digest,
        }
        for name, digest in sorted(annotation_hashes.items())
    }
    frame_checks: List[Dict[str, Any]] = []
    image_files = groups["images"]["files"]
    for episode in dataset_manifest.get("episodes", []):
        for frame_group in ("frames", "segmented_frames"):
            for frame_id, frame in sorted((episode.get(frame_group) or {}).items()):
                frame_path = str(frame["path"]).replace("\\", "/")
                relative = f"{data_rel}/{frame_path}"
                actual = image_files.get(relative)
                frame_checks.append({
                    "episode": episode["episode_key"],
                    "group": frame_group,
                    "frame": frame_id,
                    "path": relative,
                    "expected": frame.get("sha256"),
                    "actual": actual,
                    "match": actual == frame.get("sha256"),
                })
    cross_checks["dataset_manifest_annotations"] = annotation_check
    cross_checks["dataset_manifest_frames"] = {
        "checked": len(frame_checks), "mismatches": [row for row in frame_checks if not row["match"]],
    }
    cross_checks["dataset_manifest_sha"] = {
        "expected": sha256_file(manifest_path) if manifest_path.exists() else None,
        "recorded": dataset_manifest.get("manifest_sha256"),
    }

    # ---- split manifest checks
    splits_path = inputs_dir / "splits_manifest.json"
    split_block: Dict[str, Any] = {"path": relative_to_root(splits_path) if splits_path.exists() else None}
    source_qa_path = data_root / "QA" / "train" / "enact_ordering.jsonl"
    if splits_path.exists():
        splits = json.loads(splits_path.read_text(encoding="utf-8"))
        split_block.update({
            "sha256": sha256_file(splits_path),
            "seed": splits.get("seed"),
            "source_qa": splits.get("source_qa"),
            "source_qa_sha256": splits.get("source_qa_sha256"),
            "smoke_per_group": splits.get("smoke_per_group"),
            "file_sha256": splits.get("sha256", {}),
            "counts": {key: (splits.get(key) or {}).get("count") for key in ("preflight", "smoke", "full_dev")},
            "by_setting": {key: (splits.get(key) or {}).get("by_setting") for key in ("preflight", "smoke", "full_dev")},
        })
        source_qa_sha = sha256_file(source_qa_path) if source_qa_path.exists() else None
        split_block["checks"] = {
            "source_qa_sha_matches": source_qa_sha == splits.get("source_qa_sha256"),
            "seed_is_20261024": splits.get("seed") == 20261024,
            "file_hashes_match": {
                name: (inputs_dir / name).exists() and sha256_file(inputs_dir / name) == digest
                for name, digest in sorted((splits.get("sha256") or {}).items())
            },
        }
        # input id/content checks against the frozen source QA
        source_records = [json.loads(line) for line in source_qa_path.read_text(encoding="utf-8").splitlines()
                          if line.strip()] if source_qa_path.exists() else []
        source_by_id = {record["id"]: record for record in source_records}
        input_checks: Dict[str, Any] = {}
        for name in ("preflight", "smoke", "full_dev"):
            path = inputs_dir / f"{name}.jsonl"
            if not path.exists():
                input_checks[name] = {"exists": False}
                continue
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            ids = [row["id"] for row in rows]
            input_checks[name] = {
                "exists": True,
                "rows": len(rows),
                "unique_ids": len(set(ids)) == len(ids),
                "ids_subset_of_source": set(ids).issubset(set(source_by_id)),
                "records_equal_source": all(source_by_id.get(row["id"]) == row for row in rows),
            }
        input_checks["full_dev_covers_source_qa"] = (
            {row["id"] for row in
             [json.loads(line) for line in (inputs_dir / "full_dev.jsonl").read_text(encoding="utf-8").splitlines()
              if line.strip()]} == set(source_by_id)
            if (inputs_dir / "full_dev.jsonl").exists() else False)
        split_block["input_checks"] = input_checks
        if split_block["checks"]["file_hashes_match"]:
            split_block["checks"]["file_hashes_match"] = all(split_block["checks"]["file_hashes_match"].values())
    else:
        split_block["checks"] = {"splits_manifest_missing": True}

    # ---- prompt block (all conditions must agree on the prompt directive)
    prompt_conditions = {condition: {"system_prompt": config.get("system_prompt"),
                                     "format_directive": config.get("format_directive"),
                                     "prompt_policy": config.get("prompt_policy")}
                         for condition, config in condition_configs.items()}
    prompt_values = {json.dumps(value, sort_keys=True, ensure_ascii=False)
                     for value in prompt_conditions.values()}
    primary_config = condition_configs.get(conditions[0], {}) if conditions else {}
    prompt_block = {
        "policy": primary_config.get("prompt_policy"),
        "system_prompt": primary_config.get("system_prompt"),
        "format_directive": primary_config.get("format_directive"),
        "format_directive_sha256": sha256_text(primary_config["format_directive"])
        if primary_config.get("format_directive") is not None else None,
        "per_condition": prompt_conditions,
        "conditions_agree": len(prompt_values) <= 1,
    }

    # ---- model block
    def distinct(key: str) -> List[Any]:
        values: List[Any] = []
        for config in condition_configs.values():
            value = config.get(key)
            if value not in values:
                values.append(value)
        return values

    model_block = {
        "model_requested": distinct("model_requested"),
        "model_returned": {condition: fields["model_returned"]
                           for condition, fields in predictions_model_fields.items()},
        "model_field": {condition: fields["model"] for condition, fields in predictions_model_fields.items()},
        "temperature": distinct("temperature"),
        "enable_thinking": distinct("enable_thinking"),
        "max_completion_tokens": distinct("max_completion_tokens"),
        "stream": distinct("stream"),
        "timeout_seconds": distinct("timeout_seconds"),
        "max_attempts": distinct("max_attempts"),
        "api_url": distinct("api_url"),
        "backend": distinct("backend"),
        "decode_params_consistent_across_conditions": all(
            len(distinct(key)) <= 1 for key in MODEL_PARAM_KEYS),
        "per_condition": condition_configs,
    }

    # ---- scoring block
    evaluate_rel = relative_to_root(ROOT / "scripts" / "usim" / "evaluate.py")
    scoring_block = {
        "evaluation_protocol": EVALUATION_PROTOCOL,
        "scorer": evaluate_rel,
        "scorer_sha256": sha256_file(ROOT / "scripts" / "usim" / "evaluate.py"),
        "verifier": PROTOCOL_NOTES["verifier"],
        "parser_version": PROTOCOL_NOTES["scoring_parser_version"],
        "metrics": ["EM", "TA", "semantic_only", "PA_item_mean", "PA_transition_micro"],
        "fixed_denominator": True,
        "strict_parser": True,
        "asset_precheck_aborts": True,
        "reference_transition_gate": {
            "enforced_in_precheck": True,
            "empty_visible_signature_policy": "AssetError, non-zero exit, no report",
            "introduced_in": "usim_strict_v0.3",
        },
        "scorer_entrypoint": "scripts/usim/evaluate.py USIMEvaluator",
        "protocol_history": {
            "usim_strict_v0.2": "fixed denominator, strict parser, asset precheck; does not reject "
                                "empty visible reference signatures",
            "usim_strict_v0.3": "adds the reference-transition gate; EM/TA/PA formulas unchanged",
        },
        "run_artifact_evaluation_protocols": run_report_protocols,
        "known_gaps": [KNOWN_LIMITATIONS[1]],
    }

    # ---- code drift (per condition: run_config recorded different code hashes across runs)
    recorded_by_condition: Dict[str, Dict[str, str]] = {}
    for condition, checks in cross_checks.items():
        if condition.startswith("condition:"):
            name = condition.split(":", 1)[1]
            recorded_by_condition[name] = {
                relative: entry["recorded"] for relative, entry in checks["code_matches_run_config"].items()
            }
    code_drift: Dict[str, Any] = {}
    all_code_files = set(groups["code"]["files"]) | {
        relative for mapping in recorded_by_condition.values() for relative in mapping
    }
    for relative in sorted(all_code_files):
        current = groups["code"]["files"].get(relative)
        per_condition = {name: mapping.get(relative) for name, mapping in recorded_by_condition.items()}
        matches = {name: (recorded is not None and recorded == current)
                   for name, recorded in per_condition.items()}
        code_drift[relative] = {
            "current": current,
            "recorded_by_condition": per_condition,
            "matches": matches,
            "drift_in_any_condition": any(recorded is not None and not matches[name]
                                          for name, recorded in per_condition.items()),
        }

    generation_checks = {
        "dataset_manifest_annotations_pass": all(entry["match"] for entry in annotation_check.values()),
        "dataset_manifest_frames_pass": not cross_checks["dataset_manifest_frames"]["mismatches"],
        "frames_checked": cross_checks["dataset_manifest_frames"]["checked"],
        "condition_checks": {
            condition: {
                "qa_sha_matches_input_file": checks["qa_sha_matches_input_file"],
                "image_manifest_sha_recomputed": checks["image_manifest_sha_recomputed"],
                "format_directive_sha_recomputed": checks["format_directive_sha_recomputed"],
                "run_completed": checks["run_status_state"] == "completed",
                "run_counts": checks["run_status_counts"],
            }
            for condition, checks in cross_checks.items() if condition.startswith("condition:")
        },
        "split_checks": split_block.get("checks"),
        "split_input_checks": split_block.get("input_checks"),
        "prompt_conditions_agree": prompt_block["conditions_agree"],
        "decode_params_consistent_across_conditions": model_block["decode_params_consistent_across_conditions"],
        "code_drift": {relative: entry for relative, entry in code_drift.items()
                       if entry["drift_in_any_condition"]},
    }
    hard = [
        generation_checks["dataset_manifest_annotations_pass"],
        generation_checks["dataset_manifest_frames_pass"],
        all(block["qa_sha_matches_input_file"] for block in generation_checks["condition_checks"].values()),
        all(block["image_manifest_sha_recomputed"] for block in generation_checks["condition_checks"].values()),
        all(block["format_directive_sha_recomputed"] for block in generation_checks["condition_checks"].values()),
        all(block["run_completed"] for block in generation_checks["condition_checks"].values()),
        bool(split_block.get("checks", {}).get("source_qa_sha_matches", False)),
        prompt_block["conditions_agree"],
    ]
    generation_checks["all_hard_checks_pass"] = all(hard)

    manifest: Dict[str, Any] = {
        "schema": SCHEMA,
        "freeze_id": freeze_id,
        "created_at": now_iso(),
        "root": str(ROOT.resolve()),
        "dataset": {
            "protocol_version": dataset_version,
            "data_root": data_rel,
            "manifest_sha256": sha256_file(manifest_path) if manifest_path.exists() else None,
            "counts": dataset_manifest.get("counts"),
            "episodes": [episode.get("episode_key") for episode in dataset_manifest.get("episodes", [])],
        },
        "prompt": prompt_block,
        "model": model_block,
        "scoring": scoring_block,
        "split": {"generator": "scripts/usim/make_splits.py",
                  "generator_sha256": sha256_file(ROOT / "scripts" / "usim" / "make_splits.py")
                  if (ROOT / "scripts" / "usim" / "make_splits.py").exists() else None,
                  "seed": 20261024, **split_block},
        "run": {"run_dir": run_rel, "conditions": list(conditions),
                "run_statuses": run_statuses, "artifacts": groups["run_artifacts"]["files"]},
        "groups": groups,
        "generation_checks": generation_checks,
        "known_limitations": KNOWN_LIMITATIONS,
        "protocol_notes": PROTOCOL_NOTES,
    }
    payload = copy.deepcopy(manifest)
    manifest["manifest_payload_sha256"] = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    return manifest


# ---------------------------------------------------------------------- verify
def verify_manifest(manifest: Dict[str, Any], root_override: Optional[Path] = None) -> Dict[str, Any]:
    root = Path(root_override) if root_override is not None else Path(manifest.get("root") or ROOT)
    report: Dict[str, Any] = {"ok": True, "root": str(root), "groups": {}, "errors": []}
    if not root.exists():
        report["ok"] = False
        report["errors"].append(f"root does not exist: {root}")
        return report

    for group_name, group in (manifest.get("groups") or {}).items():
        expected = group.get("files") or {}
        patterns = group.get("patterns") or []
        paths = group.get("paths") or []
        found = expand_paths(patterns, paths, root)
        actual: Dict[str, str] = {}
        for path in found:
            relative = path.resolve().relative_to(root.resolve()).as_posix()
            actual[relative] = sha256_file(path)
        expected_keys = set(expected)
        actual_keys = set(actual)
        missing = sorted(expected_keys - actual_keys)
        extra = sorted(actual_keys - expected_keys)
        mismatched = {relative: {"expected": expected[relative], "actual": actual[relative]}
                      for relative in sorted(expected_keys & actual_keys) if expected[relative] != actual[relative]}
        digest_expected = group.get("digest")
        digest_actual = group_digest(actual) if actual else group_digest({})
        group_ok = not missing and not extra and not mismatched and digest_expected == digest_actual \
            and group.get("count") == len(actual)
        report["groups"][group_name] = {
            "ok": group_ok,
            "expected_count": group.get("count"),
            "actual_count": len(actual),
            "missing": missing,
            "extra": extra,
            "hash_mismatches": mismatched,
            "digest_expected": digest_expected,
            "digest_actual": digest_actual,
        }
        if not group_ok:
            report["ok"] = False
            report["errors"].append(f"group {group_name}: missing={len(missing)} extra={len(extra)} "
                                    f"hash_mismatches={len(mismatched)} count={len(actual)}")

    payload = copy.deepcopy(manifest)
    recorded_payload_hash = payload.pop("manifest_payload_sha256", None)
    recomputed_payload_hash = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    report["manifest_payload_sha256"] = {
        "recorded": recorded_payload_hash,
        "recomputed": recomputed_payload_hash,
        "match": recorded_payload_hash == recomputed_payload_hash,
    }
    if not report["manifest_payload_sha256"]["match"]:
        report["ok"] = False
        report["errors"].append("manifest_payload_sha256 mismatch: manifest file was edited")
    return report


# ------------------------------------------------------------------- self-test
def self_test(manifest: Dict[str, Any]) -> int:
    print("self-test: verify a freshly built manifest, then tamper with copies")
    tests: List[Dict[str, Any]] = []

    def record(name: str, expected_ok: bool, report: Dict[str, Any], detail: str = "") -> None:
        detected = (report["ok"] is expected_ok)
        tests.append({"name": name, "expected_ok": expected_ok, "actual_ok": report["ok"],
                      "detected": detected, "detail": detail,
                      "errors": report["errors"][:3]})
        print(f"  [{'PASS' if detected else 'FAIL'}] {name}: ok={report['ok']} (expected {expected_ok})")

    record("fresh_manifest_verifies", True, verify_manifest(manifest))

    tampered_hash = copy.deepcopy(manifest)
    labels = tampered_hash["groups"]["labels"]["files"]
    first = sorted(labels)[0]
    labels[first] = "0" * 64
    record("tampered_file_hash_detected", False, verify_manifest(tampered_hash), first)

    tampered_extra = copy.deepcopy(manifest)
    removed = sorted(tampered_extra["groups"]["images"]["files"])[0]
    tampered_extra["groups"]["images"]["files"].pop(removed)
    tampered_extra["groups"]["images"]["count"] -= 1
    record("added_or_unlisted_file_detected", False, verify_manifest(tampered_extra), removed)

    tampered_payload = copy.deepcopy(manifest)
    tampered_payload["note_injected"] = "post-hoc edit"
    record("tampered_payload_detected", False, verify_manifest(tampered_payload))

    missing_root = copy.deepcopy(manifest)
    missing_root["groups"]["labels"]["patterns"] = ["no_such_directory/**/*.json"]
    missing_root["groups"]["labels"]["paths"] = []
    record("missing_group_detected", False, verify_manifest(missing_root))

    result = {"all_pass": all(test["detected"] for test in tests), "tests": tests}
    print(json.dumps({"all_pass": result["all_pass"], "tests": len(tests)}, ensure_ascii=False))
    return 0 if result["all_pass"] else 1


# ============================================================ v0.2 profile
# The v0.1 branch above is frozen and must keep producing the same manifest shape
# (v0.1 regression evidence cites its digests).  v0.2 adds a separate profile with
# the extra protocol gates required by docs/WBR/ENACT-USIM-v0.2评测与正式测试方案.
V02_PROFILE = "v0.2"
DEFAULT_V02_LABEL_DOC = ROOT / "docs" / "WBR" / "ENACT-USIM-v0.2标注与关键帧规范-20261027.md"
DEFAULT_V02_EVAL_DOC = ROOT / "docs" / "WBR" / "ENACT-USIM-v0.2评测与正式测试方案-20261027.md"
DEFAULT_V02_ASSIGNMENT = ROOT / "data" / "usim_enact" / "_expansion" / "annotation_assignment.json"
DEFAULT_V02_CONDITION_D_DIR = ROOT / "data" / "usim_enact" / "_protocol" / "conditions" / "D_no_action_text_v0.2"
TEMPLATE_OUT = DEFAULT_OUT_DIR / "templates" / "freeze_v0.2_template.json"
V02_CODE_FILES = CODE_FILES + (
    "scripts/usim/curate_qa_v02.py",
    "scripts/usim/make_splits_v02.py",
    "scripts/usim/migrate_v01_to_v02.py",
    "scripts/usim/collect_v02_annotations.py",
    "scripts/usim/build_condition_d.py",
    "scripts/usim/text_prior_baseline.py",
    "scripts/usim/reseed_answers.py",
    "scripts/usim/make_splits.py",
)
V02_KNOWN_LIMITATIONS = [
    "new v0.2 annotations are single-annotator + Lead spot-check, not independent double annotation; "
    "the v0.1 migration entries keep their original 4-frame selection",
    "ego-only (320x240) gives partial evidence for distance/contact/off-bed predicates; condition B "
    "results cannot be read as 'resolution independent'",
    "the test_reserve episodes are registered as test candidates only: they are not annotated at "
    "freeze time and knowingly do not appear in any dev/val QA or split",
    "no VLM_API_KEY is available in the current session: freezing covers the protocol/inputs and the "
    "program baselines; A/B/C/D model runs must use one single run_inference.py source version",
    "qwen3.8-max is an alias model: only request_id, response model and call time can be recorded",
    "if v0.2 QA still has 0 multi-answer questions, TA is numerically equal to EM (contract fixtures "
    "cover the multi-answer path, not the real set)",
]
V02_PROTOCOL_NOTES = {
    **PROTOCOL_NOTES,
    "seed_policy": "v0.2 split/curation/reseed seed 20261027 (recorded from splits_manifest/curation manifest)",
    "test_reserve_policy": "test episodes are candidates only until the protocol is frozen; they must not "
                           "appear in curated dev/val QA or in dev/val splits",
    "condition_matrix": "A full image / B zoom / C text-only / D no-action-text forward, same frozen QA ids, "
                        "same model+decode params, same run_inference.py source version",
}


def read_json_file(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def read_jsonl_records(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def v02_direction(record: Dict[str, Any]) -> str:
    return "inverse" if "inverse" in record["type"] else "forward"


def qa_summary_v02(records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    ids = [record["id"] for record in records]
    by_type: Dict[str, int] = {}
    by_setting: Dict[str, int] = {}
    for record in records:
        by_type[record["type"]] = by_type.get(record["type"], 0) + 1
        setting = f"{v02_direction(record)}_L{len(record['key_frame_ids'])}"
        by_setting[setting] = by_setting.get(setting, 0) + 1
    identity = sum(1 for record in records
                   if list(record["gt_answer"]) == list(range(1, len(record["gt_answer"]) + 1)))
    return {
        "rows": len(records),
        "unique_ids": len(set(ids)),
        "ids_sha256": sha256_text("\n".join(sorted(ids))),
        "by_type": dict(sorted(by_type.items())),
        "by_setting": dict(sorted(by_setting.items())),
        "episodes": sorted({record["task_name"] for record in records}),
        "episode_count": len({record["task_name"] for record in records}),
        "forward_questions": sum(1 for record in records if v02_direction(record) == "forward"),
        "inverse_questions": sum(1 for record in records if v02_direction(record) == "inverse"),
        "identity_reference_rate": round(identity / len(records), 4) if records else None,
        "transitions_total": sum(len(record["gt_answer"]) for record in records),
    }


def assignment_list(payload: Optional[Dict[str, Any]], key: str) -> List[str]:
    """Normalise an episode list from ``annotation_assignment.json`` (or a plain list file)."""
    if payload is None:
        return []
    value = payload.get(key) if isinstance(payload, dict) else payload
    if value is None:
        return []
    if isinstance(value, dict):
        value = list(value.keys()) if all(isinstance(item, str) for item in value.keys()) else list(value.values())
    result: List[str] = []
    for item in value:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            for field in ("episode_key", "task_name", "episode", "id"):
                if isinstance(item.get(field), str):
                    result.append(item[field])
                    break
    return result


def file_metadata(path: Path, include_title: bool = False) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "path": relative_to_root(path),
        "exists": path.exists(),
        "sha256": sha256_file(path) if path.exists() else None,
        "bytes": path.stat().st_size if path.exists() else None,
    }
    if include_title and path.exists():
        try:
            first_line = path.read_text(encoding="utf-8").splitlines()[0].strip()
            entry["title"] = first_line
        except (IndexError, UnicodeDecodeError, OSError):
            entry["title"] = None
    return entry


def git_snapshot() -> Optional[Dict[str, Any]]:
    """Record the git HEAD + dirty ENACT entries when this checkout is a git repo."""
    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                                       encoding="utf-8", errors="replace",
                                       stderr=subprocess.DEVNULL, timeout=20).strip()
        status = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True,
                                         encoding="utf-8", errors="replace",
                                         stderr=subprocess.DEVNULL, timeout=20)
        dirty = [line for line in status.splitlines() if line.strip()]
        return {"head": head, "dirty_entries_count": len(dirty), "dirty_entries": dirty[:80]}
    except Exception:
        return None


def model_prompt_blocks(configs: Dict[str, Dict[str, Any]], source: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build the prompt/model blocks from run configs (or a single model-config template)."""
    primary = next(iter(configs.values())) if configs else {}
    per_condition = {
        name: {key: config.get(key) for key in ("system_prompt", "format_directive", "prompt_policy")}
        for name, config in configs.items()
    }
    prompt = {
        "source": source,
        "policy": primary.get("prompt_policy"),
        "system_prompt": primary.get("system_prompt"),
        "format_directive": primary.get("format_directive"),
        "format_directive_sha256": sha256_text(primary["format_directive"])
        if primary.get("format_directive") is not None else None,
        "per_condition": per_condition,
        "conditions_agree": len({json.dumps(value, sort_keys=True, ensure_ascii=False)
                                 for value in per_condition.values()}) <= 1,
    }

    def distinct(key: str) -> List[Any]:
        values: List[Any] = []
        for config in configs.values():
            value = config.get(key)
            if value not in values:
                values.append(value)
        return values

    model = {
        "source": source,
        "model_requested": distinct("model_requested"),
        "temperature": distinct("temperature"),
        "enable_thinking": distinct("enable_thinking"),
        "max_completion_tokens": distinct("max_completion_tokens"),
        "stream": distinct("stream"),
        "timeout_seconds": distinct("timeout_seconds"),
        "max_attempts": distinct("max_attempts"),
        "api_url": distinct("api_url"),
        "backend": distinct("backend"),
        "decode_params_consistent_across_conditions": all(
            len(distinct(key)) <= 1 for key in MODEL_PARAM_KEYS),
        "per_condition": {name: {key: config.get(key) for key in MODEL_PARAM_KEYS}
                          for name, config in configs.items()},
    }
    return prompt, model


def build_manifest_v02(opts: Dict[str, Any]) -> Dict[str, Any]:
    """Build the v0.2 freeze manifest (see templates/freeze_v0.2_template.json)."""
    data_root = Path(opts["data_root"])
    run_dir = Path(opts["run_dir"]) if opts.get("run_dir") else None
    inputs_dir = Path(opts["inputs_dir"]) if opts.get("inputs_dir") else (
        run_dir / "inputs" if run_dir is not None else None)
    curated_qa = Path(opts["curated_qa"])
    label_doc = Path(opts["label_doc"])
    eval_doc = Path(opts["eval_doc"])
    assignment = Path(opts["assignment"])
    condition_d_dir = Path(opts["condition_d_dir"])
    condition_d_qa = Path(opts["condition_d_qa"]) if opts.get("condition_d_qa") else condition_d_dir / "enact_ordering.jsonl"
    freeze_id = opts.get("freeze_id") or datetime.now(TZ_SHANGHAI).strftime("%Y%m%d")
    expected_test_reserve = int(opts.get("expected_test_reserve", 10))
    requested_split_seed = opts.get("split_seed")

    problems: List[str] = []
    checks: Dict[str, bool] = {}

    def note(name: str, ok: bool, message: str = "") -> bool:
        checks[name] = bool(ok)
        if not ok:
            problems.append(f"{name}: {message}" if message else name)
        return bool(ok)

    data_rel = relative_to_root(data_root)
    dataset_manifest = read_json_file(data_root / "manifest.json") or {}
    dataset_version = dataset_manifest.get("protocol_version", "usim-enact-v0.2")
    note("dataset_manifest_exists", (data_root / "manifest.json").exists(), str(data_root / "manifest.json"))
    note("dataset_protocol_version_is_v02", str(dataset_version).startswith("usim-enact-v0.2"), str(dataset_version))

    # ---- curated QA ---------------------------------------------------------
    curated_records = read_jsonl_records(curated_qa)
    curated_summary = qa_summary_v02(curated_records)
    curated_ids = {record["id"] for record in curated_records}
    curated_episodes = {record["task_name"] for record in curated_records}
    curated_forward_ids = {record["id"] for record in curated_records if v02_direction(record) == "forward"}
    curated_sha = sha256_file(curated_qa) if curated_qa.exists() else None
    curation_manifest_path = curated_qa.with_name(curated_qa.stem + ".manifest.json")
    curation_manifest = read_json_file(curation_manifest_path)
    note("curated_qa_exists", curated_qa.exists(), str(curated_qa))
    note("curated_qa_nonempty", curated_summary["rows"] > 0)
    note("curated_qa_ids_unique", curated_summary["unique_ids"] == curated_summary["rows"],
         f"{curated_summary['rows']} rows / {curated_summary['unique_ids']} unique ids")
    note("curated_qa_has_both_directions",
         curated_summary["forward_questions"] > 0 and curated_summary["inverse_questions"] > 0)
    note("curation_manifest_exists", curation_manifest is not None, str(curation_manifest_path))

    # ---- test reserve -------------------------------------------------------
    assignment_payload = read_json_file(assignment)
    test_episodes = assignment_list(assignment_payload, "test_reserve")
    dev_new = assignment_list(assignment_payload, "dev_new")
    val_new = assignment_list(assignment_payload, "val_new")
    test_set = set(test_episodes)
    note("assignment_file_exists", assignment.exists(), str(assignment))
    note("test_reserve_count_expected", len(test_episodes) == expected_test_reserve,
         f"expected {expected_test_reserve}, got {len(test_episodes)}")
    note("dev_new_nonempty", len(dev_new) > 0)
    note("val_new_nonempty", len(val_new) > 0)
    test_reserve_curated_overlap = sorted(test_set & curated_episodes)
    note("test_reserve_not_in_curated_qa", not test_reserve_curated_overlap, str(test_reserve_curated_overlap))
    if assignment_payload and assignment_payload.get("protocol_version"):
        note("assignment_protocol_matches_dataset",
             assignment_payload.get("protocol_version") == dataset_version,
             f"{assignment_payload.get('protocol_version')} vs {dataset_version}")

    # ---- splits -------------------------------------------------------------
    split_block: Dict[str, Any] = {"inputs_dir": relative_to_root(inputs_dir) if inputs_dir else None}
    dev_ids: set = set()
    val_ids: set = set()
    dev_val_ids: set = set()
    splits_manifest = None
    if inputs_dir is not None:
        splits_manifest_path = inputs_dir / "splits_manifest.json"
        splits_manifest = read_json_file(splits_manifest_path)
        split_block["splits_manifest"] = file_metadata(splits_manifest_path)
        if splits_manifest:
            split_block.update({
                "seed": splits_manifest.get("seed"),
                "split_version": splits_manifest.get("split_version"),
                "assignment_sha256": splits_manifest.get("assignment_sha256"),
                "qa_sha256": splits_manifest.get("qa_sha256"),
                "splits": splits_manifest.get("splits", {}),
                "empty_splits": splits_manifest.get("empty_splits", []),
            })
            for split in ("dev", "val"):
                info = (splits_manifest.get("splits") or {}).get(split) or {}
                path = Path(info["path"]) if info.get("path") else inputs_dir / f"{split}.jsonl"
                id_list = [record["id"] for record in read_jsonl_records(path)]
                if split == "dev":
                    dev_ids = set(id_list)
                else:
                    val_ids = set(id_list)
                split_block[f"{split}_ids"] = len(id_list)
                split_block[f"{split}_episodes"] = info.get("episodes")
                if info.get("sha256") and path.exists():
                    note(f"splits_{split}_file_sha_matches", sha256_file(path) == info["sha256"])
            dev_val_path = inputs_dir / "dev_val.jsonl"
            dev_val_ids = {record["id"] for record in read_jsonl_records(dev_val_path)}
            split_block["dev_val"] = {
                "path": relative_to_root(dev_val_path),
                "exists": dev_val_path.exists(),
                "ids": len(dev_val_ids),
                "sha256": sha256_file(dev_val_path) if dev_val_path.exists() else None,
            }
        note("splits_manifest_exists", splits_manifest is not None, str(inputs_dir / "splits_manifest.json"))
        if splits_manifest:
            note("splits_seed_present", splits_manifest.get("seed") is not None)
            if requested_split_seed is not None:
                note("splits_seed_matches_requested", splits_manifest.get("seed") == int(requested_split_seed),
                     f"{splits_manifest.get('seed')} vs {requested_split_seed}")
            note("splits_qa_sha_matches_curated", splits_manifest.get("qa_sha256") == curated_sha)
            note("splits_assignment_sha_matches", splits_manifest.get("assignment_sha256") ==
                 (sha256_file(assignment) if assignment.exists() else None))
            note("splits_dev_val_equals_curated_ids", (dev_ids | val_ids) == curated_ids,
                 f"{len(dev_ids | val_ids)} split ids vs {len(curated_ids)} curated ids")
            note("splits_dev_val_disjoint", not (dev_ids & val_ids), str(sorted(dev_ids & val_ids)[:5]))
            split_test_present = bool((splits_manifest.get("splits") or {}).get("test")) or \
                (inputs_dir / "test.jsonl").exists()
            note("splits_test_split_absent", not split_test_present,
                 "test split must not be built before the protocol/test freeze")
            split_episodes = set()
            for split in ("dev", "val"):
                split_episodes |= set(((splits_manifest.get("splits") or {}).get(split) or {}).get("episodes") or [])
            note("test_reserve_not_in_dev_val_episodes", not (test_set & split_episodes),
                 str(sorted(test_set & split_episodes)))
    else:
        note("splits_inputs_dir_provided", False, "pass --split-inputs-dir or --run-dir")

    # ---- condition D --------------------------------------------------------
    d_records = read_jsonl_records(condition_d_qa)
    d_ids = {record["id"] for record in d_records}
    d_summary = qa_summary_v02(d_records)
    d_manifest_path = condition_d_dir / "build_manifest.json"
    d_oracle_path = condition_d_dir / "oracle_report.json"
    d_manifest = read_json_file(d_manifest_path)
    d_oracle = read_json_file(d_oracle_path)
    d_oracle_overall = (d_oracle or {}).get("overall", {})
    d_episodes = {record["task_name"] for record in d_records}
    note("condition_d_qa_exists", condition_d_qa.exists(), str(condition_d_qa))
    note("condition_d_manifest_exists", d_manifest is not None, str(d_manifest_path))
    note("condition_d_oracle_report_exists", d_oracle is not None, str(d_oracle_path))
    note("condition_d_ids_equal_curated_forward", d_ids == curated_forward_ids,
         f"{len(d_ids)} vs {len(curated_forward_ids)}")
    note("condition_d_only_forward", all(v02_direction(record) == "forward" for record in d_records))
    note("condition_d_oracle_is_1_0",
         d_oracle_overall.get("EM") == 1.0 and d_oracle_overall.get("TA") == 1.0
         and d_oracle_overall.get("PA_transition_micro") == 1.0,
         str({key: d_oracle_overall.get(key) for key in ("EM", "TA", "PA_transition_micro")}))
    note("test_reserve_not_in_condition_d", not (test_set & d_episodes), str(sorted(test_set & d_episodes)))

    # ---- audit gate ---------------------------------------------------------
    audit_path = Path(opts.get("audit_evidence") or
                      (DEFAULT_OUT_DIR / f"audit_qa_validity_{dataset_version}.json"))
    audit = read_json_file(audit_path)
    audit_overall = (audit or {}).get("overall", {})
    note("audit_evidence_exists", audit is not None, str(audit_path))
    note("audit_gate_passed", bool(audit and audit.get("all_validity_checks_pass") is True))
    note("audit_zero_empty_reference_transitions",
         audit_overall.get("empty_reference_transitions") == 0,
         str(audit_overall.get("empty_reference_transitions")))
    note("audit_zero_gt_rejected", audit_overall.get("gt_rejected_questions") == 0,
         str(audit_overall.get("gt_rejected_questions")))

    # ---- docs / prompt / model / code --------------------------------------
    note("label_guideline_exists", label_doc.exists(), str(label_doc))
    note("evaluation_plan_exists", eval_doc.exists(), str(eval_doc))

    configs: Dict[str, Dict[str, Any]] = {}
    config_source = ""
    condition_dirs = []
    if run_dir is not None:
        all_dirs = [child for child in sorted(run_dir.iterdir())
                    if child.is_dir() and (child / "run_config.json").exists()] if run_dir.exists() else []
        # final conditions are the evaluated runs; preflight/smoke dirs have no report.json
        # and may use different (empty) prompts, so they must not affect the freeze.
        condition_dirs = [child for child in all_dirs if (child / "report.json").exists()] or all_dirs
        for condition_dir in condition_dirs:
            configs[condition_dir.name] = read_json_file(condition_dir / "run_config.json") or {}
        if configs:
            config_source = "run_config"
    if not configs and opts.get("model_config"):
        model_config_path = Path(opts["model_config"])
        config = read_json_file(model_config_path)
        if config is not None:
            configs = {"model_config_template": config}
            config_source = f"model_config:{relative_to_root(model_config_path)}"
    note("model_config_available", bool(configs), "provide run configs or --model-config")
    prompt_block, model_block = model_prompt_blocks(configs, config_source) if configs else ({}, {})
    if configs:
        note("prompt_conditions_agree", prompt_block["conditions_agree"])

    # ---- groups -------------------------------------------------------------
    run_rel = relative_to_root(run_dir) if run_dir is not None else None
    inputs_rel = relative_to_root(inputs_dir) if inputs_dir is not None else None
    groups: Dict[str, Any] = {
        "dataset_manifest": build_group(paths=[f"{data_rel}/manifest.json"]),
        "labels": build_group(patterns=[
            f"{data_rel}/annotations/**/*.json",
            f"{data_rel}/replayed_activities/*/scene_graph_0.json",
            f"{data_rel}/segmented_activities/*/segmented_scene_graph_0.json",
        ]),
        "images": build_group(patterns=[
            f"{data_rel}/replayed_activities/*/external_sensor1/*.png",
            f"{data_rel}/segmented_activities/*/external_sensor1/*.png",
            f"{data_rel}/QA/images/**/*.png",
            f"{data_rel}/QA/conditions/**/images/**/*.png",
        ]),
        "qa": build_group(patterns=[f"{data_rel}/QA/**/*.jsonl", f"{data_rel}/QA/**/*.json"]),
        "docs": build_group(paths=[relative_to_root(label_doc), relative_to_root(eval_doc)]),
        "registration": build_group(paths=[relative_to_root(assignment)]),
        "condition_d": build_group(paths=[relative_to_root(condition_d_qa),
                                          relative_to_root(d_manifest_path),
                                          relative_to_root(d_oracle_path)]),
        "code": build_group(paths=[relative for relative in V02_CODE_FILES if (ROOT / relative).exists()]),
    }
    if inputs_dir is not None:
        groups["inputs"] = build_group(patterns=[f"{inputs_rel}/*.jsonl", f"{inputs_rel}/*.json"])
    if configs and run_rel:
        condition_patterns = [f"{run_rel}/{name}/*.jsonl" for name in configs] + \
                             [f"{run_rel}/{name}/*.json" for name in configs]
        groups["run_artifacts"] = build_group(patterns=condition_patterns)
    if run_rel and (run_dir / "baselines").exists():
        groups["program_baselines"] = build_group(patterns=[f"{run_rel}/baselines/*.json",
                                                            f"{run_rel}/baselines/*.jsonl"])
    if opts.get("model_config") and config_source.startswith("model_config"):
        groups["model_config"] = build_group(paths=[relative_to_root(Path(opts["model_config"]))])
    if audit is not None:
        groups["audit_evidence"] = build_group(paths=[relative_to_root(audit_path)])
    note("code_files_captured", groups["code"]["count"] >= 15, f"{groups['code']['count']} files")
    note("labels_captured", groups["labels"]["count"] > 0, f"{groups['labels']['count']} files")
    note("images_captured", groups["images"]["count"] > 0, f"{groups['images']['count']} files")
    note("program_baselines_captured", groups.get("program_baselines", {}).get("count", 0) > 0,
         f"{groups.get('program_baselines', {}).get('count', 0)} files")

    # ---- dataset manifest internal hash checks (labels + key frames) --------
    label_files = groups["labels"]["files"]
    annotation_checks = {
        name: {
            "expected": digest,
            "actual": label_files.get(f"{data_rel}/annotations/episodes/{name}"),
            "match": label_files.get(f"{data_rel}/annotations/episodes/{name}") == digest,
        }
        for name, digest in sorted((dataset_manifest.get("annotation_sha256") or {}).items())
    }
    image_files = groups["images"]["files"]
    frame_checks: List[Dict[str, Any]] = []
    for episode in dataset_manifest.get("episodes", []):
        for frame_group in ("frames", "segmented_frames"):
            for frame_id, frame in sorted((episode.get(frame_group) or {}).items()):
                frame_path = str(frame["path"]).replace("\\", "/")
                relative = f"{data_rel}/{frame_path}"
                actual = image_files.get(relative)
                frame_checks.append({"episode": episode.get("episode_key"), "group": frame_group,
                                     "frame": frame_id, "path": relative,
                                     "expected": frame.get("sha256"), "actual": actual,
                                     "match": actual == frame.get("sha256")})
    note("dataset_annotation_hashes_match",
         bool(annotation_checks) and all(entry["match"] for entry in annotation_checks.values()),
         f"{sum(1 for entry in annotation_checks.values() if not entry['match'])} mismatches / "
         f"{len(annotation_checks)} annotations")
    note("dataset_frame_hashes_match",
         not [row for row in frame_checks if not row["match"]],
         f"{sum(1 for row in frame_checks if not row['match'])} mismatches / {len(frame_checks)} frames")
    curation_checks = {
        "curation_manifest_output_sha_matches_curated": bool(
            curation_manifest and curation_manifest.get("output_qa_sha256") == curated_sha),
        "curation_manifest_total_selected_matches": bool(
            curation_manifest and curation_manifest.get("total_selected") == curated_summary["rows"]),
        "curation_seed_recorded": bool(curation_manifest and curation_manifest.get("seed") is not None),
    }
    for name, ok in curation_checks.items():
        note(name, ok)

    # ---- scoring ------------------------------------------------------------
    evaluate_rel = relative_to_root(ROOT / "scripts" / "usim" / "evaluate.py")
    run_artifact_protocols: Dict[str, Any] = {}
    if run_dir is not None:
        for condition_dir in condition_dirs:
            report = read_json_file(condition_dir / "report.json")
            if report:
                run_artifact_protocols[condition_dir.name] = {
                    "evaluation_protocol": report.get("evaluation_protocol"),
                    "report_sha256": sha256_file(condition_dir / "report.json"),
                    "total_questions": report.get("total_questions"),
                    "overall": report.get("overall"),
                }
    scoring_block = {
        "evaluation_protocol": EVALUATION_PROTOCOL,
        "scorer": evaluate_rel,
        "scorer_sha256": sha256_file(ROOT / "scripts" / "usim" / "evaluate.py"),
        "verifier": PROTOCOL_NOTES["verifier"],
        "parser_version": PROTOCOL_NOTES["scoring_parser_version"],
        "metrics": ["EM", "TA", "semantic_only", "PA_item_mean", "PA_transition_micro"],
        "fixed_denominator": True,
        "strict_parser": True,
        "asset_precheck_aborts": True,
        "reference_transition_gate": {
            "enforced_in_precheck": True,
            "empty_visible_signature_policy": "AssetError, non-zero exit, no report",
            "introduced_in": "usim_strict_v0.3",
        },
        "protocol_history": {
            "usim_strict_v0.2": "v0.1 development protocol (no empty-signature gate)",
            "usim_strict_v0.3": "v0.2 protocol: adds reference-transition gate; EM/TA/PA unchanged",
        },
        "run_artifact_evaluation_protocols": run_artifact_protocols,
    }

    # ---- manifest -----------------------------------------------------------
    manifest: Dict[str, Any] = {
        "schema": SCHEMA,
        "profile": V02_PROFILE,
        "freeze_id": freeze_id,
        "created_at": now_iso(),
        "root": str(ROOT.resolve()),
        "dataset": {
            "protocol_version": dataset_version,
            "data_root": data_rel,
            "manifest_sha256": sha256_file(data_root / "manifest.json")
            if (data_root / "manifest.json").exists() else None,
            "counts": dataset_manifest.get("counts"),
            "episodes": [episode.get("episode_key") for episode in dataset_manifest.get("episodes", [])],
            "annotation_hashes_checked": len(annotation_checks),
            "frame_hashes_checked": len(frame_checks),
            "hash_mismatches": {
                "annotations": [name for name, entry in annotation_checks.items() if not entry["match"]],
                "frames": [row["path"] for row in frame_checks if not row["match"]],
            },
            "migration_file": file_metadata(data_root / "migration_v01_to_v02.json"),
        },
        "label_guideline": file_metadata(label_doc, include_title=True),
        "evaluation_plan": file_metadata(eval_doc, include_title=True),
        "curated_qa": {
            "file": file_metadata(curated_qa),
            "summary": curated_summary,
            "curation_manifest": file_metadata(curation_manifest_path),
        },
        "qa_gate": {
            "audit_evidence": file_metadata(audit_path),
            "passed": bool(audit and audit.get("all_validity_checks_pass") is True),
            "evaluation_protocol": (audit or {}).get("evaluation_protocol"),
            "overall": audit_overall,
            "multi_answer_questions": audit_overall.get("multi_answer_questions"),
            "accepted_count_histogram": audit_overall.get("accepted_count_histogram"),
        },
        "test_reserve": {
            "source": file_metadata(assignment),
            "policy": "test candidates only; annotated only after this protocol freeze; "
                      "must not appear in curated dev/val QA, dev/val splits or condition D",
            "registered_episodes": sorted(test_episodes),
            "registered_count": len(test_episodes),
            "expected_count": expected_test_reserve,
            "dev_new_count": len(dev_new),
            "val_new_count": len(val_new),
            "overlap_with_curated_qa_episodes": test_reserve_curated_overlap,
            "used_in_dev_val": False,
        },
        "condition_d": {
            "qa_file": file_metadata(condition_d_qa),
            "manifest": file_metadata(d_manifest_path),
            "oracle_report": file_metadata(d_oracle_path),
            "summary": d_summary,
            "forward_ids_match_curated": d_ids == curated_forward_ids,
            "oracle_overall": d_oracle_overall,
        },
        "prompt": prompt_block,
        "model": model_block,
        "scoring": scoring_block,
        "split": split_block,
        "run": {
            "run_dir": run_rel,
            "inputs_dir": inputs_rel,
            "baselines_dir": f"{run_rel}/baselines" if (run_rel and (run_dir / "baselines").exists()) else None,
            "model_config_source": config_source,
            "condition_run_configs": sorted(configs) if config_source == "run_config" else [],
            "note": "no A/B/C/D model predictions at freeze time: the run directory contains input splits "
                    "and program baselines only (VLM_API_KEY pending); model runs must use one source version",
        },
        "code_snapshot": {
            "git": git_snapshot(),
            "files_digest": groups["code"]["digest"],
            "files_count": groups["code"]["count"],
            "note": "A/B/C/D model runs must use the same run_inference.py source version as this snapshot.",
        },
        "groups": groups,
        "generation_checks": {
            "checks": dict(sorted(checks.items())),
            "failed_checks": sorted(name for name, ok in checks.items() if not ok),
            "problems": problems,
            "all_hard_checks_pass": not problems,
        },
        "known_limitations": V02_KNOWN_LIMITATIONS,
        "protocol_notes": V02_PROTOCOL_NOTES,
    }
    payload = copy.deepcopy(manifest)
    manifest["manifest_payload_sha256"] = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    return manifest


def build_v02_template() -> Dict[str, Any]:
    """Field contract for the v0.2 freeze (written before the data/QA is ready)."""
    return {
        "schema": "usim-protocol-freeze-v02-template/v1",
        "profile": V02_PROFILE,
        "status": "fields template only; not a freeze. Fill it by running the command below once the "
                  "v0.2 curated QA / splits / condition D / audit evidence exist.",
        "generated_at": now_iso(),
        "command": (
            "python -m scripts.usim.freeze_protocol "
            "--data-root data/usim_enact/usim-enact-v0.2 "
            "--curated-qa data/usim_enact/usim-enact-v0.2/QA/train/enact_ordering_curated.jsonl "
            "--split-inputs-dir data/usim_enact/runs/qwen3.8-max/v02_dev_001/inputs "
            "--condition-d-qa data/usim_enact/_protocol/conditions/D_no_action_text_v0.2/enact_ordering.jsonl "
            "--model-config <run_config.json or --run-dir with run configs> "
            "--freeze-id 20261027"
        ),
        "required_cli": {
            "--data-root": {"default": "data/usim_enact/usim-enact-v0.2",
                            "provides": "dataset manifest, labels, scene graphs, images, full QA"},
            "--curated-qa": {"required": True,
                             "provides": "frozen v0.2 dev/val question set (audit-gated)"},
            "--split-inputs-dir / --run-dir": {"required": True,
                                               "provides": "dev/val splits manifest + seed + membership"},
            "--condition-d-qa": {"default": str(DEFAULT_V02_CONDITION_D_DIR / "enact_ordering.jsonl"),
                                 "provides": "no-action-text forward QA + manifest + oracle report"},
            "--label-doc": {"default": str(DEFAULT_V02_LABEL_DOC),
                            "provides": "v0.2 annotation guideline sha256"},
            "--eval-doc": {"default": str(DEFAULT_V02_EVAL_DOC),
                           "provides": "v0.2 evaluation plan sha256"},
            "--assignment": {"default": str(DEFAULT_V02_ASSIGNMENT),
                             "provides": "test_reserve/dev_new/val_new episode registration"},
            "--model-config / --run-dir": {"required": True,
                                           "provides": "prompt + format directive sha, model/decode params"},
            "--audit-evidence": {"default": "_protocol/audit_qa_validity_usim-enact-v0.2.json",
                                 "provides": "QA validity gate (must pass; 0 empty reference transitions)"},
            "--split-seed": {"optional": 20261027, "provides": "assert split manifest seed"},
            "--expected-test-reserve": {"default": 10,
                                        "provides": "expected number of reserved test episodes"},
        },
        "manifest_sections": {
            "dataset": {"required": True, "contents": ["protocol_version", "manifest sha256", "counts",
                                                       "episodes", "migration_v01_to_v02 file hash"]},
            "label_guideline": {"required": True, "contents": ["path", "sha256", "bytes", "title"]},
            "evaluation_plan": {"required": True, "contents": ["path", "sha256", "bytes", "title"]},
            "curated_qa": {"required": True, "contents": ["file sha256", "rows/ids", "by_type", "by_setting",
                                                          "episodes", "identity_reference_rate",
                                                          "curation manifest sha256"]},
            "qa_gate": {"required": True, "contents": ["audit evidence sha256", "pass flag",
                                                       "0 empty reference transitions", "multi-answer count",
                                                       "accepted-size histogram"]},
            "test_reserve": {"required": True, "contents": ["assignment file sha256", "10 registered episodes",
                                                            "overlap_with_curated_qa_episodes=[]",
                                                            "used_in_dev_val=false"]},
            "condition_d": {"required": True, "contents": ["QA sha256", "rows/by_setting",
                                                           "ids == curated forward ids",
                                                           "oracle report sha256 + EM/TA/PA=1.0"]},
            "prompt": {"required": True, "contents": ["policy", "system_prompt", "format_directive",
                                                      "format_directive_sha256", "conditions agree"]},
            "model": {"required": True, "contents": ["model_requested", "temperature", "enable_thinking",
                                                     "max_completion_tokens", "stream", "timeout", "max_attempts",
                                                     "api_url", "backend", "decode params consistent"]},
            "scoring": {"required": True, "contents": ["usim_strict_v0.3", "evaluate.py sha256",
                                                       "reference_transition_gate", "EM/TA/PA unchanged"]},
            "split": {"required": True, "contents": ["seed", "splits manifest sha256", "qa/assignment sha256",
                                                     "dev/val membership", "test split absent"]},
            "code_snapshot": {"required": True, "contents": ["source file sha256 set", "git HEAD + dirty entries",
                                                             "same run_inference.py version for A/B/C/D"]},
            "groups": {"required": True, "contents": ["hash groups: labels/images/qa/docs/registration/"
                                                      "condition_d/code/inputs/run_artifacts/audit_evidence"]},
            "generation_checks": {"required": True, "contents": ["per-check booleans", "problems list",
                                                                 "all_hard_checks_pass"]},
            "known_limitations": {"required": True, "contents": ["single annotator", "ego partial", "test reserve "
                                                                 "not annotated", "no API key", "alias model",
                                                                 "TA==EM if 0 multi-answer"]},
            "manifest_payload_sha256": {"required": True,
                                        "contents": ["sha256 over canonical manifest minus this field"]},
        },
        "hard_gates": [
            "dataset manifest exists and protocol_version starts with usim-enact-v0.2",
            "curated QA exists, ids unique, has both forward and inverse questions",
            "test_reserve has the expected episode count and ZERO overlap with curated QA episodes",
            "dev/val splits manifest exists, seed recorded (and optionally asserted), QA/assignment sha match",
            "dev+val ids equal the curated QA ids, dev/val disjoint, test split absent",
            "test_reserve episodes absent from dev/val split episodes and condition D",
            "condition D ids equal the curated forward ids, only forward, oracle EM/TA/PA=1.0",
            "audit evidence exists, passes, and reports 0 empty reference transitions / 0 rejected gt",
            "label guideline + evaluation plan docs exist and are hashed",
            "prompt/model config available and consistent",
            "code files captured (source sha set + git snapshot)",
        ],
        "known_limitations": V02_KNOWN_LIMITATIONS,
        "protocol_notes": V02_PROTOCOL_NOTES,
    }


def _write_fixture_file(path: Path, content: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(str(content), encoding="utf-8")


def self_test_v02() -> int:
    """Exercise the v0.2 profile on a temporary mock fixture (no real v0.2 data needed)."""
    base = DEFAULT_OUT_DIR / "_selftest_v02"
    if base.exists():
        shutil.rmtree(base)
    mock_data = base / "data" / "usim-enact-v0.2-mock"
    qa_dir = mock_data / "QA" / "train"
    inputs = base / "inputs"
    condition_d = base / "condition_d"
    docs = base / "docs"
    assignment_path = base / "_expansion" / "annotation_assignment.json"
    audit_path = base / "audit" / "audit_qa_validity_mock.json"
    model_config_path = base / "model" / "model_config.json"
    episodes = {"dev": "usim_train_episode_900001", "val": "usim_train_episode_900002"}
    test_reserve = [f"usim_train_episode_9000{i:02d}" for i in range(10, 20)]

    def record(record_id: str, task_name: str, direction: str, gt: list, question: str) -> Dict[str, Any]:
        return {
            "id": record_id,
            "type": f"{direction}_world_modeling_{len(gt) + 1}_steps",
            "task_name": task_name,
            "key_frame_ids": [str(100 + index) for index in range(len(gt) + 1)],
            "images": [f"QA/images/mock/{task_name}/img_{index}.png" for index in range(len(gt) + 1)],
            "question": question,
            "options": [],
            "gt_answer": gt,
        }

    forward_question = ("## Shuffled Actions\n[Action 1] The robot now becomes in position for the pre-grasp "
                        "approach beside the blue cylinder.\n[Action 2] The blue cylinder is now grasped by the robot.\n")
    inverse_question = ("## Shuffled Actions\n[Action 1] The blue cylinder is now grasped by the robot.\n"
                        "[Action 2] The robot now becomes in position for the pre-grasp approach beside the blue cylinder.\n")
    forward_record = record("mock_v02_forward_1", episodes["dev"], "forward", [1, 2], forward_question)
    inverse_record = record("mock_v02_inverse_1", episodes["val"], "inverse", [2, 1], inverse_question)
    curated = [forward_record, inverse_record]

    # dataset / labels / images / QA
    for episode in episodes.values():
        _write_fixture_file(mock_data / "annotations" / "episodes" / f"{episode}.json",
                            json.dumps({"episode_key": episode, "protocol_version": "usim-enact-v0.2"},
                                       ensure_ascii=False))
        _write_fixture_file(mock_data / "replayed_activities" / episode / "scene_graph_0.json", "{}\n")
        _write_fixture_file(mock_data / "segmented_activities" / episode / "segmented_scene_graph_0.json", "{}\n")
        _write_fixture_file(mock_data / "replayed_activities" / episode / "external_sensor1" / "00100.png", b"PNG")
        _write_fixture_file(mock_data / "segmented_activities" / episode / "external_sensor1" / "00100.png", b"PNG")
        _write_fixture_file(mock_data / "QA" / "images" / "mock" / episode / "img_0.png", b"PNG")
        _write_fixture_file(mock_data / "QA" / "conditions" / "B_zoom" / "images" / "mock" / episode / "img_0.png",
                            b"PNG")
    png_sha = sha256_text("PNG")
    mock_episodes = []
    for episode in episodes.values():
        mock_episodes.append({
            "episode_key": episode,
            "frames": {"100": {"path": f"replayed_activities/{episode}/external_sensor1/00100.png",
                               "sha256": png_sha}},
            "segmented_frames": {"100": {"path": f"segmented_activities/{episode}/external_sensor1/00100.png",
                                         "sha256": png_sha}},
        })
    _write_fixture_file(mock_data / "manifest.json", json.dumps({
        "protocol_version": "usim-enact-v0.2", "counts": {"episodes": 2, "key_frames": 4},
        "annotation_sha256": {
            f"{episode}.json": sha256_file(mock_data / "annotations" / "episodes" / f"{episode}.json")
            for episode in episodes.values()
        },
        "episodes": mock_episodes,
    }, ensure_ascii=False))
    _write_fixture_file(qa_dir / "enact_ordering.jsonl",
                        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in curated))
    _write_fixture_file(qa_dir / "enact_ordering_curated.jsonl",
                        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in curated))
    _write_fixture_file(qa_dir / "enact_ordering_curated.manifest.json",
                        json.dumps({"curation_version": "usim-enact-v0.2-curation-v1", "seed": 20261027,
                                    "total_input_questions": 2, "total_selected": 2, "by_type": {},
                                    "input_qa_sha256": sha256_file(qa_dir / "enact_ordering.jsonl"),
                                    "output_qa_sha256": sha256_file(qa_dir / "enact_ordering_curated.jsonl")},
                                   ensure_ascii=False))
    _write_fixture_file(docs / "label_guideline.md", "# mock label guideline\n")
    _write_fixture_file(docs / "evaluation_plan.md", "# mock evaluation plan\n")
    _write_fixture_file(assignment_path, json.dumps({
        "assignment_version": "mock", "protocol_version": "usim-enact-v0.2",
        "dev_new": [episodes["dev"]], "val_new": [episodes["val"]],
        "test_reserve": test_reserve, "counts": {"dev_new": 1, "val_new": 1, "test_reserve": 10},
    }, ensure_ascii=False))
    _write_fixture_file(audit_path, json.dumps({
        "dataset_version": "usim-enact-v0.2", "evaluation_protocol": EVALUATION_PROTOCOL,
        "all_validity_checks_pass": True,
        "overall": {"count": 2, "multi_answer_questions": 0, "accepted_count_histogram": {"1": 2},
                    "empty_reference_transitions": 0, "gt_rejected_questions": 0,
                    "uniform_EM": 0.5, "uniform_TA": 0.5, "uniform_PA_item_mean": 0.5,
                    "uniform_PA_transition_micro": 0.5, "identity_EM": 0.5},
    }, ensure_ascii=False))
    _write_fixture_file(model_config_path, json.dumps({
        "model_requested": "qwen3.8-max", "temperature": 0.0, "enable_thinking": False,
        "max_completion_tokens": 256, "stream": False, "timeout_seconds": 180, "max_attempts": 3,
        "api_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", "backend": "openai",
        "prompt_policy": "option_a_no_system_message", "system_prompt": None,
        "format_directive": "IMPORTANT: Respond with ONLY the Python list of integers, for example [2, 1].",
    }, ensure_ascii=False))

    # splits (dev/val only, test absent) - mirror make_splits_v02 manifest fields
    _write_fixture_file(inputs / "dev.jsonl", json.dumps(forward_record, ensure_ascii=False) + "\n")
    _write_fixture_file(inputs / "val.jsonl", json.dumps(inverse_record, ensure_ascii=False) + "\n")
    _write_fixture_file(inputs / "dev_val.jsonl",
                        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in curated))
    _write_fixture_file(inputs / "splits_manifest.json", json.dumps({
        "split_version": "usim-enact-v0.2-splits-v1", "seed": 20261027,
        "assignment": str(assignment_path), "assignment_sha256": sha256_file(assignment_path),
        "qa": str(qa_dir / "enact_ordering_curated.jsonl"),
        "qa_sha256": sha256_file(qa_dir / "enact_ordering_curated.jsonl"),
        "splits": {
            "dev": {"path": str(inputs / "dev.jsonl"), "sha256": sha256_file(inputs / "dev.jsonl"),
                    "questions": 1, "episodes": [episodes["dev"]], "episode_count": 1},
            "val": {"path": str(inputs / "val.jsonl"), "sha256": sha256_file(inputs / "val.jsonl"),
                    "questions": 1, "episodes": [episodes["val"]], "episode_count": 1},
        },
        "empty_splits": ["test"],
        "dev_val": {"path": str(inputs / "dev_val.jsonl"), "sha256": sha256_file(inputs / "dev_val.jsonl"),
                    "questions": 2, "episodes": sorted(episodes.values())},
    }, ensure_ascii=False))

    # condition D (forward only) + oracle report
    d_question = "## Your Task\nDetermine the chronological order of the future state images.\n## Output Format\n[1, 3, 2]\n"
    d_record = dict(forward_record)
    d_record["question"] = d_question
    _write_fixture_file(condition_d / "enact_ordering.jsonl", json.dumps(d_record, ensure_ascii=False) + "\n")
    _write_fixture_file(condition_d / "build_manifest.json",
                        json.dumps({"condition": "D_no_action_text", "profile": V02_PROFILE,
                                    "counts": {"total": 1}}, ensure_ascii=False))
    _write_fixture_file(condition_d / "oracle_report.json", json.dumps({
        "total": 1, "overall": {"count": 1, "EM": 1.0, "TA": 1.0, "PA_item_mean": 1.0,
                                "PA_transition_micro": 1.0},
    }, ensure_ascii=False))

    # mock run directory with program baselines (no condition run configs yet)
    mock_run = base / "run"
    _write_fixture_file(mock_run / "baselines" / "baseline_oracle.json", json.dumps({
        "dataset_version": "usim-enact-v0.2", "evaluation_protocol": EVALUATION_PROTOCOL,
        "total_questions": 2, "overall": {"count": 2, "EM": 1.0, "TA": 1.0, "PA_item_mean": 1.0,
                                          "PA_transition_micro": 1.0},
    }, ensure_ascii=False))

    opts = {
        "data_root": mock_data,
        "curated_qa": qa_dir / "enact_ordering_curated.jsonl",
        "inputs_dir": inputs,
        "run_dir": mock_run,
        "label_doc": docs / "label_guideline.md",
        "eval_doc": docs / "evaluation_plan.md",
        "assignment": assignment_path,
        "condition_d_dir": condition_d,
        "condition_d_qa": condition_d / "enact_ordering.jsonl",
        "audit_evidence": audit_path,
        "model_config": model_config_path,
        "freeze_id": "selftest",
        "expected_test_reserve": 10,
        "split_seed": 20261027,
    }
    manifest = build_manifest_v02(opts)
    tests: List[Dict[str, Any]] = []

    def record_test(name: str, ok: bool, detail: Any = None) -> None:
        tests.append({"name": name, "pass": bool(ok), "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" ({detail})" if detail and not ok else ""))

    hard_ok = manifest["generation_checks"]["all_hard_checks_pass"]
    record_test("mock_manifest_hard_checks_pass", hard_ok,
                manifest["generation_checks"]["failed_checks"])
    required_sections = ("dataset", "label_guideline", "evaluation_plan", "curated_qa", "qa_gate",
                         "test_reserve", "condition_d", "prompt", "model", "scoring", "split",
                         "code_snapshot", "groups", "generation_checks", "manifest_payload_sha256")
    record_test("manifest_sections_present", all(section in manifest for section in required_sections),
                [section for section in required_sections if section not in manifest])
    manifest_path = base / "freeze_mock.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                             encoding="utf-8")
    verification = verify_manifest(manifest)
    record_test("mock_manifest_verifies", verification["ok"], verification["errors"])

    # negative 1: test_reserve episode leaking into curated QA
    bad_assignment = base / "_expansion" / "assignment_overlap.json"
    payload = json.loads(assignment_path.read_text(encoding="utf-8"))
    payload["test_reserve"] = list(test_reserve) + [episodes["dev"]]
    bad_assignment.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    overlap_manifest = build_manifest_v02({**opts, "assignment": bad_assignment})
    record_test("test_reserve_overlap_detected",
                not overlap_manifest["generation_checks"]["all_hard_checks_pass"]
                and "test_reserve_not_in_curated_qa" in overlap_manifest["generation_checks"]["failed_checks"],
                overlap_manifest["generation_checks"]["failed_checks"])

    # negative 2: missing label guideline doc
    missing_doc_manifest = build_manifest_v02({**opts, "label_doc": base / "docs" / "missing.md"})
    record_test("missing_label_doc_detected",
                "label_guideline_exists" in missing_doc_manifest["generation_checks"]["failed_checks"])

    # negative 3: condition D not matching curated forward ids
    bad_d_dir = base / "condition_d_bad"
    _write_fixture_file(bad_d_dir / "enact_ordering.jsonl",
                        json.dumps(dict(d_record, id="mock_v02_forward_deadbeef"), ensure_ascii=False) + "\n")
    _write_fixture_file(bad_d_dir / "build_manifest.json", "{}")
    _write_fixture_file(bad_d_dir / "oracle_report.json",
                        json.dumps({"overall": {"EM": 1.0, "TA": 1.0, "PA_transition_micro": 1.0}}))
    bad_d_manifest = build_manifest_v02({**opts, "condition_d_dir": bad_d_dir,
                                         "condition_d_qa": bad_d_dir / "enact_ordering.jsonl"})
    record_test("condition_d_id_mismatch_detected",
                "condition_d_ids_equal_curated_forward" in bad_d_manifest["generation_checks"]["failed_checks"])

    # negative 4: tampered manifest payload
    tampered = copy.deepcopy(manifest)
    tampered["note_injected"] = "post-hoc edit"
    record_test("tampered_payload_detected", not verify_manifest(tampered)["ok"])

    result = {"all_pass": all(test["pass"] for test in tests), "tests": tests}
    print(json.dumps({"all_pass": result["all_pass"], "tests": len(tests),
                      "fixture": str(base)}, ensure_ascii=False))
    if os.environ.get("DSH_KEEP_FREEZE_FIXTURE") == "1":
        print(f"kept fixture for manual CLI checks: {base}")
    else:
        shutil.rmtree(base, ignore_errors=True)
    return 0 if result["all_pass"] else 1


# ------------------------------------------------------------------------ main
def default_out_path(data_root: Path, freeze_id: str) -> Path:
    dataset_version = PROTOCOL_VERSION
    manifest_path = data_root / "manifest.json"
    if manifest_path.exists():
        try:
            dataset_version = json.loads(manifest_path.read_text(encoding="utf-8")).get(
                "protocol_version", dataset_version)
        except json.JSONDecodeError:
            pass
    return DEFAULT_OUT_DIR / f"freeze_{dataset_version}_{freeze_id}.json"


def detect_profile(data_root: Path) -> str:
    manifest = read_json_file(data_root / "manifest.json") or {}
    version = str(manifest.get("protocol_version", ""))
    return V02_PROFILE if version.startswith("usim-enact-v0.2") else "v0.1"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--run-dir", default="",
                        help="run directory with condition sub-directories (v0.1 default: "
                             f"{DEFAULT_RUN_DIR})")
    parser.add_argument("--condition", action="append", default=[],
                        help="condition sub-directory under --run-dir; repeatable "
                             "(default: full_v1, condB_zoom, condC_text_only if present)")
    parser.add_argument("--freeze-id", default=datetime.now(TZ_SHANGHAI).strftime("%Y%m%d"))
    parser.add_argument("--out", default="")
    parser.add_argument("--verify", default="", help="verify an existing manifest and exit")
    parser.add_argument("--verify-out", default="", help="optional JSON report path for --verify")
    parser.add_argument("--root", default="", help="override the recorded root when verifying")
    parser.add_argument("--self-test", action="store_true", help="run v0.1 tamper-detection self-tests")
    parser.add_argument("--no-verify-after-generate", action="store_true")
    # ---- v0.2 profile options
    parser.add_argument("--profile", choices=["", "v0.1", "v0.2"], default="",
                        help="freeze profile; default = auto-detect from <data-root>/manifest.json")
    parser.add_argument("--curated-qa", default="", help="v0.2: curated dev/val QA JSONL")
    parser.add_argument("--split-inputs-dir", default="", help="v0.2: run inputs dir with splits_manifest.json")
    parser.add_argument("--label-doc", default=str(DEFAULT_V02_LABEL_DOC),
                        help="v0.2: annotation guideline document")
    parser.add_argument("--eval-doc", default=str(DEFAULT_V02_EVAL_DOC),
                        help="v0.2: evaluation plan document")
    parser.add_argument("--assignment", default=str(DEFAULT_V02_ASSIGNMENT),
                        help="v0.2: annotation_assignment.json with dev_new/val_new/test_reserve")
    parser.add_argument("--condition-d-qa", default="",
                        help="v0.2: condition D no-action-text QA JSONL "
                             f"(default: {DEFAULT_V02_CONDITION_D_DIR / 'enact_ordering.jsonl'})")
    parser.add_argument("--audit-evidence", default="",
                        help="v0.2: audit_qa_validity evidence JSON (default: _protocol/audit_qa_validity_<dataset>.json)")
    parser.add_argument("--model-config", default="",
                        help="v0.2: run_config-like JSON when model runs do not exist yet")
    parser.add_argument("--split-seed", type=int, default=None, help="v0.2: assert the split seed")
    parser.add_argument("--expected-test-reserve", type=int, default=10,
                        help="v0.2: expected number of reserved test episodes")
    parser.add_argument("--template", action="store_true", help="write the v0.2 freeze fields template and exit")
    parser.add_argument("--self-test-v02", action="store_true",
                        help="exercise the v0.2 profile on a temporary mock fixture and exit")
    args = parser.parse_args(argv)

    if args.verify:
        manifest_path = Path(args.verify)
        if not manifest_path.exists():
            print(f"manifest not found: {manifest_path}", file=sys.stderr)
            return 2
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        report = verify_manifest(manifest, Path(args.root) if args.root else None)
        report["manifest"] = str(manifest_path)
        report["checked_at"] = now_iso()
        if args.verify_out:
            out = Path(args.verify_out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        summary = {"ok": report["ok"], "root": report["root"],
                   "profile": manifest.get("profile", "v0.1"),
                   "groups": {name: {"ok": block["ok"], "files": block["actual_count"]}
                              for name, block in report["groups"].items()},
                   "payload_hash_match": report["manifest_payload_sha256"]["match"],
                   "errors": report["errors"]}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 2

    if args.template:
        template = build_v02_template()
        TEMPLATE_OUT.parent.mkdir(parents=True, exist_ok=True)
        TEMPLATE_OUT.write_text(json.dumps(template, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        summary = {
            "template": str(TEMPLATE_OUT),
            "profile": template["profile"],
            "sections": sorted(template["manifest_sections"]),
            "required_cli": sorted(template["required_cli"]),
            "hard_gates": len(template["hard_gates"]),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    if args.self_test_v02:
        return self_test_v02()

    data_root = Path(args.data_root)
    if not data_root.exists():
        print(f"data root not found: {data_root}", file=sys.stderr)
        return 2
    profile = args.profile or detect_profile(data_root)

    if profile == V02_PROFILE:
        curated_qa = Path(args.curated_qa) if args.curated_qa else \
            data_root / "QA" / "train" / "enact_ordering_curated.jsonl"
        if not args.split_inputs_dir:
            print("v0.2 profile requires --split-inputs-dir (or --run-dir with inputs/) containing "
                  "dev/val splits; refusing to freeze without split membership.", file=sys.stderr)
            return 2
        inputs_dir = Path(args.split_inputs_dir)
        condition_d_qa = Path(args.condition_d_qa) if args.condition_d_qa else \
            DEFAULT_V02_CONDITION_D_DIR / "enact_ordering.jsonl"
        opts = {
            "data_root": data_root,
            "run_dir": args.run_dir if args.run_dir and Path(args.run_dir).exists() else None,
            "inputs_dir": inputs_dir,
            "curated_qa": curated_qa,
            "label_doc": Path(args.label_doc),
            "eval_doc": Path(args.eval_doc),
            "assignment": Path(args.assignment),
            "condition_d_dir": condition_d_qa.parent,
            "condition_d_qa": condition_d_qa,
            "audit_evidence": Path(args.audit_evidence) if args.audit_evidence else None,
            "model_config": Path(args.model_config) if args.model_config else None,
            "freeze_id": args.freeze_id,
            "expected_test_reserve": args.expected_test_reserve,
            "split_seed": args.split_seed,
        }
        manifest = build_manifest_v02(opts)
        if args.self_test:
            return self_test(manifest)  # generic tamper test also works on v0.2 manifests
        if not manifest["generation_checks"]["all_hard_checks_pass"]:
            print(json.dumps({
                "profile": V02_PROFILE,
                "hard_checks_pass": False,
                "failed_checks": manifest["generation_checks"]["failed_checks"],
                "problems": manifest["generation_checks"]["problems"],
            }, ensure_ascii=False, indent=2), file=sys.stderr)
            return 2
        out_path = Path(args.out) if args.out else default_out_path(data_root, args.freeze_id)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                            encoding="utf-8")
        verification = verify_manifest(manifest)
        if args.verify_out:
            verify_out = Path(args.verify_out)
            verify_out.parent.mkdir(parents=True, exist_ok=True)
            verify_out.write_text(json.dumps(verification, indent=2, ensure_ascii=False) + "\n",
                                  encoding="utf-8")
        summary = {
            "manifest": str(out_path),
            "profile": V02_PROFILE,
            "freeze_id": manifest["freeze_id"],
            "dataset_version": manifest["dataset"]["protocol_version"],
            "curated_qa": manifest["curated_qa"]["summary"],
            "test_reserve": {"registered_count": manifest["test_reserve"]["registered_count"],
                             "expected_count": manifest["test_reserve"]["expected_count"],
                             "overlap_with_curated_qa_episodes":
                                 manifest["test_reserve"]["overlap_with_curated_qa_episodes"],
                             "used_in_dev_val": manifest["test_reserve"]["used_in_dev_val"]},
            "condition_d": {
                "rows": manifest["condition_d"]["summary"]["rows"],
                "by_setting": manifest["condition_d"]["summary"]["by_setting"],
                "forward_ids_match_curated": manifest["condition_d"]["forward_ids_match_curated"],
                "oracle": manifest["condition_d"]["oracle_overall"],
            },
            "qa_gate": {"passed": manifest["qa_gate"]["passed"],
                        "multi_answer_questions": manifest["qa_gate"]["multi_answer_questions"]},
            "split_seed": manifest["split"].get("seed"),
            "docs": {"label_guideline": manifest["label_guideline"],
                     "evaluation_plan": manifest["evaluation_plan"]},
            "groups": {name: {"count": group["count"], "digest": group["digest"]}
                       for name, group in manifest["groups"].items()},
            "generation_checks_pass": manifest["generation_checks"]["all_hard_checks_pass"],
            "verification_ok": verification["ok"],
            "verify_errors": verification["errors"],
            "manifest_payload_sha256": manifest["manifest_payload_sha256"],
            "known_limitations": manifest["known_limitations"][:3],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if verification["ok"] else 2

    # ---- v0.1 profile (unchanged shape) ------------------------------------
    run_dir = Path(args.run_dir) if args.run_dir else DEFAULT_RUN_DIR
    conditions = args.condition or [condition for condition in DEFAULT_CONDITIONS
                                    if (run_dir / condition / "run_config.json").exists()]
    if not conditions:
        print(f"no condition sub-directories found under {run_dir}", file=sys.stderr)
        return 2

    manifest = build_manifest(data_root, run_dir, conditions, args.freeze_id)

    if args.self_test:
        return self_test(manifest)

    out_path = Path(args.out) if args.out else default_out_path(data_root, args.freeze_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                        encoding="utf-8")

    verification = verify_manifest(manifest)
    if args.verify_out:
        verify_out = Path(args.verify_out)
        verify_out.parent.mkdir(parents=True, exist_ok=True)
        verify_out.write_text(json.dumps(verification, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    summary = {
        "manifest": str(out_path),
        "profile": "v0.1",
        "freeze_id": manifest["freeze_id"],
        "dataset_version": manifest["dataset"]["protocol_version"],
        "groups": {name: {"count": group["count"], "digest": group["digest"]}
                   for name, group in manifest["groups"].items()},
        "generation_checks_pass": manifest["generation_checks"]["all_hard_checks_pass"],
        "verification_ok": verification["ok"],
        "verify_errors": verification["errors"],
        "code_drift": sorted(manifest["generation_checks"]["code_drift"]),
        "manifest_payload_sha256": manifest["manifest_payload_sha256"],
        "known_limitations": manifest["known_limitations"][:2],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if (verification["ok"] and manifest["generation_checks"]["all_hard_checks_pass"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
