"""Reviewer-A helper: render contact sheets and numeric evidence for blind review.

Read-only over the dataset; writes only under reviewer_a/tools_out.
Usage (from E:\\code\\UW-VLM\\ENACT):
  python <this> --what kf_ctx --episode 200
  python <this> --what ctx --episode 200 --frames 140,213,248,328
  python <this> --what num --episode 200 --frames 140,213,248,328 --range 60
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path("E:/code/UW-VLM/ENACT")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enact.adapters.usim_reader import USIMReader, resolve_dataset_root  # noqa: E402
from scripts.usim.annotate_helper import colour_blobs  # noqa: E402

OUT = Path("E:/code/UW-VLM/ENACT/data/usim_enact/_review/round2/reviewer_a/tools_out")

# fixed crop that covers the arm + object region; image-only rule, no gt involved
CROP = (80, 30, 240, 190)  # x, y, w, h


def crop(frame: np.ndarray, scale: float) -> np.ndarray:
    x, y, w, h = CROP
    sub = frame[y:y + h, x:x + w]
    return cv2.resize(sub, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)


def label(img: np.ndarray, text: str) -> np.ndarray:
    out = img.copy()
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
    cv2.rectangle(out, (2, 2), (10 + tw, 10 + th + base), (0, 0, 0), -1)
    cv2.putText(out, text, (6, 6 + th), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1, cv2.LINE_AA)
    return out


def sheet(tiles, columns: int) -> np.ndarray:
    h, w = tiles[0][1].shape[:2]
    rows = int(np.ceil(len(tiles) / columns))
    canvas = np.full((rows * h, columns * w, 3), 20, np.uint8)
    for i, (text, im) in enumerate(tiles):
        r, c = divmod(i, columns)
        canvas[r * h:(r + 1) * h, c * w:(c + 1) * w] = label(im, text)
    return canvas


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--what", required=True, choices=["kf_ctx", "ctx", "num", "detail"])
    ap.add_argument("--episode", type=int, required=True)
    ap.add_argument("--frames", default="")
    ap.add_argument("--range", type=int, default=20)
    ap.add_argument("--scale", type=float, default=2.0)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    reader = USIMReader(str(resolve_dataset_root()), split="train")
    ep = reader.episode(args.episode)
    frames = [int(v) for v in args.frames.split(",") if v.strip()]

    if args.what == "num":
        table = reader.load_table(args.episode)
        joint0 = np.asarray([np.asarray(v, dtype=np.float32) for v in table["observation.state"]])[:, 0]
        lo = max(0, min(frames) - args.range)
        hi = min(ep.length - 1, max(frames) + args.range)
        want = list(range(lo, hi + 1))
        decoded = reader.read_frames(args.episode, want)
        out = {"episode_key": ep.key, "length": ep.length, "task": ep.task_text,
               "crop": CROP, "range": [lo, hi], "frames": {}}
        for f in want:
            blobs = colour_blobs(decoded[f])
            rec = {"gripper_state0": round(float(joint0[f]), 5),
                   "motion": None}
            rec["blobs"] = {k: {"area": int(v["area"]), "cx": round(float(v["cx"]), 1) if v["area"] else None,
                                "cy": round(float(v["cy"]), 1) if v["area"] else None,
                                "bbox": [v["x"], v["y"], v["w"], v["h"]]}
                            for k, v in blobs.items()}
            out["frames"][str(f)] = rec
        path = OUT / f"num_{ep.episode_index}.json"
        path.write_text(json.dumps(out, indent=1), encoding="utf-8")
        print(path)
        # compact console table
        print("frame  grip  blue(area,cx,cy,w,h)   red(area,cx,cy,w,h)  green(area,cx,cy)")
        sel = set(frames)
        for f in want:
            if f % 5 and f not in sel:
                continue
            rec = out["frames"][str(f)]
            def fmt(name):
                b = rec["blobs"][name]
                return f"{b['area']:4d} {b['cx']} {b['cy']} {b['bbox'][2]}x{b['bbox'][3]}" if b["area"] else "  -"
            print(f"{f:5d} {rec['gripper_state0']:.4f}  {fmt('blue'):26s} {fmt('red'):26s} {fmt('green')}")
        return 0

    if args.what == "kf_ctx":
        tiles = []
        for f in frames:
            fr = reader.read_frame(args.episode, f)
            img = cv2.resize(fr, None, fx=args.scale, fy=args.scale, interpolation=cv2.INTER_NEAREST)
            tiles.append((f"key f{f} ({f/10:.1f}s)", img))
        path = OUT / f"kf_{ep.episode_index}.png"
        cv2.imwrite(str(path), sheet(tiles, columns=2))
        print(path)
        return 0

    if args.what == "ctx":
        for f in frames:
            want = list(range(f - args.range, f + args.range + 1, 5))
            want = [i for i in want if 0 <= i < ep.length]
            decoded = reader.read_frames(args.episode, want)
            tiles = [(f"f{i}", crop(decoded[i], args.scale)) for i in want]
            path = OUT / f"ctx_{ep.episode_index}_{f:04d}.png"
            cv2.imwrite(str(path), sheet(tiles, columns=3))
            print(path)
        return 0

    if args.what == "detail":
        for f in frames:
            want = [i for i in (f - 10, f, f + 10) if 0 <= i < ep.length]
            decoded = reader.read_frames(args.episode, want)
            tiles = [(f"f{i}", crop(decoded[i], 3.0)) for i in want]
            path = OUT / f"detail_{ep.episode_index}_{f:04d}.png"
            cv2.imwrite(str(path), sheet(tiles, columns=3))
            print(path)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
