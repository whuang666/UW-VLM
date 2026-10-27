"""Condition B: full frame + local zoom, built as its own frozen QA file.

Crop policy (frozen before any B run, image-only -- no gt, no frame order, no
knowledge of where a model failed):

* **R1 object-anchored zoom** -- used when a compact blob of the episode's object
  colour is found in that frame (currently only ``red``; the underwater water body
  itself is blue, so a blue colour blob is not a reliable anchor).  Window side is
  ``4 x max(bbox_w, bbox_h)`` with a 160 px floor, centred on the blob centroid.
* **R2 fixed telephoto window** -- fallback when no anchor is found: the window
  ``x in [60, 260], y in [70, 230]``, which covers the arm and the seabed contact
  area on every annotated key frame of the v0.1 pilot.
* Both windows are clipped to the frame and resized to 320x240, then composited
  next to the untouched full frame: ``[ full | zoom ]`` = 640x240.

The composite keeps the original "Current State / Next State N" label on the full
panel and adds the same label with a ``zoom`` suffix on the right panel, so the
association between a state label and its two views stays explicit.

Output layout:
    <data-root>/QA/conditions/B_zoom/enact_ordering.jsonl
    <data-root>/QA/conditions/B_zoom/images/<qa_type>/<episode>/*.png
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enact.adapters.usim_annotations import PROTOCOL_VERSION, SENSOR_NAME  # noqa: E402
from enact.adapters.usim_visual_prompt import render_label  # noqa: E402
from scripts.usim.annotate_helper import colour_blobs  # noqa: E402

DEFAULT_DATA_ROOT = ROOT / "data" / "usim_enact" / PROTOCOL_VERSION
CONDITION = "B_zoom"
PANEL_SIZE = (320, 240)
FIXED_WINDOW = (60, 70, 260, 230)  # x0, y0, x1, y1


def load_jsonl(path: Path) -> List[Dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def episode_object_colour(data_root: Path, task_name: str) -> Optional[str]:
    annotation = data_root / "annotations" / "episodes" / f"{task_name}.json"
    if not annotation.exists():
        return None
    payload = json.loads(annotation.read_text(encoding="utf-8"))
    for obj in payload.get("objects", []):
        if obj.get("colour") or obj.get("color"):
            return str(obj.get("color") or obj.get("colour"))
    return None


def anchored_window(frame: np.ndarray, colour: Optional[str]) -> Tuple[Tuple[int, int, int, int], str]:
    """Return ((x0, y0, x1, y1), rule) for the zoom panel."""
    height, width = frame.shape[:2]
    if colour in ("red", "green"):
        blob = colour_blobs(frame)[colour]
        if blob["area"] >= 20 and blob["w"] > 0 and blob["h"] > 0:
            compactness = blob["area"] / float(blob["w"] * blob["h"])
            if compactness >= 0.35 and max(blob["w"], blob["h"]) <= 120:
                side = max(160, 4 * max(blob["w"], blob["h"]))
                cx, cy = blob["cx"], blob["cy"]
                x0 = int(round(cx - side / 2))
                y0 = int(round(cy - side / 2))
                x1, y1 = x0 + side, y0 + side
                x0, y0 = max(0, x0), max(0, y0)
                x1, y1 = min(width, x1), min(height, y1)
                if x1 - x0 >= 80 and y1 - y0 >= 60:
                    return (x0, y0, x1, y1), "R1_object_anchor"
    return FIXED_WINDOW, "R2_fixed_window"


def label_panel(panel: np.ndarray, text: str) -> np.ndarray:
    """Draw the standard label onto one panel via a temp file (reuses upstream renderer)."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "panel.png"
        cv2.imwrite(str(path), panel)
        render_label(str(path), text, str(path))
        return cv2.imread(str(path))


