"""Annotation helpers: candidate frames, contact sheets and colour-blob signals.

This tool never writes annotations.  It only produces review material:

* ``signals.csv``      per-frame colour-blob area/centroid and mean frame difference,
                       used to propose candidate key frames;
* ``sheet_<a>_<b>.png`` contact sheets with frame indices burned in, so a human
                       (or an agent) can pick key frames and read the object states;
* ``sheet_spec_*.png`` a sheet for an explicit list of frames.

The blob detector is *evidence*, not ground truth: USIM frames are 320x240 with a
strong blue-green cast, so thresholds are permissive and counts are reported as-is.

Usage:
    python scripts/usim/annotate_helper.py --episode 1300 --stride 25 --grid 12
    python scripts/usim/annotate_helper.py --episode 1300 --frames 0,120,240,360
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, List, Sequence

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enact.adapters.usim_reader import USIMReader, resolve_dataset_root  # noqa: E402

COLOUR_RANGES = {
    # hue bounds (OpenCV 0..179), saturation floor, value floor
    "red": ((0, 10), (170, 179), 80, 60),
    "green": ((35, 85), None, 90, 60),
    "blue": ((100, 145), None, 80, 50),
}


def colour_blobs(bgr: np.ndarray) -> Dict[str, Dict[str, float]]:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    hue = hsv[:, :, 0].astype(np.int16)
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    result: Dict[str, Dict[str, float]] = {}
    for name, (low, high, sat_min, val_min) in COLOUR_RANGES.items():
        mask = np.zeros(hue.shape, dtype=bool)
        for bounds in (low, high):
            if bounds is None:
                continue
            mask |= (hue >= bounds[0]) & (hue <= bounds[1])
        mask &= (sat >= sat_min) & (val >= val_min)
        mask_u8 = (mask.astype(np.uint8)) * 255
        mask_u8 = cv2.morphologyEx(mask_u8, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask_u8, 8)
        best_area, best_centroid, best_bbox = 0, (np.nan, np.nan), (0, 0, 0, 0)
        for idx in range(1, count):
            area = int(stats[idx, cv2.CC_STAT_AREA])
            if area < 12:
                continue
            if area > best_area:
                best_area = area
                best_centroid = (float(centroids[idx][0]), float(centroids[idx][1]))
                best_bbox = (
                    int(stats[idx, cv2.CC_STAT_LEFT]),
                    int(stats[idx, cv2.CC_STAT_TOP]),
                    int(stats[idx, cv2.CC_STAT_WIDTH]),
                    int(stats[idx, cv2.CC_STAT_HEIGHT]),
                )
        result[name] = {
            "area": best_area,
            "cx": best_centroid[0],
            "cy": best_centroid[1],
            "x": best_bbox[0],
            "y": best_bbox[1],
            "w": best_bbox[2],
            "h": best_bbox[3],
        }
    return result


def label_frame(frame: np.ndarray, text: str, scale: float = 0.55) -> np.ndarray:
    canvas = frame.copy()
    (width, height), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
    cv2.rectangle(canvas, (4, 4), (12 + width, 12 + height + baseline), (0, 0, 0), -1)
    cv2.putText(canvas, text, (8, 8 + height), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 255, 255), 1, cv2.LINE_AA)
    return canvas


def build_sheet(tiles: Sequence[tuple[str, np.ndarray]], columns: int = 3) -> np.ndarray:
    if not tiles:
        raise ValueError("empty contact sheet")
    height, width = tiles[0][1].shape[:2]
    rows = int(np.ceil(len(tiles) / columns))
    sheet = np.full((rows * height, columns * width, 3), 24, dtype=np.uint8)
    for position, (text, frame) in enumerate(tiles):
        row, column = divmod(position, columns)
        sheet[row * height:(row + 1) * height, column * width:(column + 1) * width] = label_frame(frame, text)
    return sheet


def write_signals(reader: USIMReader, episode: int, stride: int, out_dir: Path) -> List[Dict[str, float]]:
    rows: List[Dict[str, float]] = []
    previous = None
    for frame_index, frame in reader.iter_frames(episode, camera="ego"):
        if frame_index % stride:
            continue
        blobs = colour_blobs(frame)
        grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
        motion = float(np.mean(np.abs(grey - previous))) if previous is not None else 0.0
        previous = grey
        row = {"frame": frame_index, "motion": round(motion, 3)}
        for name, blob in blobs.items():
            row[f"{name}_area"] = blob["area"]
            row[f"{name}_cx"] = round(blob["cx"], 1) if blob["area"] else ""
            row[f"{name}_cy"] = round(blob["cy"], 1) if blob["area"] else ""
        rows.append(row)
    path = out_dir / "signals.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset-root", default=str(resolve_dataset_root()))
    parser.add_argument("--split", default="train", choices=["train", "test"])
    parser.add_argument("--episode", type=int, required=True)
    parser.add_argument("--frames", default="", help="explicit comma separated frame indices")
    parser.add_argument("--stride", type=int, default=25, help="stride for evenly spaced contact sheets")
    parser.add_argument("--grid", type=int, default=12, help="frames per contact sheet")
    parser.add_argument("--columns", type=int, default=3)
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)

    reader = USIMReader(args.dataset_root, split=args.split)
    episode = reader.episode(args.episode)
    out_dir = Path(args.out) if args.out else ROOT / "data" / "usim_enact" / "_review" / episode.key
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.frames:
        wanted = [int(v) for v in args.frames.split(",") if v.strip()]
        tiles = [(f"f{idx}", reader.read_frame(args.episode, idx)) for idx in wanted]
        path = out_dir / f"sheet_spec_{wanted[0]}_{wanted[-1]}.png"
        cv2.imwrite(str(path), build_sheet(tiles, columns=args.columns))
        print(path)
        return 0

    rows = write_signals(reader, args.episode, args.stride, out_dir)
    print(f"signals: {out_dir / 'signals.csv'}")
    print(f"episode {episode.key}: {episode.length} frames, task={episode.task_text!r}")

    frames = [int(row["frame"]) for row in rows]
    for sheet_index in range(0, len(frames), args.grid):
        chunk = frames[sheet_index:sheet_index + args.grid]
        tiles = [(f"f{idx}", reader.read_frame(args.episode, idx)) for idx in chunk]
        path = out_dir / f"sheet_{chunk[0]:04d}_{chunk[-1]:04d}.png"
        cv2.imwrite(str(path), build_sheet(tiles, columns=args.columns))
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
