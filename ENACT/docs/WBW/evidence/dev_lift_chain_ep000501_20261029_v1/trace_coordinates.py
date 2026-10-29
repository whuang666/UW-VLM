"""Trace visible purple pixels; no depth, support or Lifted labels are inferred."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

WORKSPACE = Path(__file__).resolve().parents[5]
REVIEW = WORKSPACE / "ENACT/data/usim_enact/_review/dev_lift_onset/exemplar_ep000501_20261029_v1b"
EVIDENCE = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, default=REVIEW)
    parser.add_argument("--out", type=Path, default=EVIDENCE)
    args = parser.parse_args()
    review, evidence = args.review.resolve(), args.out.resolve()
    inventory = json.loads((review / "frame_inventory.json").read_text(encoding="utf-8"))
    if inventory["episode_key"] != "usim_train_episode_000501":
        raise ValueError("This trace is scoped to dev episode 501")
    evidence.mkdir(parents=True, exist_ok=True)
    trace = []
    for frame in inventory["frames"]:
        path = WORKSPACE / frame["ego_png"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != frame["ego_png_sha256"]:
            raise ValueError(f"PNG changed: {path}")
        image = cv2.imread(str(path))
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([120, 65, 45], np.uint8), np.array([165, 255, 255], np.uint8))
        region = np.zeros(mask.shape, np.uint8)
        region[82:200, 72:170] = mask[82:200, 72:170]
        count, labels, stats, _ = cv2.connectedComponentsWithStats(region)
        if count < 2:
            raise ValueError(f"No purple component at frame {frame['frame']}")
        component = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        ys, xs = np.where(labels == component)
        rectangle = cv2.minAreaRect(np.column_stack([xs, ys]).astype(np.float32))
        bottom = int(ys.max())
        trace.append({
            "frame": frame["frame"], "ego_png": frame["ego_png"],
            "ego_png_sha256": frame["ego_png_sha256"],
            "dvl": frame["dvl"], "gripper": frame["gripper"],
            "ego_motion_hold": frame["ego_motion_hold"],
            "ego_exact_pixel_run": frame["ego_exact_pixel_run"],
            "wrist_exact_pixel_run": frame["wrist_exact_pixel_run"],
            "purple_silhouette_bbox_xywh": [int(x) for x in stats[component, :4]],
            "purple_mask_pixel_count": int(stats[component, cv2.CC_STAT_AREA]),
            "image_bottom_xy": [float(np.median(xs[ys == bottom])), bottom],
            "visible_mask_short_side_px": float(min(rectangle[1])),
            "local_seabed_reference_xy": None, "object_to_seabed_gap_px": None,
            "gap_to_object_width_ratio": None, "physical_support": None,
            "physical_departure": None, "half_width_gap_confirmed": None,
        })
    result = {
        "schema": "usim-dev-lift-image-trace/v1", "episode": 501,
        "trace_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "coordinate_convention": "zero-based native ego pixels; image bottom is not calibrated physical lowest point",
        "method": {
            "purple_mask": "OpenCV HSV H120..165, S>=65, V>=45; largest component in x[72,170), y[82,200)",
            "short_side": "minAreaRect of visible component; occlusion-sensitive, not physical diameter",
            "ground_reference": "unresolved; no verified floor contact edge or projection",
            "null_semantics": "unobserved/unconfirmed, not false or zero",
        },
        "frames": trace,
    }
    (evidence / "image_trace.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    canvas = Image.new("RGB", (1050, 710), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 17)
    small = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 14)
    for column, index in enumerate([214, 226, 282]):
        row = next(r for r in trace if r["frame"] == index)
        x = column * 350
        draw.text((x + 7, 4), f"ep000501 f{index}", font=font, fill="black")
        draw.text((x + 7, 27), f"visible-mask width={row['visible_mask_short_side_px']:.2f}px", font=small, fill="black")
        image = Image.open(WORKSPACE / row["ego_png"])
        canvas.paste(image, (x + 12, 50))
        canvas.paste(image.crop((72, 82, 170, 200)).resize((294, 354), Image.Resampling.NEAREST), (x + 20, 300))
        px, py = row["image_bottom_xy"]
        cx, cy = x + 20 + (px - 72) * 3, 300 + (py - 82) * 3
        draw.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), outline="red", width=2)
    draw.text((8, 665), "Red: image silhouette bottom. Local seabed reference and gap remain UNRESOLVED.", font=font, fill="black")
    canvas.save(review / "trace_contact_sheet.png")
    print(json.dumps({"traced_frames": len(trace), "ground_references_assigned": 0, "labels_assigned": False}))


if __name__ == "__main__":
    main()
