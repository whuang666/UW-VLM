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
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
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
    "usim_strict_v0.2 does not reject empty visible reference transitions; the proposed "
    "usim_strict_v0.3 contract adds that guard (see data/usim_enact/_protocol/contract/check_scoring_contract_v2.json)",
    "v0.1 QA contains 0 multi-answer questions, so TA is numerically equal to EM and the "
    "multi-answer path is not exercised by the frozen set",
    "v0.1 has 7 episodes / 70 questions; episode-grouped statistics are development diagnostics only",
    "full_v1/run_config.json predates the image_condition field; the condition can be cross-checked "
    "from input_manifest image tokens but is not a recorded config key",
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
        "scorer_entrypoint": "scripts/usim/evaluate.py USIMEvaluator",
        "proposed_contract_versions": {
            "usim_strict_v0.3": "reference-transition guard: empty visible signatures are rejected",
        },
        "known_gaps": KNOWN_LIMITATIONS[:2],
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


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--condition", action="append", default=[],
                        help="condition sub-directory under --run-dir; repeatable "
                             "(default: full_v1, condB_zoom, condC_text_only if present)")
    parser.add_argument("--freeze-id", default=datetime.now(TZ_SHANGHAI).strftime("%Y%m%d"))
    parser.add_argument("--out", default="")
    parser.add_argument("--verify", default="", help="verify an existing manifest and exit")
    parser.add_argument("--verify-out", default="", help="optional JSON report path for --verify")
    parser.add_argument("--root", default="", help="override the recorded root when verifying")
    parser.add_argument("--self-test", action="store_true", help="run tamper-detection self-tests")
    parser.add_argument("--no-verify-after-generate", action="store_true")
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
                   "groups": {name: {"ok": block["ok"], "files": block["actual_count"]}
                              for name, block in report["groups"].items()},
                   "payload_hash_match": report["manifest_payload_sha256"]["match"],
                   "errors": report["errors"]}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 2

    data_root = Path(args.data_root)
    run_dir = Path(args.run_dir)
    if not data_root.exists():
        print(f"data root not found: {data_root}", file=sys.stderr)
        return 2
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
