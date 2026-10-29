"""Prepare an offline, dev-only visual feasibility packet without assigning labels.

All episode identities come from the existing 19-episode dev split. Original
annotations, QA, model runs and test-reserve records are never written. Images
are temporary review material; compact provenance and hold metadata are JSON.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

import cv2
import numpy as np
import pyarrow.parquet as pq
from PIL import Image, ImageDraw, ImageFont

WORKSPACE = Path(__file__).resolve().parents[3]
BASE = WORKSPACE / "ENACT/data/usim_enact"
VERSION = "dev-lift-onset-feasibility-v1"
REVIEW_PARENT = BASE / "_review/dev_lift_onset"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def local_path(path: Path) -> str:
    return path.resolve().relative_to(WORKSPACE).as_posix()


def resolve_output(path: Path) -> Path:
    result = path.resolve()
    if not result.is_relative_to(REVIEW_PARENT.resolve()) or result == REVIEW_PARENT.resolve():
        raise ValueError("Output must be a fresh child of the dev-only review directory")
    if result.exists():
        raise FileExistsError(f"Refusing to overwrite review material: {result}")
    return result


def signal_probe(state: np.ndarray) -> dict:
    if state.ndim != 2 or state.shape[1] < 29 or not np.isfinite(state[:, [0, 28]]).all():
        raise ValueError("Missing or non-finite source signal")
    closed = state[:, 0] > 0.004
    events = [{"frame": i, "event": "close" if closed[i] else "open"}
              for i in range(1, len(state)) if closed[i] != closed[i - 1]]
    closes = [event["frame"] for event in events if event["event"] == "close"]
    if not closes:
        raise ValueError("No close event")
    close = closes[-1]
    lo, hi = max(0, close - 20), min(len(state), close + 120)
    minimum = lo + int(np.argmin(state[lo:hi, 28]))
    baseline = float(state[minimum, 28])
    onset = next((i for i in range(minimum, len(state) - 10)
                  if state[i, 28] >= baseline + 0.05
                  and np.all(state[i + 1:i + 11, 28] >= baseline + 0.02)), None)
    raw = None if onset is None else [onset + 40, onset + 60]
    available = None if raw is None else [max(0, raw[0]), min(len(state) - 1, raw[1])]
    if available is not None and available[0] > available[1]:
        available = None
    release = next((e["frame"] for e in events if e["event"] == "open" and e["frame"] > close), None)
    return {"events": events, "main_close_signal_candidate": close,
            "main_close_visually_confirmed": False, "release_after_main_close": release,
            "baseline_search_half_open": [lo, hi], "minimum_frame": minimum,
            "minimum_value": baseline, "robot_rise_proxy_frame": onset,
            "proxy_window_raw": raw, "proxy_window_available": available}


def decode_holds(video: Path) -> tuple[list[dict], list[np.ndarray], int]:
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise ValueError(f"Cannot open video: {video}")
    holds, frames = [], []
    start, previous = 0, None
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(float)
        if previous is not None and float(np.abs(gray - previous).mean()) > 0.5:
            holds.append({"index": len(holds), "start": start, "end": len(frames) - 1,
                          "length": len(frames) - start})
            start = len(frames)
        previous = gray
        frames.append(frame)
    capture.release()
    if not frames:
        raise ValueError("No decoded video frames")
    holds.append({"index": len(holds), "start": start, "end": len(frames) - 1,
                  "length": len(frames) - start})
    return holds, frames, len(frames)


def save_sheet(tiles: list[tuple[str, Image.Image]], target: Path) -> None:
    width, height, columns = 480, 405, 3
    canvas = Image.new("RGB", (columns * width, ((len(tiles) + columns - 1) // columns) * height), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 17)
    for i, (label, picture) in enumerate(tiles):
        x, y = (i % columns) * width, (i // columns) * height
        draw.multiline_text((x + 4, y + 2), label, font=font, fill="black", spacing=1)
        canvas.paste(picture.resize((480, 360), Image.Resampling.NEAREST), (x, y + 44))
    canvas.save(target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REVIEW_PARENT / "round_20261029_v1")
    args = parser.parse_args()
    out = resolve_output(args.out)
    split_path = BASE / "runs/qwen3.8-max/v02_dev_001/inputs/splits_manifest.json"
    split = json.loads(split_path.read_text(encoding="utf-8"))
    keys = split["splits"]["dev"]["episodes"]
    forbidden = set(split["splits"]["val"]["episodes"])
    assignment_path = BASE / "_expansion/annotation_assignment.json"
    forbidden.update(json.loads(assignment_path.read_text(encoding="utf-8"))["test_reserve"])
    if len(keys) != 19 or len(set(keys)) != 19 or set(keys) & forbidden:
        raise ValueError("Unexpected dev scope or held-out episode overlap")
    qa_path = BASE / "runs/qwen3.8-max/v02_dev_001/inputs/dev.jsonl"
    if sha256(qa_path) != split["splits"]["dev"]["sha256"]:
        raise ValueError("Dev QA differs from its recorded split digest")
    qa = [json.loads(line) for line in qa_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    counts = Counter(row["task_name"] for row in qa)
    if len(qa) != 84 or set(counts) != set(keys):
        raise ValueError("Dev QA coverage differs")
    expected_path = WORKSPACE / "tools/_hfcache/expected.json"
    expected = {item["path"]: item for item in json.loads(expected_path.read_text(encoding="utf-8"))}
    source_manifest_path = WORKSPACE / "usim/_download_manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    if sha256(expected_path) != source_manifest["expected_manifest_sha256"]:
        raise ValueError("Pinned source inventory digest differs")
    draft = WORKSPACE / "docs/workbuddyRead/test_lift_onset_pick_transfer_draft_20261029_zh.md"
    plan = {"schema": "usim-dev-lift-feasibility-plan/v1", "version": VERSION,
            "created_at_utc": datetime.now(timezone.utc).isoformat(), "draft_path": local_path(draft),
            "draft_sha256": sha256(draft), "probe_sha256": sha256(Path(__file__)),
            "split_manifest_sha256": sha256(split_path), "dev_qa_sha256": sha256(qa_path),
            "source_commit": source_manifest["commit"], "expected_inventory_sha256": sha256(expected_path),
            "episode_keys": keys, "questions": 84, "forbidden_overlap": [],
            "hold_segmentation": {"measure": "adjacent decoded gray mean absolute difference",
                                  "new_hold_when_above": 0.5, "minimum_hold_length": 8},
            "candidate_strategy": "first_visual_gap_ready_hold_draft_v1",
            "spacing": {"frames_at_least": 25, "render_updates_at_least": 2},
            "visual_review": "technical feasibility review; independent human acceptance not performed",
            "visual_labels_assigned_by_probe": False, "existing_model_predictions_loaded": False,
            "model_api_calls": 0, "annotation_writes": 0}
    out.mkdir(parents=True)
    write_json(out / "analysis_plan.json", plan)
    episodes = []
    for key in keys:
        match = re.fullmatch(r"usim_train_episode_(\d{6})", key)
        if match is None:
            raise ValueError(f"Unexpected dev key: {key}")
        number = int(match.group(1))
        chunk = f"chunk-{number // 1000:03d}"
        source_paths = {"ego_video": f"train/videos/{chunk}/observation.images.ego/episode_{number:06d}.mp4",
                        "parquet": f"train/data/{chunk}/episode_{number:06d}.parquet"}
        sources = {}
        for kind, relative in source_paths.items():
            path = WORKSPACE / "usim" / relative
            digest = sha256(path)
            if digest != expected[relative]["sha256"]:
                raise ValueError(f"Pinned source hash mismatch: {relative}")
            sources[kind] = {"path": local_path(path), "sha256": digest, "pinned_hash_match": True}
        annotation_path = BASE / "usim-enact-v0.2/annotations/episodes" / f"{key}.json"
        annotation = json.loads(annotation_path.read_text(encoding="utf-8"))
        old_frames = [int(f["frame_index"]) for f in annotation["frames"]]
        state = np.asarray(pq.read_table(WORKSPACE / sources["parquet"]["path"],
                                         columns=["observation.state"])["observation.state"].to_pylist(), float)
        signal = signal_probe(state)
        holds, decoded, length = decode_holds(WORKSPACE / sources["ego_video"]["path"])
        if length != len(state) or max(old_frames) >= length:
            raise ValueError(f"Source/video/annotation alignment differs: {key}")
        episode_out = out / f"ep{number:06d}"
        episode_out.mkdir()
        # Include the whole episode as native hold representatives. The main
        # sheet starts before the main attempt; no model answer selects frames.
        sheet_tiles = []
        for hold in holds:
            representative = (hold["start"] + hold["end"]) // 2
            picture = Image.fromarray(cv2.cvtColor(decoded[representative], cv2.COLOR_BGR2RGB))
            target = episode_out / f"hold_{hold['index']:03d}_f{representative:05d}.png"
            picture.save(target)
            hold.update({"representative_frame": representative, "native_png": local_path(target),
                         "native_png_sha256": sha256(target), "dvl_at_representative": float(state[representative, 28]),
                         "gripper_at_representative": float(state[representative, 0])})
            if hold["end"] >= max(0, signal["main_close_signal_candidate"] - 45):
                label = (f"ep{number:06d}  H{hold['index']:02d}  f{representative}  [{hold['start']},{hold['end']}]\n"
                         f"len={hold['length']}  h={state[representative,28]:.3f}  grip={state[representative,0]:.3f}")
                sheet_tiles.append((label, picture))
        sheets = []
        for i in range(0, len(sheet_tiles), 12):
            target = episode_out / f"timeline_{i // 12 + 1:02d}.png"
            save_sheet(sheet_tiles[i:i + 12], target)
            sheets.append(local_path(target))
        old_tiles, old_hold_records = [], []
        for index, frame in enumerate(old_frames):
            hold = next(h for h in holds if h["start"] <= frame <= h["end"])
            picture = Image.fromarray(cv2.cvtColor(decoded[frame], cv2.COLOR_BGR2RGB))
            target = episode_out / f"old_slot_{index+1:02d}_f{frame:05d}.png"
            picture.save(target)
            old_tiles.append((f"ep{number:06d} old slot{index+1} f{frame}\nH{hold['index']:02d} [{hold['start']},{hold['end']}]", picture))
            old_hold_records.append({"slot": index + 1, "source_frame": frame, "hold_index": hold["index"],
                                     "hold_length": hold["length"], "native_png": local_path(target),
                                     "native_png_sha256": sha256(target)})
        old_sheet = episode_out / "old_keyframes.png"
        save_sheet(old_tiles, old_sheet)
        spacing = [{"left": a["source_frame"], "right": b["source_frame"],
                    "frame_gap": b["source_frame"] - a["source_frame"],
                    "render_updates": b["hold_index"] - a["hold_index"]}
                   for a, b in zip(old_hold_records, old_hold_records[1:])]
        payload = {"episode_key": key, "episode": number, "task_text": annotation["task_text"],
                   "task_family": "transfer" if "transfer" in annotation["task_text"].lower() else "pick",
                   "source_files": sources, "decoded_frames": length, "parquet_rows": len(state),
                   "annotation_path": local_path(annotation_path), "annotation_sha256": sha256(annotation_path),
                   "old_frames": old_frames, "old_hold_records": old_hold_records, "old_spacing": spacing,
                   "qa_questions": counts[key], "qa_ids": [q["id"] for q in qa if q["task_name"] == key],
                   "signal": signal, "holds": holds, "timeline_sheets": sheets,
                   "old_keyframe_sheet": local_path(old_sheet), "visual_review_complete": False}
        write_json(episode_out / "probe.json", payload)
        episodes.append(payload)
        print(json.dumps({"episode": number, "holds": len(holds), "sheets": len(sheets),
                          "proxy_window": signal["proxy_window_available"]}), flush=True)
    inventory = {"schema": "usim-dev-lift-feasibility-inventory/v1", "version": VERSION,
                 "analysis_plan_sha256": sha256(out / "analysis_plan.json"),
                 "episodes": episodes, "counts": {"episodes": len(episodes), "questions": len(qa),
                 "families": dict(Counter(e["task_family"] for e in episodes)),
                 "source_hash_checks": 2 * len(episodes), "source_alignment_pass": len(episodes)},
                 "model_api_calls": 0, "annotation_writes": 0, "visual_review_complete": False}
    write_json(out / "inventory.json", inventory)
    print(json.dumps({"output": local_path(out), "counts": inventory["counts"]}), flush=True)


if __name__ == "__main__":
    main()
