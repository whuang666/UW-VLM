"""Build blind review packets for the independent v0.1 label review (round 2).

The reviewer must first judge every key frame **without seeing the stored fact
values**.  This script therefore emits, per episode:

* episode identity, task text and the declared object / relation *scope*;
* the key frames (index, timestamp, raw and labelled image paths);
* the QA usage summary (which questions use this episode and which image files
  the model actually receives) -- question text is deliberately excluded because
  it contains the action ordering that is part of the label;
* source video paths for the third review pass (physical-event check).

It does NOT emit per-frame fact values, annotation notes, transition texts or
reference answers.  Values are exposed only after the reviewer has frozen pass 1
(see the reviewer task description).

Usage:
    python scripts/usim/make_review_packet.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "data" / "usim_enact" / "usim-enact-v0.1"
REVIEW_ROOT = ROOT / "data" / "usim_enact" / "_review" / "round2"

# Reviewer split: disjoint episode sets, both reviewers apply the same protocol.
ASSIGNMENTS = {
    "reviewer_a": ["usim_train_episode_000200", "usim_train_episode_000201", "usim_train_episode_000552"],
    "reviewer_b": [
        "usim_train_episode_000553",
        "usim_train_episode_000555",
        "usim_train_episode_000556",
        "usim_train_episode_001302",
    ],
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path) -> str:
    """Path relative to the workspace root (some sources live outside ENACT/)."""
    return str(path.relative_to(ROOT.parent) if ROOT in path.parents else path)


def load_qa() -> dict:
    qa_path = DATA_ROOT / "QA" / "train" / "enact_ordering.jsonl"
    records = [json.loads(line) for line in qa_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_episode: dict[str, list] = {}
    for record in records:
        by_episode.setdefault(record["task_name"], []).append(record)
    return by_episode


def build_episode_packet(annotation: dict, qa_records: list, episode_key: str) -> dict:
    raw_dir = DATA_ROOT / "replayed_activities" / episode_key / "external_sensor1"
    segmented_dir = DATA_ROOT / "segmented_activities" / episode_key / "external_sensor1"

    frames = []
    for frame in annotation["frames"]:
        frame_index = int(frame["frame_index"])
        raw_image = raw_dir / f"{frame_index:05d}.png"
        seg_image = segmented_dir / f"{frame_index:05d}.png"
        if not raw_image.exists() or not seg_image.exists():
            raise FileNotFoundError(f"{episode_key}@{frame_index}: missing raw/segmented image")
        frames.append(
            {
                "frame_index": frame_index,
                "timestamp_seconds": frame.get("timestamp_seconds"),
                "raw_image": rel(raw_image),
                "segmented_image": rel(seg_image),
                "raw_image_sha256": sha256(raw_image),
            }
        )

    # Model input surface: list the QA image files per question, question text excluded.
    qa_usage = []
    for record in qa_records:
        qa_usage.append(
            {
                "id": record["id"],
                "type": record["type"],
                "num_images": len(record["images"]),
                "images": [rel(DATA_ROOT / image) for image in record["images"]],
                "chronological_frame_ids": list(record["key_frame_ids"]),
            }
        )

    split = annotation["source_split"]
    episode_index = int(annotation["episode_index"])
    video_ego = ROOT.parent / "usim" / split / "videos" / f"chunk-{episode_index // 1000:03d}" / \
        "observation.images.ego" / f"episode_{episode_index:06d}.mp4"
    parquet = ROOT.parent / "usim" / split / "data" / f"chunk-{episode_index // 1000:03d}" / \
        f"episode_{episode_index:06d}.parquet"

    return {
        "packet_version": "blind-review-20261027",
        "episode_key": episode_key,
        "source_split": split,
        "episode_index": episode_index,
        "task_index": annotation.get("task_index"),
        "task_text": annotation.get("task_text"),
        "objects": annotation["objects"],
        "relation_scope": annotation["relations"],
        "key_frames": frames,
        "qa_usage": qa_usage,
        "source_media": {
            "video_ego": rel(video_ego) if video_ego.exists() else f"MISSING: {video_ego}",
            "parquet": rel(parquet) if parquet.exists() else f"MISSING: {parquet}",
            "dataset": "USIM LeRobot v2.1, split=train, camera=ego, 10 fps, 320x240",
        },
        "disclosure": {
            "facts_hidden": True,
            "note": "关系 scope 已给出，但逐帧取值、标注备注、动作文本与参考答案均未提供。",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(REVIEW_ROOT / "packets"))
    args = parser.parse_args(argv)
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    qa_by_episode = load_qa()
    annotations = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in (DATA_ROOT / "annotations" / "episodes").glob("*.json")
    }

    index = {"packet_version": "blind-review-20261027", "data_root": rel(DATA_ROOT), "reviewers": {}}
    for reviewer, episodes in ASSIGNMENTS.items():
        reviewer_dir = out_root / reviewer
        reviewer_dir.mkdir(parents=True, exist_ok=True)
        packets = []
        for episode_key in episodes:
            if episode_key not in annotations:
                raise KeyError(f"no annotation for {episode_key}")
            packet = build_episode_packet(annotations[episode_key], qa_by_episode.get(episode_key, []), episode_key)
            packet_path = reviewer_dir / f"{episode_key}.json"
            packet_path.write_text(json.dumps(packet, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            packets.append(
                {
                    "episode_key": episode_key,
                    "path": str(packet_path.relative_to(ROOT)),
                    "sha256": sha256(packet_path),
                    "key_frames": len(packet["key_frames"]),
                    "qa_questions": len(packet["qa_usage"]),
                }
            )
        index["reviewers"][reviewer] = {"episodes": packets, "assignment_count": len(packets)}
        summary = {
            "packet_version": index["packet_version"],
            "reviewer": reviewer,
            "episodes": [item["episode_key"] for item in packets],
        }
        (reviewer_dir / "assignment.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    index_path = out_root / "index.json"
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({reviewer: [item["episode_key"] for item in data["episodes"]] for reviewer, data in index["reviewers"].items()}, indent=2, ensure_ascii=False))
    print(f"index: {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
