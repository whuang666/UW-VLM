"""Audit the conservative candidate batch offline, without changing source labels.

Creates one full-chain diagnostic QA per episode/direction, enumerates all answer
permutations with the stock verifier, and runs the stock synthetic oracle. These
are audit fixtures, not a released test set or real model predictions.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import shutil
import socket
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enact.adapters.usim_annotations import USIMEpisodeAnnotation, SENSOR_NAME  # noqa: E402
from scripts.usim import audit_qa_validity, build_dataset, build_qa, evaluate  # noqa: E402

BASE = ROOT / "data/usim_enact"
BATCH = "test-reserve-conservative-20261029-v1"
MANIFEST = ROOT / "docs/WBW/evidence/test_reserve_conservative_20261029/conservative_manifest.json"
SOURCES = BASE / "_expansion/annotation_work/test_reserve/conservative_20261029_v1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fresh_child(path: Path, parent: Path) -> Path:
    result = path.resolve()
    if not result.is_relative_to(parent.resolve()) or result == parent.resolve():
        raise ValueError(f"Output must be a fresh child of {parent}")
    if result.exists():
        raise FileExistsError(f"Refusing to overwrite: {result}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=BASE / "_review/test_reserve/conservative_semantic_20261029_v1")
    parser.add_argument("--evidence-out", type=Path,
                        default=ROOT / "docs/WBW/evidence/test_reserve_conservative_semantic_20261029_v1")
    args = parser.parse_args()
    out = fresh_child(args.out, BASE / "_review/test_reserve")
    evidence = fresh_child(args.evidence_out, ROOT / "docs/WBW/evidence")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest["version"] != BATCH or len(manifest["items"]) != 10:
        raise ValueError("Unexpected candidate batch")
    assignment = json.loads((BASE / "_expansion/annotation_assignment.json").read_text(encoding="utf-8"))
    reserved = set(assignment["test_reserve"])
    items, source_hashes = [], {}
    for entry in manifest["items"]:
        key = f"usim_train_episode_{entry['episode']:06d}"
        path = SOURCES / f"{key}.json"
        annotation = USIMEpisodeAnnotation.from_json(path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        if key not in reserved or annotation.episode_key != key or annotation.source_split != "train":
            raise ValueError(f"Unexpected identity: {key}")
        frames = [frame.frame_index for frame in annotation.frames]
        relations = [relation[0] for relation in annotation.relations]
        if frames != entry["frames"] or set(relations) != set(entry["relations"]):
            raise ValueError(f"Candidate/manifest differs: {key}")
        if "Lifted" in relations or (entry["family"] == "transfer" and "OnSeabed" in relations):
            raise ValueError(f"Conservative scope gate failed: {key}")
        if len(frames) != (3 if entry["family"] == "pick" else 4):
            raise ValueError(f"Unexpected full-chain length: {key}")
        if raw.get("conservative_version") != BATCH:
            raise ValueError(f"Missing candidate version: {key}")
        source_hashes[key] = digest(path)
        items.append((entry, path, annotation))
    if len(source_hashes) != 10 or set(source_hashes) != reserved:
        raise ValueError("Duplicate or incomplete reserved-episode coverage")
    expected_path = WORKSPACE / "tools/_hfcache/expected.json"
    expected = {item["path"]: item for item in json.loads(expected_path.read_text(encoding="utf-8"))}
    raw_manifest = json.loads((WORKSPACE / "usim/_download_manifest.json").read_text(encoding="utf-8"))
    if digest(expected_path) != raw_manifest["expected_manifest_sha256"]:
        raise ValueError("Pinned source inventory differs")
    raw_sources = {}
    for entry, _, _ in items:
        number = entry["episode"]
        chunk = f"chunk-{number // 1000:03d}"
        for relative in (f"train/data/{chunk}/episode_{number:06d}.parquet",
                         f"train/videos/{chunk}/observation.images.ego/episode_{number:06d}.mp4"):
            actual = digest(WORKSPACE / "usim" / relative)
            if actual != expected[relative]["sha256"]:
                raise ValueError(f"Pinned source hash mismatch: {relative}")
            raw_sources[relative] = actual
    out.mkdir(parents=True)
    evidence.mkdir(parents=True)
    staged = out / "source_annotations"
    staged.mkdir()
    for _, path, _ in items:
        shutil.copyfile(path, staged / path.name)
    code_paths = [Path(__file__), ROOT / "scripts/usim/build_dataset.py", ROOT / "scripts/usim/build_qa.py",
                  ROOT / "scripts/usim/audit_qa_validity.py", ROOT / "scripts/usim/evaluate.py",
                  ROOT / "enact/core/evaluators.py", ROOT / "enact/core/forward_world_modeling.py",
                  ROOT / "enact/core/inverse_world_modeling.py"]
    plan = {"schema": "usim-conservative-semantic-plan/v1", "candidate_version": BATCH,
            "audit_version": "conservative-semantic-20261029-v1", "candidate_manifest_sha256": digest(MANIFEST),
            "candidate_annotation_sha256": source_hashes, "raw_source_sha256": raw_sources,
            "source_commit": raw_manifest["commit"], "adapter_protocol_versions": sorted({a.protocol_version for _, _, a in items}),
            "code_sha256": {str(p.relative_to(WORKSPACE)).replace('\\', '/'): digest(p) for p in code_paths},
            "planned_questions": 20, "directions": ["forward", "inverse"],
            "frame_selection": "all retained frames, one diagnostic QA per episode/direction; no subpaths",
            "generator_randomness": "stock per-call seed42 retained; diagnostic answer distribution is not a test design",
            "gates": ["all 10 episodes", "20 distinct full-chain questions", "nonempty reference transitions",
                      "reference accepted", "exactly one accepted permutation per question", "oracle all metrics 1"],
            "model_api_calls": 0, "original_annotation_writes": 0, "formal_test_release": False}
    write_json(evidence / "analysis_plan.json", plan)
    attempts = []

    def deny_connection(*args, **kwargs):
        attempts.append("socket connection")
        raise RuntimeError("Network disabled during candidate audit")

    original_connect, original_connect_ex = socket.socket.connect, socket.socket.connect_ex
    socket.socket.connect = deny_connection
    socket.socket.connect_ex = deny_connection
    dataset = out / "dataset"
    qa_path = out / "diagnostic_full_chain_qa.jsonl"
    try:
        with (evidence / "execution.txt").open("w", encoding="utf-8", newline="\n") as log, redirect_stdout(log), redirect_stderr(log):
            code = build_dataset.main(["--dataset-root", str(WORKSPACE / "usim"), "--annotations", str(staged), "--out", str(dataset)])
            if code != 0:
                raise RuntimeError(f"Dataset compilation failed: {code}")
            compiled_manifest_path = dataset / "manifest.json"
            compiled_manifest = json.loads(compiled_manifest_path.read_text(encoding="utf-8"))
            compiled_manifest.update({"protocol_version": BATCH, "candidate_batch_version": BATCH,
                                      "adapter_protocol_versions": plan["adapter_protocol_versions"],
                                      "audit_only": True, "release_eligible": False})
            write_json(compiled_manifest_path, compiled_manifest)
            verified_native_frames = 0
            for entry, _, annotation in items:
                number = entry["episode"]
                video = WORKSPACE / f"usim/train/videos/chunk-{number // 1000:03d}/observation.images.ego/episode_{number:06d}.mp4"
                capture = cv2.VideoCapture(str(video))
                if not capture.isOpened():
                    raise RuntimeError(f"Cannot reopen pinned source: {video}")
                wanted = {f.frame_index for f in annotation.frames}
                decoded = 0
                found = set()
                while True:
                    ok, frame = capture.read()
                    if not ok:
                        break
                    if decoded in wanted:
                        for branch in ("replayed_activities", "segmented_activities"):
                            emitted = cv2.imread(str(dataset / branch / annotation.episode_key / SENSOR_NAME / f"{decoded:05d}.png"))
                            if emitted is None or not np.array_equal(frame, emitted):
                                raise RuntimeError(f"Source frame differs: {annotation.episode_key}/{decoded}/{branch}")
                        found.add(decoded)
                        verified_native_frames += 1
                    decoded += 1
                capture.release()
                if found != wanted:
                    raise RuntimeError(f"Missing source frames: {annotation.episode_key}")
            tasks = build_qa.load_task_data(dataset)
            if {task.task_name for task in tasks} != reserved:
                raise RuntimeError("Task compilation skipped or added an episode")
            tasks_by_key = {task.task_name: task for task in tasks}
            records = []
            for _, _, annotation in items:
                for direction in ("forward", "inverse"):
                    generator = build_qa.build_generator(direction, len(annotation.frames))
                    generated = generator.generate(tasks_by_key[annotation.episode_key], num_to_sample=1)
                    if len(generated) != 1:
                        raise RuntimeError(f"Expected one full-chain QA: {annotation.episode_key}/{direction}")
                    record = generated[0].to_dict()
                    if list(record["key_frame_ids"]) != [str(f.frame_index) for f in annotation.frames]:
                        raise RuntimeError("Generator selected a subpath")
                    record.update({"generator_id": record["id"], "id": "conservative_semantic_v1_" + record["id"],
                                   "candidate_batch_version": BATCH, "audit_only": True})
                    records.append(record)
            if len(records) != 20 or len({r["id"] for r in records}) != 20:
                raise RuntimeError("Diagnostic QA coverage differs")
            qa_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
            code = audit_qa_validity.main(["--data-root", str(dataset), "--qa", str(qa_path), "--out",
                                           str(evidence / "permutation_audit.json"), "--skip-synthetic-baselines"])
            if code != 0:
                raise RuntimeError(f"Stock permutation audit failed: {code}")
            code = evaluate.main(["--data-root", str(dataset), "--qa", str(qa_path), "--synthetic", "oracle",
                                  "--name", "conservative_candidate_synthetic_oracle", "--out", str(evidence / "oracle.json")])
            if code != 0:
                raise RuntimeError(f"Synthetic oracle failed: {code}")
    finally:
        socket.socket.connect, socket.socket.connect_ex = original_connect, original_connect_ex
        write_json(evidence / "network_receipt.json", {"socket_attempts": len(attempts), "model_api_calls": 0})
    audit = json.loads((evidence / "permutation_audit.json").read_text(encoding="utf-8"))
    oracle = json.loads((evidence / "oracle.json").read_text(encoding="utf-8"))
    bad = [r["id"] for r in audit["questions"] if r["accepted_count"] != 1 or not r["gt_accepted"] or r["empty_reference_transitions"]]
    oracle_ok = all(oracle["overall"][metric] == 1 for metric in ("EM", "TA", "PA_item_mean", "PA_transition_micro"))
    unique_ok = not bad and len(audit["questions"]) == 20
    exact_uniform = sum((Fraction(1, r["permutations_total"]) for r in audit["questions"]), Fraction()) / 20
    summary = {"schema": "usim-conservative-semantic-result/v1", "candidate_version": BATCH,
               "questions": 20, "episodes": 10, "by_setting": audit["by_setting"],
               "source_hash_checks": len(raw_sources), "native_source_frames_verified": verified_native_frames,
               "permutation_instances_evaluated": sum(r["permutations_total"] for r in audit["questions"]),
               "accepted_count_histogram": audit["overall"]["accepted_count_histogram"], "unique_gate_passed": unique_ok,
               "non_unique_or_invalid_ids": bad, "empty_reference_transitions": audit["overall"]["empty_reference_transitions"],
               "gt_rejected_questions": audit["overall"]["gt_rejected_questions"], "oracle": oracle["overall"],
               "oracle_gate_passed": oracle_ok, "uniform_random_EM_exact": str(exact_uniform),
               "answer_distribution": dict(Counter(json.dumps(r["gt_answer"]) for r in records)),
               "diagnostic_qa_sha256": digest(qa_path), "diagnostic_qa_path": str(qa_path.relative_to(WORKSPACE)).replace('\\', '/'),
               "dataset_path": str(dataset.relative_to(WORKSPACE)).replace('\\', '/'),
               "mechanical_gate_passed": unique_ok and oracle_ok and not attempts,
               "visual_semantic_truth_validated": False, "transfer_ego_adjudication_complete": False,
               "independent_acceptance": "0/10", "formal_test_release": False, "model_api_calls": 0}
    write_json(evidence / "summary.json", summary)
    shutil.copyfile(qa_path, evidence / "diagnostic_full_chain_qa.jsonl")
    shutil.copyfile(dataset / "manifest.json", evidence / "compiled_dataset_manifest.json")
    print(json.dumps({key: summary[key] for key in ("questions", "episodes", "permutation_instances_evaluated",
                     "accepted_count_histogram", "unique_gate_passed", "oracle_gate_passed", "uniform_random_EM_exact",
                     "mechanical_gate_passed", "independent_acceptance", "model_api_calls")}, ensure_ascii=False))
    if not summary["mechanical_gate_passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
