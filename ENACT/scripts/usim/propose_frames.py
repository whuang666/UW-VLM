"""Propose candidate key frames from the gripper signal, then render a review sheet.

``observation.state[0]`` in USIM is a two-level gripper joint (open ``~0.000`` /
closed ``~0.0149`` with a ~3 frame ramp).  On the annotated pilot episodes the
close command lands 10-40 frames before the object is actually held, and the
trailing open command marks the release.  The signal is therefore a reliable
*event proposal* mechanism, not a semantic ground truth: every proposed frame still
needs visual review.

Usage:
    python scripts/usim/propose_frames.py --episode 1302
    python scripts/usim/propose_frames.py --episode 552 --out data/usim_enact/_review
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Sequence

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enact.adapters.usim_reader import USIMReader, resolve_dataset_root  # noqa: E402
from scripts.usim.annotate_helper import build_sheet, colour_blobs  # noqa: E402

GRIPPER_OPEN_THRESHOLD = 0.004
# Offsets (frames) around each gripper event that are worth looking at.
EVENT_OFFSETS = (-60, -30, -10, 0, 15, 40)


def gripper_events(joint0: np.ndarray, threshold: float = GRIPPER_OPEN_THRESHOLD) -> List[Dict[str, object]]:
    closed = joint0 > threshold
    events: List[Dict[str, object]] = []
    for index in range(1, len(closed)):
        if closed[index] and not closed[index - 1]:
            events.append({"event": "close", "frame": index})
        elif not closed[index] and closed[index - 1]:
            events.append({"event": "open", "frame": index})
    return events


def propose(episode_length: int, events: Sequence[Dict[str, object]], max_last_events: int = 2) -> List[int]:
    """First frame plus the neighbourhood of the first and last gripper events."""
    chosen = {0, episode_length - 2}
    picked = list(events[:1]) + list(events[-max_last_events:])
    for event in picked:
        for offset in EVENT_OFFSETS:
            chosen.add(int(event["frame"]) + offset)
    return sorted(f for f in chosen if 0 <= f < episode_length)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset-root", default=str(resolve_dataset_root()))
    parser.add_argument("--split", default="train", choices=["train", "test"])
    parser.add_argument("--episode", type=int, required=True)
    parser.add_argument("--out", default="")
    parser.add_argument("--columns", type=int, default=4)
    args = parser.parse_args(argv)

    reader = USIMReader(args.dataset_root, split=args.split)
    episode = reader.episode(args.episode)
    table = reader.load_table(args.episode)
    joint0 = np.array([np.asarray(v, dtype=np.float32) for v in table["observation.state"]])[:, 0]
    events = gripper_events(joint0)
    candidates = propose(episode.length, events)

    out_dir = Path(args.out) if args.out else ROOT / "data" / "usim_enact" / "_review" / episode.key
    out_dir.mkdir(parents=True, exist_ok=True)

    tiles = []
    visibility: Dict[str, Dict[str, float]] = {}
    for frame_index in candidates:
        frame = reader.read_frame(args.episode, frame_index)
        blobs = colour_blobs(frame)
        visibility[str(frame_index)] = {
            name: {"area": int(blob["area"]),
                   "cx": round(blob["cx"], 1) if blob["area"] else None,
                   "cy": round(blob["cy"], 1) if blob["area"] else None}
            for name, blob in blobs.items()
        }
        tiles.append((f"f{frame_index}", frame))

    sheet_path = out_dir / f"proposal_{candidates[0]:04d}_{candidates[-1]:04d}.png"
    cv2.imwrite(str(sheet_path), build_sheet(tiles, columns=args.columns))

    report = {
        "episode_key": episode.key,
        "task_text": episode.task_text,
        "length": episode.length,
        "gripper_events": events,
        "proposed_frames": candidates,
        "blob_stats": visibility,
        "sheet": str(sheet_path),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