def compose(full: np.ndarray, window: Tuple[int, int, int, int], label: str) -> np.ndarray:
    x0, y0, x1, y1 = window
    zoom = full[y0:y1, x0:x1]
    zoom = cv2.resize(zoom, (PANEL_SIZE[0], PANEL_SIZE[1]), interpolation=cv2.INTER_CUBIC)
    # keep the top-left label byte-identical to condition A so the only change is the extra panel
    left = label_panel(full, label)
    right = label_panel(zoom, label)
    cv2.putText(right, "zoom", (8, PANEL_SIZE[1] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
    return np.hstack([left, right])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--qa", default="")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    data_root = Path(args.data_root)
    qa_path = Path(args.qa) if args.qa else data_root / "QA" / "train" / "enact_ordering.jsonl"
    records = load_jsonl(qa_path)

    out_root = data_root / "QA" / "conditions" / CONDITION
    out_qa = out_root / "enact_ordering.jsonl"
    if out_qa.exists():
        out_qa.unlink()

    # raw frame index per episode so we can rebuild composites from clean frames
    frame_cache: Dict[str, Dict[str, np.ndarray]] = {}
    colours: Dict[str, Optional[str]] = {}
    rule_counts: Dict[str, int] = {}
    new_records = []
    image_rows: List[Dict] = []

    for record in records:
        task_name = record["task_name"]
        if task_name not in frame_cache:
            colours[task_name] = episode_object_colour(data_root, task_name)
            sensor_dir = data_root / "replayed_activities" / task_name / SENSOR_NAME
            frame_cache[task_name] = {
                path.stem: cv2.imread(str(path)) for path in sorted(sensor_dir.glob("*.png"))
            }

        # map each presented image back to its source frame (labels live only in the top band)
        sources = list(frame_cache[task_name].items())
        image_dir = out_root / "images" / record["type"] / task_name
        image_dir.mkdir(parents=True, exist_ok=True)

        new_images: List[str] = []
        for position, relative in enumerate(record["images"]):
            presented = cv2.imread(str(data_root / str(relative).replace("\\", "/")))
            if presented is None:
                raise FileNotFoundError(relative)
            body = presented[56:, :, :].astype(np.int16)
            best_name, best_score = None, None
            for name, raw in sources:
                score = float(np.mean(np.abs(raw[56:, :, :].astype(np.int16) - body)))
                if best_score is None or score < best_score:
                    best_name, best_score = name, score
            if best_score is None or best_score > 1.0:
                raise RuntimeError(f"{record['id']}: cannot map presented image to a source frame (score={best_score})")

            frame = frame_cache[task_name][best_name]
            window, rule = anchored_window(frame, colours[task_name])
            rule_counts[rule] = rule_counts.get(rule, 0) + 1

            label = "Current State" if position == 0 else f"Next State {position}"
            target = image_dir / f"{record['id']}_{position:02d}.png"
            cv2.imwrite(str(target), compose(frame, window, label))
            new_images.append(str(target.relative_to(data_root)))
            image_rows.append({"id": record["id"], "position": position, "rule": rule,
                               "window": list(window), "path": str(target.relative_to(data_root))})

        new_record = dict(record)
        new_record["images"] = new_images
        new_record["source_images"] = record["images"]
        new_records.append(new_record)

    out_root.mkdir(parents=True, exist_ok=True)
    with out_qa.open("w", encoding="utf-8") as handle:
        for record in new_records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    manifest = {
        "condition": CONDITION,
        "source_qa": str(qa_path),
        "source_qa_sha256": sha256_file(qa_path),
        "output_qa": str(out_qa),
        "output_qa_sha256": sha256_file(out_qa),
        "crop_policy": {
            "R1_object_anchor": "window side = max(160, 4*max(bbox_w,bbox_h)), centred on the object colour blob",
            "R2_fixed_window": list(FIXED_WINDOW),
            "colours_anchored": ["red", "green"],
            "panel_layout": "[full 320x240 | zoom 320x240]",
        },
        "rule_counts": rule_counts,
        "object_colours": colours,
        "images": len(image_rows),
        "questions": len(new_records),
    }
    (out_root / "build_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps({"questions": len(new_records), "images": len(image_rows), "rules": rule_counts}, ensure_ascii=False))
    print(f"output: {out_qa}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
