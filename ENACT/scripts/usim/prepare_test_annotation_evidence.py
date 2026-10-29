"""Read-only source probes for test-reserve annotation; never assigns labels.

Decode ego frames, verify source hashes, report gripper events/DVL/hold runs and
export native candidate images plus a nearest-neighbor contact sheet for review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pyarrow.parquet as pq
from PIL import Image, ImageDraw, ImageFont

ENACT = Path(__file__).resolve().parents[2]
BASE = ENACT / "data/usim_enact"


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def probe(number: int, out_root: Path) -> dict:
    package_path = BASE / "_expansion/packages" / f"usim_train_episode_{number:06d}/package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    for source in ("parquet", "ego_video", "wrist_video"):
        path = Path(package["source_files"][source]["path"])
        if file_hash(path) != package["source_files"][source]["sha256"]:
            raise ValueError(f"Source hash differs: {number}/{source}")
    table = pq.read_table(package["source_files"]["parquet"]["path"], columns=["observation.state"])
    state = np.array(table["observation.state"].to_pylist(), dtype=float)
    closed = state[:, 0] > 0.004
    events = [{"event": "close" if closed[i] else "open", "frame": i}
              for i in range(1, len(state)) if closed[i] != closed[i - 1]]
    closes = [event["frame"] for event in events if event["event"] == "close"]
    close = closes[-1]
    low, high = max(0, close - 20), min(len(state), close + 120)
    minimum = int(np.argmin(state[low:high, 28])) + low
    lift_low, lift_high = minimum + 40, min(len(state) - 1, minimum + 60)
    chosen = {0, max(0, closes[0] - 90), max(0, closes[0] - 60)}
    for window in ((close - 20, close - 10), (close + 10, close + 20), (lift_low, lift_high)):
        chosen.update(range(max(0, window[0]), min(len(state) - 1, window[1]) + 1, 5))
    for frame in package["candidate_frames"]:
        if frame["role"] == "start":
            chosen.add(frame["frame_index"])
    # Include the failed first attempt and retry neighborhood, without labelling it.
    if len(closes) > 1:
        chosen.update([closes[0] - 20, closes[0] - 10, closes[0] + 10, closes[0] + 20, close - 5, close])
    chosen = sorted(frame for frame in chosen if 0 <= frame < len(state))
    out = out_root / f"ep{number}"
    out.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(package["source_files"]["ego_video"]["path"])
    runs = []
    previous = None
    start = 0
    decoded = 0
    stored = {}
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(float)
        if previous is not None and float(np.abs(gray - previous).mean()) > 0.5:
            runs.append({"start": start, "end": decoded - 1, "length": decoded - start})
            start = decoded
        previous = gray
        if decoded in chosen:
            rgb = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            rgb.save(out / f"ego_f{decoded:05d}.png")
            stored[decoded] = rgb
        decoded += 1
    capture.release()
    runs.append({"start": start, "end": decoded - 1, "length": decoded - start})
    if decoded != package["length"] or decoded != len(state):
        raise ValueError(f"Video/Parquet alignment differs: {number}")
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 19)
    cols, width, height = 4, 480, 420
    canvas = Image.new("RGB", (cols * width, ((len(chosen) + cols - 1) // cols) * height), "white")
    draw = ImageDraw.Draw(canvas)
    candidates = []
    for index, frame in enumerate(chosen):
        hold = next(run for run in runs if run["start"] <= frame <= run["end"])
        x, y = (index % cols) * width, (index // cols) * height
        draw.text((x + 8, y + 4), f"f{frame}  dvl={state[frame,28]:.3f}  grip={state[frame,0]:.3f}", font=font, fill="black")
        draw.text((x + 8, y + 26), f"hold {hold['start']}..{hold['end']} ({hold['length']})", font=font, fill="black")
        canvas.paste(stored[frame].resize((480, 360), Image.Resampling.NEAREST), (x, y + 52))
        candidates.append({"frame": frame, "hold": hold, "dvl_h": float(state[frame, 28]), "gripper_signal": float(state[frame, 0]),
                           "closed_signal": bool(closed[frame]), "native_png_sha256": file_hash(out / f"ego_f{frame:05d}.png")})
    canvas.save(out / "candidates.png")
    evidence = {"schema": "usim-test-annotation-probe/v1", "episode": number, "task_text": package["task_text"],
                "source_package": str(package_path), "source_package_sha256": file_hash(package_path),
                "source_files": package["source_files"], "decoded_frames": decoded, "events": events,
                "main_close_candidate": close, "first_close": closes[0], "dvl_minimum_frame": minimum,
                "dvl_minimum": float(state[minimum, 28]), "ascent_window_proposal": [lift_low, lift_high],
                "onset_note": "DVL minimum followed by rise is only an anchoring proposal; ego evidence decides the label",
                "hold_motion_threshold": 0.5, "hold_motion_measure": "mean absolute gray-level difference",
                "hold_runs": runs, "candidate_frames": candidates, "labels_assigned": False, "model_api_calls": 0}
    (out / "probe.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return {"episode": number, "events": events, "close": close, "minimum": minimum, "lift_window": [lift_low, lift_high],
            "sheet": str(out / "candidates.png"), "candidate_count": len(chosen)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episodes", default="1734,1259,1273,1145,1497,1549")
    parser.add_argument("--out", type=Path, default=BASE / "_review/test_reserve/round_20261028")
    args = parser.parse_args()
    for number in [int(value) for value in args.episodes.split(",")]:
        print(json.dumps(probe(number, args.out.resolve())), flush=True)


if __name__ == "__main__":
    main()
