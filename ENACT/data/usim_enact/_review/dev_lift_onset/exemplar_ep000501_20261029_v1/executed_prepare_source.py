"""Export a dev-only lift evidence chain for manual review, without assigning labels."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np
import pyarrow.parquet as pq
from PIL import Image, ImageDraw, ImageFont

ENACT = Path(__file__).resolve().parents[2]
if str(ENACT) not in sys.path:
    sys.path.insert(0, str(ENACT))

from scripts.usim.probe_dev_lift_onset import (  # noqa: E402
    BASE, REVIEW_PARENT, WORKSPACE, decode_holds, local_path, resolve_output,
    sha256, signal_probe, write_json,
)


def exact_pixel_runs(frames: list[np.ndarray]) -> list[dict]:
    result, start = [], 0
    for i in range(1, len(frames) + 1):
        if i == len(frames) or not np.array_equal(frames[i], frames[i - 1]):
            result.append({"index": len(result), "start": start, "end": i - 1, "length": i - start})
            start = i
    return result


def gallery(records: list[dict], out: Path, frames: list[int]) -> None:
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 17)
    lookup = {r["frame"]: r for r in records}
    for page in range(0, len(frames), 4):
        subset = frames[page:page + 4]
        canvas = Image.new("RGB", (1280, 410 * len(subset)), "white")
        draw = ImageDraw.Draw(canvas)
        for row, frame in enumerate(subset):
            r = lookup[frame]
            y = row * 410
            draw.text((4, y + 2), f"f{frame}: ego full | ego ROI (x72..169,y82..199) | wrist auxiliary", font=font, fill="black")
            draw.text((4, y + 22), f"h={r['dvl']:.6f}; grip={r['gripper']:.6f}; motion hold={r['ego_motion_hold']['start']}..{r['ego_motion_hold']['end']}", font=font, fill="black")
            ego = Image.open(WORKSPACE / r["ego_png"])
            wrist = Image.open(WORKSPACE / r["wrist_aux_png"])
            canvas.paste(ego.resize((480, 360), Image.Resampling.NEAREST), (0, y + 48))
            canvas.paste(ego.crop((72, 82, 170, 200)).resize((294, 354), Image.Resampling.NEAREST), (486, y + 48))
            canvas.paste(wrist.resize((480, 360), Image.Resampling.NEAREST), (800, y + 48))
        canvas.save(out / f"chain_gallery_{page // 4 + 1:02d}.png")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode", type=int, default=501)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    split_path = BASE / "runs/qwen3.8-max/v02_dev_001/inputs/splits_manifest.json"
    split = json.loads(split_path.read_text(encoding="utf-8"))
    key = f"usim_train_episode_{args.episode:06d}"
    if key not in split["splits"]["dev"]["episodes"]:
        raise ValueError("Exemplar must belong to the existing frozen dev split")
    out = resolve_output(args.out or REVIEW_PARENT / f"exemplar_ep{args.episode:06d}_20261029_v1")
    source_manifest_path = WORKSPACE / "usim/_download_manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    expected_path = WORKSPACE / "tools/_hfcache/expected.json"
    if sha256(expected_path) != source_manifest["expected_manifest_sha256"]:
        raise ValueError("Pinned source inventory changed")
    expected = {item["path"]: item for item in json.loads(expected_path.read_text(encoding="utf-8"))}
    chunk = f"chunk-{args.episode // 1000:03d}"
    relative = {"ego": f"train/videos/{chunk}/observation.images.ego/episode_{args.episode:06d}.mp4",
                "wrist_aux": f"train/videos/{chunk}/observation.images.wrist/episode_{args.episode:06d}.mp4",
                "parquet": f"train/data/{chunk}/episode_{args.episode:06d}.parquet"}
    sources = {}
    for role, name in relative.items():
        path = WORKSPACE / "usim" / name
        digest = sha256(path)
        if digest != expected[name]["sha256"]:
            raise ValueError(f"Pinned source differs: {name}")
        sources[role] = {"path": local_path(path), "sha256": digest, "pinned_hash_match": True}
    state = np.asarray(pq.read_table(WORKSPACE / sources["parquet"]["path"],
                                    columns=["observation.state"])["observation.state"].to_pylist(), float)
    signal = signal_probe(state)
    ego_holds, ego, n = decode_holds(WORKSPACE / sources["ego"]["path"])
    wrist_holds, wrist, wrist_n = decode_holds(WORKSPACE / sources["wrist_aux"]["path"])
    if n != len(state) or wrist_n != n:
        raise ValueError("Video/Parquet alignment differs")
    ego_exact, wrist_exact = exact_pixel_runs(ego), exact_pixel_runs(wrist)
    lo, hi = max(0, signal["main_close_signal_candidate"] - 40), n - 1
    if args.episode == 501:
        lo = 180
    plan = {"schema": "usim-dev-lift-chain-plan/v1", "version": "dev-lift-chain-ep000501-v1" if args.episode == 501 else f"dev-lift-chain-ep{args.episode:06d}-v1",
            "episode_key": key, "split": "dev", "source_commit": source_manifest["commit"],
            "source_files": sources, "script_sha256": sha256(Path(__file__)),
            "probe_dependency_sha256": sha256(ENACT / "scripts/usim/probe_dev_lift_onset.py"),
            "split_manifest_sha256": sha256(split_path), "review_frames_inclusive": [lo, hi],
            "selection_reason": "Single-close, single-target, ordinary blue-cylinder pick in already used dev; no transfer, no accuracy-based selection",
            "posthoc_feasibility_example": True, "blind_review_claimed": False,
            "rule_change_applied": False, "annotation_writes": 0, "model_api_calls": 0,
            "ego_primary": True, "wrist_auxiliary_only": True,
            "coordinate_convention": "Zero-based native pixels; crop boxes are half-open; resized views use nearest-neighbor only",
            "exact_pixel_definition": "Adjacent complete decoded BGR arrays equal in every byte; not compressed video packet bytes",
            "motion_hold_definition": "Adjacent decoded grayscale mean absolute difference <=0.5"}
    out.mkdir(parents=True)
    write_json(out / "analysis_plan.json", plan)
    for name in ("ego", "wrist_aux"):
        (out / name).mkdir()
    records = []
    for i in range(lo, hi + 1):
        ep, wp = out / "ego" / f"f{i:05d}.png", out / "wrist_aux" / f"f{i:05d}.png"
        Image.fromarray(cv2.cvtColor(ego[i], cv2.COLOR_BGR2RGB)).save(ep)
        Image.fromarray(cv2.cvtColor(wrist[i], cv2.COLOR_BGR2RGB)).save(wp)
        records.append({"frame": i, "dvl": float(state[i, 28]), "gripper": float(state[i, 0]),
                        "ego_png": local_path(ep), "ego_png_sha256": sha256(ep),
                        "ego_decoded_pixel_sha256": hashlib.sha256(ego[i].tobytes()).hexdigest(),
                        "wrist_aux_png": local_path(wp), "wrist_aux_png_sha256": sha256(wp),
                        "ego_motion_hold": next(h for h in ego_holds if h["start"] <= i <= h["end"]),
                        "ego_exact_pixel_run": next(h for h in ego_exact if h["start"] <= i <= h["end"]),
                        "wrist_motion_hold": next(h for h in wrist_holds if h["start"] <= i <= h["end"]),
                        "wrist_exact_pixel_run": next(h for h in wrist_exact if h["start"] <= i <= h["end"])})
    selected = sorted({(max(lo, h["start"]) + min(hi, h["end"])) // 2 for h in ego_holds
                       if h["length"] >= 8 and h["end"] >= lo and h["start"] <= hi})
    gallery(records, out, selected)
    inventory = {"schema": "usim-dev-lift-chain-inventory/v1", "episode_key": key,
                 "plan_sha256": sha256(out / "analysis_plan.json"), "source_files": sources,
                 "decoded_frames": {"ego": n, "wrist_aux": wrist_n, "parquet": len(state)},
                 "signal": signal, "review_frames_inclusive": [lo, hi], "frames": records,
                 "ego_motion_holds": ego_holds, "ego_exact_pixel_runs": ego_exact,
                 "wrist_motion_holds": wrist_holds, "wrist_exact_pixel_runs": wrist_exact,
                 "gallery_frame_ids": selected, "labels_assigned": False,
                 "annotation_writes": 0, "model_api_calls": 0}
    write_json(out / "frame_inventory.json", inventory)
    print(json.dumps({"episode": args.episode, "out": local_path(out), "review_frames": len(records),
                      "alignment_pass": True, "sources_verified": len(sources),
                      "gallery_frames": selected, "model_api_calls": 0}))


if __name__ == "__main__":
    main()
