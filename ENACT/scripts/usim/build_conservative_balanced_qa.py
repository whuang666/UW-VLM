"""Build the agreed balanced QA candidate in a fresh version, entirely offline.

Old diagnostics, source annotations and model runs are inputs only. Successful
construction still leaves release_eligible=false pending independent review.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import redirect_stderr, redirect_stdout
from fractions import Fraction
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import shutil
import socket
import sys

import cv2
import numpy as np
import pyarrow.parquet as pq
from PIL import Image, ImageDraw, ImageFont, __version__ as PILLOW_VERSION

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enact.adapters.usim_annotations import USIMEpisodeAnnotation, SENSOR_NAME  # noqa: E402
from enact.adapters.usim_visual_prompt import resolve_font_path  # noqa: E402
from scripts.usim import audit_qa_validity, build_dataset, evaluate, text_prior_baseline  # noqa: E402

BASE = ROOT / "data/usim_enact"
QA_VERSION = "test-reserve-balanced-qa-20261029-v1"
CANDIDATE_VERSION = "test-reserve-conservative-20261029-v1"
PLAN_DIR = ROOT / "docs/WBW/evidence/test_reserve_permutation_strategy_20261029_v1"
PARENT_DIR = ROOT / "docs/WBW/evidence/test_reserve_conservative_semantic_20261029_v1"
SOURCE_ANNOTATIONS = BASE / "_expansion/annotation_work/test_reserve/conservative_20261029_v1"
OUTPUT_PREFIX = "usim-enact-v0.2-conservative-balanced-"
ACTION_LINE = re.compile(r"^\[Action (\d+)\] ([^\r\n]*)$", re.MULTILINE)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fresh_dataset(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.parent != BASE.resolve() or not resolved.name.startswith(OUTPUT_PREFIX):
        raise ValueError("Use a fresh, separately versioned conservative-balanced dataset child")
    if resolved.exists():
        raise FileExistsError(f"Refusing to overwrite dataset: {resolved}")
    return resolved


def fresh_evidence(path: Path) -> Path:
    resolved = path.resolve()
    parent = (ROOT / "docs/WBW/evidence").resolve()
    if not resolved.is_relative_to(parent) or resolved == parent:
        raise ValueError("Evidence must be a fresh child under docs/WBW/evidence")
    if resolved.exists():
        raise FileExistsError(f"Refusing to overwrite evidence: {resolved}")
    return resolved


def permutation(values: list[int], k: int) -> list[int]:
    if (len(values) != k or any(isinstance(v, bool) or not isinstance(v, int) for v in values)
            or sorted(values) != list(range(1, k + 1))):
        raise ValueError(f"Not a complete 1-based permutation of {k} items: {values}")
    return list(values)


def display_frames(direction: str, frames: list[str], answer: list[int]) -> list[str]:
    k = len(frames) - 1
    permutation(answer, k)
    if direction == "forward":
        return [frames[0]] + [frames[answer.index(slot) + 1] for slot in range(1, k + 1)]
    if direction == "inverse":
        return list(frames)
    raise ValueError("Unknown direction")


def chronological_actions(question: str, answer: list[int]) -> list[str]:
    k = len(answer)
    permutation(answer, k)
    if question.count("## Shuffled Actions") != 1:
        raise ValueError("Missing or repeated inverse action header")
    matches = ACTION_LINE.findall(question.partition("## Shuffled Actions")[2])
    labels = [int(label) for label, _ in matches]
    if len(matches) != k or sorted(labels) != list(range(1, k + 1)):
        raise ValueError("Missing, duplicate or unknown action labels")
    by_label = {int(label): text for label, text in matches}
    return [by_label[label] for label in answer]


def remap_inverse(question: str, old_answer: list[int], new_answer: list[int]) -> str:
    actions = chronological_actions(question, old_answer)
    permutation(new_answer, len(actions))
    head, marker, tail = question.partition("## Shuffled Actions")
    matches = list(ACTION_LINE.finditer(tail))
    block = "\n".join(f"[Action {slot}] {actions[new_answer.index(slot)]}"
                      for slot in range(1, len(actions) + 1))
    return head + marker + tail[:matches[0].start()] + block + tail[matches[-1].end():]


def rendered(source: Path, label: str, font_path: Path) -> tuple[Image.Image, tuple]:
    image = Image.open(source).convert("RGB")
    font = ImageFont.truetype(str(font_path), max(18, image.height // 10))
    draw = ImageDraw.Draw(image)
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            if dx or dy:
                draw.text((8 + dx, 6 + dy), label, font=font, fill=(255, 255, 255))
    draw.text((8, 6), label, font=font, fill=(255, 20, 20))
    box = draw.textbbox((8, 6), label, font=font, stroke_width=2)
    if box[0] < 0 or box[1] < 0 or box[2] > image.width or box[3] > image.height:
        raise ValueError("Visual label exceeds the native image")
    return image, box


def balance_report(records: list[dict]) -> dict:
    result = {}
    for grouping in ("length", "direction_length"):
        groups = defaultdict(list)
        for row in records:
            direction = "forward" if "forward" in row["type"] else "inverse"
            key = (direction + "_" if grouping == "direction_length" else "") + f"L{len(row['gt_answer']) + 1}"
            groups[key].append(row)
        cells, correct = {}, 0
        for key, rows in sorted(groups.items()):
            k = len(rows[0]["gt_answer"])
            space = list(itertools.permutations(range(1, k + 1)))
            counts = Counter(tuple(r["gt_answer"]) for r in rows)
            frequencies = [counts[p] for p in space]
            if max(frequencies) - min(frequencies) > 1 or len(counts) != min(len(rows), len(space)):
                raise ValueError(f"Answer distribution gate failed: {key}")
            best = Fraction(max(frequencies), len(rows))
            floor = Fraction(math.ceil(len(rows) / len(space)), len(rows))
            if best != floor:
                raise ValueError(f"Finite sample constant gate failed: {key}")
            matrix = [[sum(r["gt_answer"][j] == s + 1 for r in rows) for s in range(k)] for j in range(k)]
            correct += max(frequencies)
            cells[key] = {"N": len(rows), "M": len(space), "histogram": {json.dumps(p): counts[p] for p in space},
                          "distinct_answers": len(counts), "best_constant_EM": str(best),
                          "minimum_possible_best_constant_EM": str(floor), "uniform_random_EM": str(Fraction(1, len(space))),
                          "chronological_item_by_display_slot_counts": matrix,
                          "EM_step_percentage_points": str(Fraction(100, len(rows)))}
        result[grouping] = {"cells": cells, "best_constant_overall_EM": str(Fraction(correct, len(records)))}
    result["uniform_random_EM"] = str(sum((Fraction(1, math.factorial(len(r["gt_answer"]))) for r in records), Fraction()) / len(records))
    return result


def verify_bindings(dataset: Path, records: list[dict], parents: dict, planned: dict, font_path: Path) -> dict:
    bindings, touched = [], set()
    for record in records:
        parent = parents[record["parent_diagnostic_id"]]
        row = planned[parent["id"]]
        direction = row["direction"]
        frames = record["key_frame_ids"]
        if frames != parent["key_frame_ids"] or record["gt_answer"] != row["proposed_gt"]:
            raise ValueError("Time order or reference differs from agreed mapping")
        if direction == "forward":
            if record["question"] != parent["question"]:
                raise ValueError("Forward chronological action prose changed")
        else:
            if chronological_actions(record["question"], record["gt_answer"]) != chronological_actions(parent["question"], parent["gt_answer"]):
                raise ValueError("Inverse action content or mapping changed")
            if ACTION_LINE.sub("", record["question"]) != ACTION_LINE.sub("", parent["question"]):
                raise ValueError("Inverse prompt outside action lines changed")
        expected_frames = display_frames(direction, frames, record["gt_answer"])
        if len(record["images"]) != len(expected_frames):
            raise ValueError("Missing or extra presented image")
        annotation_path = dataset / "annotations/episodes" / f"{record['task_name']}.json"
        annotation = USIMEpisodeAnnotation.from_json(annotation_path)
        by_frame = {str(f.frame_index): f for f in annotation.frames}
        for slot, (relative, frame_id) in enumerate(zip(record["images"], expected_frames)):
            target = (dataset / relative).resolve()
            if not target.is_relative_to(dataset.resolve()) or target in touched:
                raise ValueError("Image escape or reused output file")
            touched.add(target)
            source = dataset / "replayed_activities" / record["task_name"] / SENSOR_NAME / f"{int(frame_id):05d}.png"
            label = "Current State" if slot == 0 else f"Next State {slot}"
            expected, bbox = rendered(source, label, font_path)
            with Image.open(target) as actual_image:
                actual = np.asarray(actual_image.convert("RGB"))
            if not np.array_equal(actual, np.asarray(expected)):
                raise ValueError(f"Mislabeled image or wrong source frame: {record['id']}/{slot}")
            native = np.asarray(Image.open(source).convert("RGB"))
            changed = np.any(native != actual, axis=2)
            allowed = np.zeros(changed.shape, bool)
            allowed[max(0, bbox[1]):bbox[3], max(0, bbox[0]):bbox[2]] = True
            if not changed.any() or np.any(changed & ~allowed):
                raise ValueError("No label rendered or source pixels altered outside label region")
            visibility = by_frame[frame_id].visibility
            if not all(v.get("value") is True for v in visibility):
                raise ValueError("Candidate visibility incomplete; do not silently infer it")
            bindings.append({"qa_id": record["id"], "direction": direction, "slot": slot,
                             "source_frame": int(frame_id), "source_png": source.relative_to(dataset).as_posix(),
                             "source_sha256": sha(source), "presented_png": relative, "presented_sha256": sha(target),
                             "label": label, "label_bbox_xyxy": bbox, "annotation_sha256": sha(annotation_path),
                             "candidate_visibility": visibility, "independent_visibility_acceptance": "pending"})
    return {"schema": "usim-balanced-image-bindings/v1", "qa_version": QA_VERSION, "bindings": bindings,
            "presented_images": len(bindings), "outside_label_pixels_preserved": True,
            "source_annotation_visibility_preserved": True, "independent_visual_acceptance": "0/10"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=BASE / "usim-enact-v0.2-conservative-balanced-20261029-v1")
    parser.add_argument("--evidence-out", type=Path, default=ROOT / "docs/WBW/evidence/test_reserve_balanced_qa_20261029_v1")
    args = parser.parse_args()
    dataset, evidence = fresh_dataset(args.out), fresh_evidence(args.evidence_out)
    preview_path = PLAN_DIR / "strategy_preview.json"
    preview = load(preview_path)
    if preview["version"] != "test-reserve-balanced-labels-draft-v1" or len(preview["schedule"]) != 20:
        raise ValueError("Unexpected agreed mapping")
    parent_path = PARENT_DIR / "diagnostic_full_chain_qa.jsonl"
    parents = {r["id"]: r for r in evaluate.load_jsonl(parent_path)}
    planned = {r["parent_diagnostic_id"]: r for r in preview["schedule"]}
    if len(parents) != 20 or set(planned) != set(parents) or len(planned) != 20:
        raise ValueError("Mapping/diagnostic identity coverage differs")
    font_name = resolve_font_path()
    if not font_name:
        raise ValueError("No recorded real font available; no silent bitmap fallback")
    font_path = Path(font_name)
    old_manifest = load(PARENT_DIR / "analysis_plan.json")
    for key, digest in old_manifest["candidate_annotation_sha256"].items():
        if sha(SOURCE_ANNOTATIONS / f"{key}.json") != digest:
            raise ValueError(f"Candidate annotation changed: {key}")
    for relative, digest in old_manifest["raw_source_sha256"].items():
        if sha(WORKSPACE / "usim" / relative) != digest:
            raise ValueError(f"Pinned source changed: {relative}")
    dataset.mkdir()
    evidence.mkdir(parents=True)
    annotations = dataset / "annotations/episodes"
    annotations.mkdir(parents=True)
    for key in old_manifest["candidate_annotation_sha256"]:
        shutil.copyfile(SOURCE_ANNOTATIONS / f"{key}.json", annotations / f"{key}.json")
    code_files = [Path(__file__), ROOT / "scripts/usim/build_dataset.py", ROOT / "scripts/usim/evaluate.py",
                  ROOT / "scripts/usim/audit_qa_validity.py", ROOT / "scripts/usim/text_prior_baseline.py",
                  ROOT / "enact/core/evaluators.py"]
    plan = {"schema": "usim-balanced-qa-build-plan/v1", "qa_version": QA_VERSION,
            "candidate_version": CANDIDATE_VERSION, "mapping_sha256": sha(preview_path),
            "mapping_version": preview["version"], "seed": preview["seed"], "parent_qa_sha256": sha(parent_path),
            "candidate_annotation_sha256": old_manifest["candidate_annotation_sha256"],
            "raw_source_sha256": old_manifest["raw_source_sha256"],
            "code_sha256": {p.relative_to(WORKSPACE).as_posix(): sha(p) for p in code_files},
            "renderer": {"version": "strict-red-white-label-v1", "font_path": str(font_path), "font_sha256": sha(font_path),
                         "pillow": PILLOW_VERSION, "font_size_rule": "max(18,height//10)", "xy": [8, 6], "outline_radius": 2},
            "question_count": 20, "episode_count": 10, "model_api_calls": 0, "release_eligible": False}
    save(evidence / "build_plan.json", plan)
    attempts = []

    def deny_connection(*a, **kw):
        attempts.append("socket connection")
        raise RuntimeError("Network disabled during QA construction and scoring")

    old_connect, old_connect_ex = socket.socket.connect, socket.socket.connect_ex
    socket.socket.connect, socket.socket.connect_ex = deny_connection, deny_connection
    try:
        with (evidence / "execution.txt").open("w", encoding="utf-8", newline="\n") as log, redirect_stdout(log), redirect_stderr(log):
            if build_dataset.main(["--dataset-root", str(WORKSPACE / "usim"), "--annotations", str(annotations), "--out", str(dataset)]) != 0:
                raise RuntimeError("Dataset compilation failed")
            manifest_path = dataset / "manifest.json"
            manifest = load(manifest_path)
            manifest.update({"protocol_version": QA_VERSION, "candidate_batch_version": CANDIDATE_VERSION,
                             "source_annotation_protocol_versions": ["usim-enact-v0.2"], "qa_version": QA_VERSION,
                             "release_eligible": False, "independent_acceptance": "0/10"})
            save(manifest_path, manifest)
            records = []
            for mapping in preview["schedule"]:
                parent = parents[mapping["parent_diagnostic_id"]]
                frames = list(parent["key_frame_ids"])
                if frames != mapping["chronological_frame_ids"] or parent["task_name"] != mapping["episode_key"]:
                    raise ValueError("Preview binds a different chain")
                answer = permutation(mapping["proposed_gt"], len(frames) - 1)
                direction = mapping["direction"]
                identity = hashlib.sha256(canonical([QA_VERSION, plan["mapping_sha256"], parent["id"], answer])).hexdigest()[:20]
                qid = f"balanced20261029_v1_{identity}"
                question = parent["question"] if direction == "forward" else remap_inverse(parent["question"], parent["gt_answer"], answer)
                shown = display_frames(direction, frames, answer)
                images = []
                for slot, frame in enumerate(shown):
                    source = dataset / "replayed_activities" / parent["task_name"] / SENSOR_NAME / f"{int(frame):05d}.png"
                    target = dataset / "QA/images" / parent["type"] / parent["task_name"] / f"{qid}_slot_{slot:02d}.png"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    picture, _ = rendered(source, "Current State" if slot == 0 else f"Next State {slot}", font_path)
                    picture.save(target)
                    images.append(target.relative_to(dataset).as_posix())
                records.append({"id": qid, "type": parent["type"], "task_name": parent["task_name"],
                                "key_frame_ids": frames, "images": images, "question": question,
                                "options": list(parent["options"]), "gt_answer": answer,
                                "qa_version": QA_VERSION, "candidate_batch_version": CANDIDATE_VERSION,
                                "parent_diagnostic_id": parent["id"]})
            if len({r["id"] for r in records}) != 20 or set(r["id"] for r in records) & set(parents):
                raise ValueError("ID collision or old IDs reused")
            qa_path = dataset / "QA/candidate/enact_ordering_balanced.jsonl"
            qa_path.parent.mkdir(parents=True)
            qa_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
            bindings = verify_bindings(dataset, records, parents, planned, font_path)
            save(evidence / "image_bindings.json", bindings)
            distributions = balance_report(records)
            save(evidence / "answer_distribution.json", distributions)
            for key, expected in (("length", "9/20"), ("direction_length", "1/2")):
                if distributions[key]["best_constant_overall_EM"] != expected:
                    raise ValueError("Distribution differs from agreed preview")
            if audit_qa_validity.main(["--data-root", str(dataset), "--qa", str(qa_path), "--out", str(evidence / "permutation_audit.json"), "--skip-synthetic-baselines"]) != 0:
                raise RuntimeError("Permutation audit failed")
            audited = load(evidence / "permutation_audit.json")
            if not all(q["accepted_count"] == 1 and q["gt_accepted"] and not q["empty_reference_transitions"] for q in audited["questions"]):
                raise ValueError("Actual QA uniqueness gate failed")
            baseline_reports = {}
            for mode in ("oracle", "identity", "reverse"):
                report_path = evidence / f"{mode}.json"
                if evaluate.main(["--data-root", str(dataset), "--qa", str(qa_path), "--synthetic", mode, "--out", str(report_path)]) != 0:
                    raise RuntimeError(f"Synthetic {mode} failed")
                baseline_reports[mode] = load(report_path)
            oracle = baseline_reports["oracle"]["overall"]
            if not all(oracle[m] == 1 for m in ("EM", "TA", "PA_item_mean", "PA_transition_micro")):
                raise ValueError("Oracle gate failed")
            evaluator = evaluate.USIMEvaluator(dataset)
            for grouping in ("length", "direction_length"):
                cells = defaultdict(list)
                for record in records:
                    direction = "forward" if "forward" in record["type"] else "inverse"
                    cells[(direction if grouping == "direction_length" else "", len(record["gt_answer"]))].append(record)
                answers = {}
                for rows in cells.values():
                    counts = Counter(tuple(r["gt_answer"]) for r in rows)
                    chosen = min(counts, key=lambda p: (-counts[p], p))
                    answers.update({r["id"]: list(chosen) for r in rows})
                result = evaluator.evaluate(records, answers)
                score = evaluator.summarise([item for cell in result["items"].values() for item in cell])
                expected_score = float(Fraction(distributions[grouping]["best_constant_overall_EM"]))
                if score["EM"] != expected_score or score["TA"] != expected_score:
                    raise ValueError("Scored constant baseline differs from the distribution bound")
                baseline_reports[f"best_{grouping}_constant"] = {"overall": score}
                save(evidence / f"best_{grouping}_constant.json", {"posthoc_distribution_audit": True, "overall": score,
                      "answers": answers, "readable_fields": grouping, "model_api_calls": 0})
            if text_prior_baseline.main(["--data-root", str(dataset), "--qa", str(qa_path), "--out", str(evidence / "text_baseline.json"),
                                         "--predictions-out", str(evidence / "text_baseline_answers.jsonl")]) != 0:
                raise RuntimeError("Text baseline failed")
            # Re-decode sequentially: avoid taking random-seek alignment on faith.
            verified_frames = 0
            for entry in manifest["episodes"]:
                number = entry["episode_index"]
                video = WORKSPACE / f"usim/train/videos/chunk-{number // 1000:03d}/observation.images.ego/episode_{number:06d}.mp4"
                capture = cv2.VideoCapture(str(video))
                wanted, found, index = set(map(int, entry["key_frame_ids"])), set(), 0
                while True:
                    ok, pixels = capture.read()
                    if not ok:
                        break
                    if index in wanted:
                        for branch in ("replayed_activities", "segmented_activities"):
                            target = cv2.imread(str(dataset / branch / entry["episode_key"] / SENSOR_NAME / f"{index:05d}.png"))
                            if target is None or not np.array_equal(target, pixels):
                                raise ValueError("Compiled native frame differs from sequential source")
                        found.add(index)
                        verified_frames += 1
                    index += 1
                capture.release()
                if found != wanted:
                    raise ValueError("A native source frame is unavailable")
                parquet = WORKSPACE / f"usim/train/data/chunk-{number // 1000:03d}/episode_{number:06d}.parquet"
                if pq.read_metadata(parquet).num_rows != index:
                    raise ValueError("Source video/Parquet length differs")
    finally:
        socket.socket.connect, socket.socket.connect_ex = old_connect, old_connect_ex
        save(evidence / "network_receipt.json", {"socket_attempts": len(attempts), "model_api_calls": 0})
    if attempts:
        raise RuntimeError("Unexpected network attempt")
    snapshot = {"schema": "usim-balanced-candidate-input-snapshot/v1", "qa_version": QA_VERSION,
                "candidate_batch_version": CANDIDATE_VERSION, "release_eligible": False,
                "root": dataset.relative_to(WORKSPACE).as_posix(), "qa": qa_path.relative_to(dataset).as_posix(),
                "qa_sha256": sha(qa_path), "build_plan_sha256": sha(evidence / "build_plan.json"),
                "files": {p.relative_to(dataset).as_posix(): sha(p) for p in sorted(dataset.rglob('*')) if p.is_file()},
                "independent_acceptance": "0/10", "execution_protocol_frozen": False}
    snapshot["payload_sha256"] = hashlib.sha256(canonical(snapshot)).hexdigest()
    save(dataset / "candidate_input_snapshot.json", snapshot)
    save(evidence / "candidate_input_snapshot.json", snapshot)
    save(evidence / "summary.json", {"qa_version": QA_VERSION, "dataset": dataset.relative_to(WORKSPACE).as_posix(),
         "qa": qa_path.relative_to(WORKSPACE).as_posix(), "questions": 20, "episodes": 10,
         "native_frames_source_verified": verified_frames, "presented_images_bound": bindings["presented_images"],
         "unique_accepted_count_histogram": audited["overall"]["accepted_count_histogram"],
         "permutation_instances_evaluated": sum(q["permutations_total"] for q in audited["questions"]),
         "uniform_random_EM": distributions["uniform_random_EM"], "baselines": baseline_reports,
         "candidate_snapshot_sha256": sha(dataset / "candidate_input_snapshot.json"),
         "mechanical_gate_passed": True, "release_eligible": False, "independent_acceptance": "0/10", "model_api_calls": 0})
    shutil.copyfile(qa_path, evidence / "enact_ordering_balanced.jsonl")
    print(json.dumps({"qa_version": QA_VERSION, "questions": 20, "bound_images": bindings["presented_images"],
                      "source_frames": verified_frames, "uniform_random_EM": distributions["uniform_random_EM"],
                      "unique_answers": audited["overall"]["accepted_count_histogram"], "oracle": oracle["EM"],
                      "model_api_calls": 0, "release_eligible": False}))


if __name__ == "__main__":
    main()
