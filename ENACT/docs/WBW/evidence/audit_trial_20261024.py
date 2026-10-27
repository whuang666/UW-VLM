"""Read-only trial audit; only writes the JSON evidence beside this script.

Run from ENACT with the Python environment recorded in the companion report.
No network requests, source edits, QA regeneration, or original report overwrites.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

from enact.adapters.usim_reader import USIMReader
from scripts.usim.evaluate import USIMEvaluator, load_jsonl, synthetic_predictions

DATA = ROOT / "data/usim_enact/usim-enact-v0.1"
OUTPUT = Path(__file__).with_name("trial_audit_20261024.json")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    qa_path = DATA / "QA/train/enact_ordering.jsonl"
    records = load_jsonl(qa_path)
    sources = sorted((ROOT / "enact").rglob("*.py")) + sorted((ROOT / "scripts/usim").glob("*.py"))
    protected = sources + [DATA / "manifest.json", qa_path]
    protected += sorted((DATA / "annotations/episodes").glob("*.json"))
    protected += sorted((DATA / "evaluation").rglob("*.json"))
    protected += sorted((DATA / "evaluation").rglob("*.jsonl"))
    protected += sorted((DATA / "predictions").glob("*.jsonl"))
    before = {str(p.relative_to(ROOT)): sha(p) for p in protected}
    hash_checks = []
    for name, expected in manifest["annotation_sha256"].items():
        p = DATA / "annotations/episodes" / name
        hash_checks.append({"path": str(p.relative_to(ROOT)), "matches": sha(p) == expected})
    reader = USIMReader(ROOT.parent / "usim", split="train")
    alignment = []
    for episode in manifest["episodes"]:
        p = DATA / "replayed_activities" / episode["episode_key"] / "scene_graph_0.json"
        hash_checks.append({"path": str(p.relative_to(ROOT)), "matches": sha(p) == episode["scene_graph_sha256"]})
        for group in ("frames", "segmented_frames"):
            for frame in episode[group].values():
                p = DATA / frame["path"]
                hash_checks.append({"path": str(p.relative_to(ROOT)), "matches": sha(p) == frame["sha256"]})
        ep = episode["episode_index"]
        check = reader.align_check(ep)
        capture = cv2.VideoCapture(str(reader.video_path(ep, "ego")))
        decoded, pixel_matches = 0, {}
        try:
            while True:
                ok, image = capture.read()
                if not ok:
                    break
                if str(decoded) in episode["frames"]:
                    raw = cv2.imread(str(DATA / episode["frames"][str(decoded)]["path"]))
                    pixel_matches[str(decoded)] = bool(np.array_equal(image, raw))
                decoded += 1
        finally:
            capture.release()
        check["header_frame_count"] = check.pop("decoded_frames")
        check["sequentially_decoded_frames"] = decoded
        check["full_decode_matches_rows"] = decoded == check["parquet_rows"]
        check["keyframe_pixels_match_sequential_video"] = pixel_matches
        alignment.append(check)

    image_checks, image_hashes = [], {}
    for record in records:
        frames = record["key_frame_ids"]
        if "forward" in record["type"]:
            ordered = [None] * (len(frames) - 1)
            for chrono, slot in enumerate(record["gt_answer"]):
                ordered[slot - 1] = frames[chrono + 1]
            frames = [frames[0], *ordered]
        for rel, frame in zip(record["images"], frames):
            p = DATA / rel
            labelled = cv2.imread(str(p))
            raw = cv2.imread(str(DATA / "replayed_activities" / record["task_name"] / "external_sensor1" / f"{int(frame):05d}.png"))
            image_checks.append({"id": record["id"], "image": rel, "expected_frame": frame,
                                 "pixels_below_label_match": bool(np.array_equal(labelled[55:], raw[55:]))})
            image_hashes[rel] = sha(p)

    evaluator, baselines = USIMEvaluator(DATA), {}
    for mode in ("oracle", "identity", "reverse", "random", "empty", "malformed"):
        result = evaluator.evaluate(records, synthetic_predictions(records, mode, seed=0))
        items = [item for bucket in result["items"].values() for item in bucket]
        summary = evaluator.summarise(items)
        existing = json.loads((DATA / "evaluation" / f"baseline_{mode}" / "report.json").read_text(encoding="utf-8"))
        baselines[mode] = {"overall": summary, "skipped_count": len(result["skipped"]),
                           "matches_saved_overall": summary == existing["overall"],
                           "by_setting": {f"{direction}_L{length}": evaluator.summarise(bucket)
                                          for (direction, length), bucket in result["items"].items()}}

    chance = defaultdict(list)
    for record in records:
        accepted, total, pa_sum = 0, 0, 0.0
        verifier = evaluator.verifier(record["task_name"])
        method = verifier.verify_inverse if "inverse" in record["type"] else verifier.verify_forward
        for perm in itertools.permutations(range(1, len(record["gt_answer"]) + 1)):
            score, _ = method(record["key_frame_ids"], record["gt_answer"], list(perm))
            accepted += int(score["task_accuracy"])
            pa_sum += score["pairwise_accuracy"]
            total += 1
        chance[record["type"]].append({"id": record["id"], "accepted": accepted, "permutations": total,
                                       "TA": accepted / total, "PA": pa_sum / total})

    sample = lambda n, valid: {"exact_match": float(valid), "semantic_match": float(valid),
                              "task_accuracy": float(valid), "pairwise_accuracy": float(valid),
                              "parsed": list(range(1, n + 1)) if valid else None, "num_transitions": n}
    mixed = evaluator.summarise([sample(2, True), sample(3, False)])
    absent = USIMEvaluator(DATA / "__audit_nonexistent_root__")
    missing_graph = absent.evaluate(records[:1], {records[0]["id"]: records[0]["gt_answer"]})
    parser_inputs = ["[1, 2]", "Explanation: [1, 2]", "[2, 1] then [1, 2]", "[0, 1]", "[1, 1]", "[1, "]
    parser_probes = {s: evaluator.parse_strict(s, 2) for s in parser_inputs}
    download = ROOT.parent / "usim/_download_manifest.json"
    downloaded = json.loads(download.read_text(encoding="utf-8"))
    annotations = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((DATA / "annotations/episodes").glob("*.json"))]
    predictions = {p.name: dict(Counter(row.get("backend", "unknown") for row in load_jsonl(p)))
                   for p in sorted((DATA / "predictions").glob("*.jsonl"))}
    result = {
        "audited_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "scope": "Trial artifact and evaluator audit; no real model calls or independent semantic annotation review.",
        "python": sys.version, "enact_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "counts": manifest["counts"], "questions": len(records), "unique_qa_ids": len({r["id"] for r in records}),
        "qa_by_type": dict(Counter(r["type"] for r in records)),
        "task_counts": dict(Counter(a["task_text"] for a in annotations)),
        "label_sources": dict(Counter(a.get("label_source") for a in annotations)),
        "annotation_statuses": dict(Counter(a.get("annotation_status") for a in annotations)),
        "download_manifest": {k: downloaded.get(k) for k in ("repo_id", "commit", "file_count", "complete", "verified", "structure", "readability_checks")},
        "download_manifest_matches_trial": sha(download) == manifest["usim"]["download_manifest_sha256"],
        "artifact_hash_checks": hash_checks, "alignment": alignment,
        "question_image_checks": image_checks, "question_image_sha256": image_hashes,
        "baselines": baselines, "prediction_backends": predictions,
        "uniform_permutation_exact_chance": {k: {"questions": len(v), "EM": sum(1 / x["permutations"] for x in v) / len(v),
                                                 "TA": sum(x["TA"] for x in v) / len(v),
                                                 "PA_item_mean": sum(x["PA"] for x in v) / len(v),
                                                 "questions_with_multiple_accepted_permutations": sum(x["accepted"] > 1 for x in v)}
                                              for k, v in chance.items()},
        "probes": {"mixed_valid_missing": {"current_summary": mixed, "fixed_denominator_PA_transition_micro_expected": 2 / 5},
                   "missing_scene_graph": {"input_questions": 1, "scored_questions": sum(map(len, missing_graph["items"].values())),
                                           "skipped": missing_graph["skipped"]}, "strict_parser": parser_probes},
        "source_and_artifact_sha256": before,
        "protected_files_unchanged": all(sha(ROOT / rel) == digest for rel, digest in before.items()),
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "counts": result["counts"], "questions": len(records),
                      "hash_checks": len(hash_checks), "hash_failures": sum(not c["matches"] for c in hash_checks),
                      "image_checks": len(image_checks), "image_mismatches": sum(not c["pixels_below_label_match"] for c in image_checks),
                      "baselines_match": all(b["matches_saved_overall"] for b in baselines.values()),
                      "uniform_chance": result["uniform_permutation_exact_chance"], "probes": result["probes"],
                      "protected_files_unchanged": result["protected_files_unchanged"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
