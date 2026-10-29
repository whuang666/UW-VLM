"""Prepare neutral native frames and blank human reviews for the current candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.usim.probe_dev_lift_onset import decode_holds  # noqa: E402

BASE = ROOT / "data/usim_enact"
VERSION = "test-human-acceptance-workpack-20261029-v2"
DATASET = BASE / "usim-enact-v0.2-conservative-balanced-20261029-v1"
TEMPLATE = Path(__file__).parent / "templates/acceptance_workpack.html"
CRITERIA = ["all_scope_objects_identifiable", "all_scope_facts_decidable", "all_transitions_ego_decidable", "frame_selection_rules_satisfied"]
ATTESTATION = "我本人完成本轮复核，独立于初标者；所填判断来自所列图像证据。"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fresh(path: Path, parent: Path) -> Path:
    path = path.resolve()
    if not path.is_relative_to(parent.resolve()) or path == parent.resolve() or path.exists():
        raise ValueError("Output must be a fresh child of the specified review/evidence root")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=BASE / "_review/test_reserve/acceptance_workpack_20261029_v2")
    parser.add_argument("--evidence-out", type=Path, default=ROOT / "docs/WBW/evidence/test_human_acceptance_20261029_v2")
    args = parser.parse_args()
    out = fresh(args.out, BASE / "_review/test_reserve")
    evidence = fresh(args.evidence_out, ROOT / "docs/WBW/evidence")
    snapshot_path = DATASET / "candidate_input_snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    payload = dict(snapshot)
    expected = payload.pop("payload_sha256")
    actual = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
    if actual != expected:
        raise ValueError("Candidate snapshot payload differs")
    for name, digest in snapshot["files"].items():
        path = (DATASET / name).resolve()
        if not path.is_relative_to(DATASET.resolve()) or sha(path) != digest:
            raise ValueError(f"Candidate asset differs: {name}")
    manifest = json.loads((DATASET / "manifest.json").read_text(encoding="utf-8"))
    out.mkdir(parents=True)
    (out / "images").mkdir()
    evidence.mkdir(parents=True)
    episodes, worksheets = [], []
    for entry in manifest["episodes"]:
        key, number = entry["episode_key"], entry["episode_index"]
        annotation_path = DATASET / "annotations/episodes" / f"{key}.json"
        annotation = json.loads(annotation_path.read_text(encoding="utf-8"))
        native = DATASET / "replayed_activities" / key / "external_sensor1"
        video = WORKSPACE / f"usim/train/videos/chunk-{number // 1000:03d}/observation.images.ego/episode_{number:06d}.mp4"
        holds, decoded, length = decode_holds(video)
        frames = []
        for slot, frame in enumerate(annotation["frames"], 1):
            index = frame["frame_index"]
            source = native / f"{index:05d}.png"
            if not np.array_equal(cv2.imread(str(source)), decoded[index]):
                raise ValueError("Native frame differs from sequential source")
            target = out / "images" / f"ep{number:06d}_slot{slot:02d}.png"
            shutil.copyfile(source, target)
            hold = next(h for h in holds if h["start"] <= index <= h["end"])
            stable = [h for h in holds if h["length"] >= 8]
            previous = next((h for h in reversed(stable) if h["end"] < hold["start"]), None)
            following = next((h for h in stable if h["start"] > hold["end"]), None)
            context = []
            for label, adjacent in (("previous", previous), ("following", following)):
                if adjacent is None:
                    continue
                frame_id = (adjacent["start"] + adjacent["end"]) // 2
                image = out / "images" / f"ep{number:06d}_slot{slot:02d}_{label}.png"
                if not cv2.imwrite(str(image), decoded[frame_id]):
                    raise RuntimeError("Could not export context image")
                context.append({"relation": label, "source_frame": frame_id, "path": image.relative_to(out).as_posix(),
                                "sha256": sha(image), "motion_hold": adjacent})
            frames.append({"slot": slot, "source_frame": index, "path": target.relative_to(out).as_posix(),
                           "sha256": sha(target), "dataset_source_path": source.relative_to(WORKSPACE).as_posix(),
                           "motion_hold": hold, "context": context})
        objects = [{k: v for k, v in obj.items() if k in ("object_id", "category", "color", "description")} for obj in annotation["objects"]]
        episode = {"episode_key": key, "episode": number, "task_text": annotation["task_text"],
                   "family": "transfer" if "transfer" in annotation["task_text"] else "pick", "objects": objects,
                   "scope": annotation["relations"], "frames": frames,
                   "source_annotation_path": annotation_path.relative_to(WORKSPACE).as_posix(),
                   "source_annotation_sha256": sha(annotation_path), "source_video_sha256": sha(video),
                   "frame_gaps": [b["source_frame"] - a["source_frame"] for a, b in zip(frames, frames[1:])],
                   "video_frames": length, "proposal_facts_included": False}
        episodes.append(episode)
        worksheets.append({"episode_key": key, "source_annotation_sha256": sha(annotation_path),
                           "frames": [{"source_frame": f["source_frame"], "native_png_sha256": f["sha256"],
                                       "visibility": {obj["object_id"]: None for obj in objects},
                                       "facts": [{"predicate": r[0], "arguments": r[1:], "value": None} for r in episode["scope"]],
                                       "evidence_note": ""} for f in frames],
                           "transitions": [{"from_frame": a["source_frame"], "to_frame": b["source_frame"],
                                            "ego_decidable": None, "evidence_note": ""} for a, b in zip(frames, frames[1:])],
                           "criteria": {name: None for name in CRITERIA}, "decision": None,
                           "decision_reason": "", "review_complete": False,
                           "signature_name": "", "signed_at": "", "attestation": ""})
    packet = {"schema": "usim-human-review-packet/v1", "version": VERSION,
              "candidate_qa_version": snapshot["qa_version"], "candidate_snapshot_path": snapshot_path.relative_to(WORKSPACE).as_posix(),
              "candidate_snapshot_sha256": sha(snapshot_path), "dataset_root": DATASET.relative_to(WORKSPACE).as_posix(),
              "episodes": episodes, "model_api_calls": 0, "proposal_facts_included": False,
              "scope_includes_lifted": False, "independent_acceptance": "0/10",
              "segmentation_note": "Gray MAD<=0.5 segments propose display holds; they are not exact physical-event times or certified render counts"}
    save(out / "packet_manifest.json", packet)
    packet_hash = sha(out / "packet_manifest.json")
    bundle = {"schema": "usim-human-review-bundle/v1", "packet_version": VERSION, "packet_manifest_sha256": packet_hash,
              "reviewer_identity": "", "reviewer_is_human": None, "reviewer_independent_of_first_pass": None,
              "prior_answer_exposure": None, "worksheets": worksheets}
    save(out / "review_templates.json", bundle)
    screen_data = {"packet": packet, "bundle": bundle, "criteria": CRITERIA, "attestation": ATTESTATION}
    encoded = json.dumps(screen_data, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c")
    html = TEMPLATE.read_text(encoding="utf-8").replace("__PACKET_DATA__", encoded)
    (out / "review.html").write_text(html, encoding="utf-8")
    focus = {"version": VERSION, "open_after_own_judgment": True, "issues": [
        {"episode": 1650, "frame": 0, "issue": "Target pipe not identifiable in technical native-frame review; current snapshot cannot be accepted while this remains unresolved"},
        {"episode": 1259, "frames": [57, 170, 203], "issue": "Multiple attempts: close159, open186, close190; command alone cannot establish holding or support"},
        {"episodes": [1378, 1384], "issue": "NearBox means release-position proximity, not merely a visible box; no Lifted or OnSeabed may be inferred at the retained final state"}]}
    save(out / "adjudication_focus.json", focus)
    for name in ("packet_manifest.json", "review_templates.json", "adjudication_focus.json"):
        shutil.copyfile(out / name, evidence / name)
    receipt = {"schema": "usim-human-workpack-build/v1", "packet_version": VERSION,
               "packet_manifest_sha256": packet_hash, "html_sha256": sha(out / "review.html"),
               "template_sha256": sha(TEMPLATE), "builder_sha256": sha(Path(__file__)),
               "local_packet": out.relative_to(WORKSPACE).as_posix(), "episode_count": len(episodes),
               "keyframes": sum(len(e["frames"]) for e in episodes), "blank_worksheets": len(worksheets),
               "independent_acceptance": "0/10", "model_api_calls": 0, "release_eligible": False}
    save(evidence / "build_receipt.json", receipt)
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
