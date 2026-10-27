"""Build annotation-ready evidence packages for selected USIM episodes.

For every episode in ``selection.jsonl`` this tool produces, under
``data/usim_enact/_expansion/packages/<episode_key>/``:

* ``package.json`` -- metadata, gripper-signal events, action/state summaries,
  motion bursts, 4-6 proposed key frames (reach / touch / grasp / lift /
  carry / release-settle / end) with per-frame evidence and a +/-10 frame
  stability check, colour-blob statistics, scene descriptors, the L=5 route
  candidates (``transfer_inbox`` / ``release_settle`` / ``touching`` / ``none``)
  with per-transition evidence, and a proposed (NOT written) annotation brief;
* ``sheet_candidates.png`` -- contact sheet of the proposed frames (4 columns,
  frame number burned in);
* ``sheet_timeline.png``  -- 8 evenly spaced frames for scene/background review;
* ``sheet_candidates_wrist.png`` -- wrist view of the same frames (auxiliary
  evidence only; the protocol input stays ego-only).

Nothing here is a label.  The gripper signal is a *proposal* mechanism; every
state still needs visual review (docs/04, docs/06).  The builder never writes
into ``usim-enact-v0.1`` or into ``enact/``.

Usage (PowerShell):
    python scripts/usim/build_episode_package.py
    python scripts/usim/build_episode_package.py --only 1304,1330
    python scripts/usim/build_episode_package.py --no-wrist
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enact.adapters.usim_reader import USIMReader, resolve_dataset_root  # noqa: E402
from scripts.usim.annotate_helper import COLOUR_RANGES, build_sheet, colour_blobs  # noqa: E402

GRIPPER_CLOSED_THRESHOLD = 0.004
STABILITY_HALF_WINDOW = 10
STABILITY_STEP = 2
SCAN_STRIDE = 8
TIMELINE_TILES = 8
MIN_RELEASE_SETTLE_FRAMES = 8
MIN_STATION_GAP = 12
MIN_TARGET_AREA = {"red": 40, "blue": 100}
MAX_TARGET_AREA = {"red": 2500, "blue": 2500}
# The USIM "blue cylinder" renders purple in the ego stream (v0.1 annotation
# note), while the water/background is cyan-blue with hue ~100-110.  The
# annotate_helper "blue" range is too permissive for the ego stream, so target
# tracking uses a purple-biased range for the blue task.  This is an evidence
# detector, not a ground-truth label.
TARGET_RANGES = {
    "red": COLOUR_RANGES["red"],
    "blue": ((112, 155), None, 75, 110),
}
MIN_COMPONENT_AREA = 24
MIN_BOX_AREA = 400
BOX_COLOUR = "green"
TRANSFER_TASK_INDEX = 7
TARGET_COLOURS = {
    "Pick up the pipe": (),
    "Pick up the blue cylinder": ("blue",),
    "Pick up the red cylinder": ("red",),
    "Pick up the red cylinder and transfer it to the box": ("red",),
}
TARGET_OBJECT = {
    "Pick up the pipe": {"object_id": "pipe", "category": "pipe"},
    "Pick up the blue cylinder": {"object_id": "blue_cylinder", "category": "cylinder", "color": "blue"},
    "Pick up the red cylinder": {"object_id": "red_cylinder", "category": "cylinder", "color": "red"},
    "Pick up the red cylinder and transfer it to the box": {
        "object_id": "red_cylinder",
        "category": "cylinder",
        "color": "red",
    },
}
STATE_SLICES = {
    "joint_pos": (0, 5),
    "pwm": (5, 13),
    "joint_v": (13, 18),
    "dvl_v": (18, 21),
    "imu_av": (21, 24),
    "imu_la": (24, 27),
    "pressure": (27, 28),
    "dvl_h": (28, 29),
}
ACTION_SLICES = {"joint_pos": (0, 5), "pwm": (5, 13)}


# ------------------------------------------------------------------------ utils
def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def round_list(values, digits: int = 3) -> List[float]:
    return [round(float(value), digits) for value in np.asarray(values).reshape(-1)]


def clamp(value: int, low: int, high: int) -> int:
    return int(max(low, min(high, value)))


def load_selection(path: Path) -> List[Dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def colour_components(frame: np.ndarray, colour: str) -> List[Dict]:
    """Connected components for one colour range (annotate_helper thresholds).

    ``annotate_helper.colour_blobs`` only returns the single largest component;
    for the blue task the water background itself can be the largest "blue"
    blob, so target tracking needs the component list plus a border/large-blob
    filter.  This is evidence collection, not ground truth.
    """
    low, high, sat_min, val_min = TARGET_RANGES.get(colour, COLOUR_RANGES[colour])
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hue = hsv[:, :, 0].astype(np.int16)
    mask = np.zeros(hue.shape, dtype=bool)
    for bounds in (low, high):
        if bounds is None:
            continue
        mask |= (hue >= bounds[0]) & (hue <= bounds[1])
    mask &= (hsv[:, :, 1] >= sat_min) & (hsv[:, :, 2] >= val_min)
    mask_u8 = cv2.morphologyEx((mask.astype(np.uint8)) * 255, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    height, width = frame.shape[:2]
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask_u8, 8)
    components: List[Dict] = []
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        if area < MIN_COMPONENT_AREA:
            continue
        x = int(stats[index, cv2.CC_STAT_LEFT])
        y = int(stats[index, cv2.CC_STAT_TOP])
        w = int(stats[index, cv2.CC_STAT_WIDTH])
        h = int(stats[index, cv2.CC_STAT_HEIGHT])
        touches_border = x <= 1 or y <= 1 or (x + w) >= width - 1 or (y + h) >= height - 1
        components.append(
            {
                "colour": colour,
                "area": area,
                "cx": round(float(centroids[index][0]), 1),
                "cy": round(float(centroids[index][1]), 1),
                "bbox": [x, y, w, h],
                "touches_border": bool(touches_border),
            }
        )
    return components


def pick_target(frame: np.ndarray, colours: Sequence[str]) -> Tuple[Optional[Dict], int]:
    """Best compact target-colour component and the number of ambiguities.

    Filters out border-touching / oversized components (water background) and
    components in the top third of the frame (background decorations), and
    reports how many plausible same-colour components remain, because multiple
    same-class instances cannot be uniquely referenced in the ego stream.
    """
    best = None
    ambiguous_count = 0
    height = frame.shape[0]
    for colour in colours:
        components = colour_components(frame, colour)
        usable = [
            component
            for component in components
            if MIN_TARGET_AREA.get(colour, 40) <= component["area"] <= MAX_TARGET_AREA.get(colour, 2500)
            and not component["touches_border"]
            and component["cy"] >= 0.30 * height
        ]
        if not usable:
            continue
        usable.sort(key=lambda component: component["area"], reverse=True)
        ambiguous_count += len(usable)
        if best is None or usable[0]["area"] > best["area"]:
            best = dict(usable[0])
    if best is not None:
        best["component_count"] = ambiguous_count
        best["ambiguous"] = ambiguous_count > 1
    return best, ambiguous_count


def box_blob(blobs: Dict[str, Dict]) -> Optional[Dict]:
    blob = blobs.get(BOX_COLOUR) or {}
    area = int(blob.get("area") or 0)
    if area < MIN_BOX_AREA:
        return None
    return {
        "colour": BOX_COLOUR,
        "area": area,
        "cx": round(float(blob["cx"]), 1),
        "cy": round(float(blob["cy"]), 1),
        "bbox": [int(blob["x"]), int(blob["y"]), int(blob["w"]), int(blob["h"])],
    }


def bbox_contains(outer: Sequence[int], point: Tuple[float, float]) -> bool:
    x, y, w, h = outer
    return bool(x <= point[0] <= x + w and y <= point[1] <= y + h)


def motion_window(motion: np.ndarray, frame: int, half: int = STABILITY_HALF_WINDOW) -> Dict:
    low = max(0, frame - half)
    high = min(len(motion) - 1, frame + half)
    window = np.asarray(motion[low:high + 1], dtype=np.float64)
    finite = window[np.isfinite(window)]
    if finite.size == 0:
        return {"window": [low, high], "mean": 0.0, "max": 0.0, "min": 0.0}
    return {
        "window": [int(low), int(high)],
        "mean": round(float(finite.mean()), 3),
        "max": round(float(finite.max()), 3),
        "min": round(float(finite.min()), 3),
    }


def slice_summary(array: np.ndarray, slices: Dict[str, Tuple[int, int]]) -> Dict:
    summary = {}
    for name, (start, stop) in slices.items():
        block = np.asarray(array[:, start:stop], dtype=np.float64)
        summary[name] = {
            "mean": round_list(block.mean(axis=0), 4),
            "std": round_list(block.std(axis=0), 4),
            "min": round_list(block.min(axis=0), 4),
            "max": round_list(block.max(axis=0), 4),
        }
    return summary


def events_from_joint0(joint0: np.ndarray, timestamps: np.ndarray) -> Dict:
    closed = joint0 > GRIPPER_CLOSED_THRESHOLD
    events: List[Dict] = []
    for index in range(1, len(closed)):
        if closed[index] and not closed[index - 1]:
            events.append({"event": "close", "frame": int(index)})
        elif not closed[index] and closed[index - 1]:
            events.append({"event": "open", "frame": int(index)})
    for event in events:
        event["timestamp_seconds"] = round(float(timestamps[event["frame"]]), 3)
        event["index"] = len(events)
    final_open = events[-1] if events and events[-1]["event"] == "open" else None
    first_close = next((event for event in events if event["event"] == "close"), None)
    last_close = next((event for event in reversed(events) if event["event"] == "close"), None)
    return {
        "signal": "observation.state[0] (joint_pos[0]); > %.3f means closed" % GRIPPER_CLOSED_THRESHOLD,
        "threshold": GRIPPER_CLOSED_THRESHOLD,
        "range": [round(float(joint0.min()), 5), round(float(joint0.max()), 5)],
        "closed_frames": int(closed.sum()),
        "closed_fraction": round(float(closed.mean()), 4),
        "events": events,
        "event_count": len(events),
        "final_state": "closed" if closed[-1] else "open",
        "first_close_frame": int(first_close["frame"]) if first_close else None,
        "last_close_frame": int(last_close["frame"]) if last_close else None,
        "last_open_frame": int(final_open["frame"]) if final_open else None,
        "frames_after_final_open": (
            int(len(joint0) - 1 - final_open["frame"]) if final_open is not None else None
        ),
    }


# ---------------------------------------------------------------- video passes
def scan_video(reader: USIMReader, episode_index: int, length: int) -> Dict:
    """Sequential decode #1: per-frame motion + every STRIDE-th frame (full res)."""
    motion = np.zeros(length, dtype=np.float64)
    stride_frames: Dict[int, np.ndarray] = {}
    previous = None
    decoded = 0
    for index, frame in reader.iter_frames(episode_index, camera="ego"):
        if index >= length:
            break
        grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
        if previous is not None:
            motion[index] = float(np.mean(np.abs(grey - previous)))
        previous = grey
        if index % SCAN_STRIDE == 0:
            stride_frames[index] = frame
        decoded += 1
    return {"motion": motion, "stride_frames": stride_frames, "decoded_frames": decoded}


def decode_requests(reader: USIMReader, episode_index: int, frames: Sequence[int], length: int) -> Tuple[Dict[int, np.ndarray], int]:
    """Sequential decode #2: capture only the requested frames (no seek reliance)."""
    wanted = sorted({clamp(frame, 0, length - 1) for frame in frames})
    wanted_set = set(wanted)
    captured: Dict[int, np.ndarray] = {}
    decoded = 0
    for index, frame in reader.iter_frames(episode_index, camera="ego"):
        if index >= length:
            break
        decoded += 1
        if index in wanted_set:
            captured[index] = frame
    missing = wanted_set - set(captured)
    if missing:
        warnings = f"frames not decoded: {sorted(missing)}"
        raise RuntimeError(warnings)
    return captured, decoded


# ----------------------------------------------------------------- candidates
def choose_candidates(gripper: Dict, stride_frames: Dict[int, np.ndarray], length: int,
                      task_text: str) -> Tuple[List[Dict], Dict, List[str]]:
    """Propose 4-6 key frames from the gripper lifecycle (signal + blob tracking).

    The *successful* grasp is anchored on the last close before the final
    release (or the last close when the object is held to the end); earlier
    close/open pairs are failed grasp attempts (``COC...`` gripper patterns) and
    are reported separately instead of being used as lifecycle stations.
    ``lift`` is a mid-hold proposal: blob vertical motion is not reliable because
    the ego camera moves with the arm, so it must be visually confirmed.
    """
    notes: List[str] = []
    stride = sorted(stride_frames)
    colours = TARGET_COLOURS.get(task_text, ())

    def stride_target(frame: int) -> Optional[Dict]:
        blob, _ = pick_target(stride_frames[frame], colours)
        return blob

    close_events = [event for event in gripper["events"] if event["event"] == "close"]
    last_open = gripper["last_open_frame"]
    final_open = gripper["final_state"] == "open"
    retry_attempts = max(0, len(close_events) - 1)
    if retry_attempts:
        notes.append(
            f"{retry_attempts} extra close event(s): failed grasp attempts / retries; "
            "the lifecycle is anchored on the last close"
        )

    if not close_events:
        notes.append("no gripper close event found; falling back to evenly spaced frames")
        grasp_event = length // 2
        approach_event = clamp(grasp_event - 40, 0, length - 1)
        grasp = clamp(grasp_event + 15, 0, length - 1)
        approach = clamp(approach_event - 40, 0, length - 1)
        touch = None
        start = 0
    else:
        grasp_event = int(close_events[-1]["frame"])
        # approach is anchored on the FIRST close command (start of the
        # manipulation attempt); retries between first and last close are
        # reported but not used as lifecycle stations.
        approach_event = int(close_events[0]["frame"])
        grasp = clamp(grasp_event + 15, 0, length - 1)
        approach = clamp(approach_event - 40, 0, length - 1)
        touch = clamp(grasp_event + 2, 0, length - 1) if not final_open else None

        # first sampled frame where the target colour is visible on the seabed
        visible_frames = [frame for frame in stride if stride_target(frame) is not None]
        if visible_frames:
            start = visible_frames[0]
        else:
            start = max(0, approach_event - 90)
            notes.append("start frame derived from a fixed offset (target blob not found)")

    if start >= approach:
        approach = clamp(start + 8, 0, length - 1)
        notes.append("approach station moved after the start station (late object visibility)")

    if final_open and last_open is not None:
        hold_start = clamp(grasp_event + 10, 0, length - 1)
        hold_end = clamp(last_open - 15, hold_start + 10, length - 1)
        lift = clamp(hold_start + int(0.5 * (hold_end - hold_start)), hold_start + 10, hold_end - 5)
        carry = hold_end
        settle = clamp(last_open + 15, 0, length - 1)
        if length - 1 - settle >= 8:
            settle = clamp(last_open + 20, 0, length - 1)
    else:
        hold_start = clamp(grasp_event + 10, 0, length - 1)
        hold_end = clamp(length - 3, hold_start + 10, length - 1)
        # keep the "lift" station close to the end so it is clearly distinct
        # from "grasp"; if video end is very near, the end station is dropped
        lift = clamp(max(grasp_event + 80, hold_end - 20), hold_start + 10, hold_end)
        carry = None
        settle = None

    specs: List[Tuple[str, int, str]] = [
        ("start", clamp(start, 0, length - 1), "object on the seabed, before the approach"),
        ("approach", approach, "robot next to the object, before the close command"),
    ]
    if touch is not None:
        specs.append(("touch", touch, "gripper closing around the object (Touching candidate, needs review)"))
    specs.append(("grasp", grasp, "after the successful close event; object held"))
    specs.append(("lift", lift, "mid-hold station; Lifted must be visually confirmed"))
    if final_open and last_open is not None:
        specs.append(("carry", carry, "object carried, before the final release"))
        specs.append(("release_settle", settle, "0.5-2 s after release, object should be settling"))
    else:
        specs.append(("end", clamp(length - 2, 0, length - 1), "video end; object still held"))

    specs.sort(key=lambda item: item[1])
    chosen: List[Dict] = []
    for role, frame, why in specs:
        if chosen and frame - chosen[-1]["frame_index"] < 8:
            notes.append(
                f"role {role}@f{frame} dropped: <8 frames from {chosen[-1]['role']}@f{chosen[-1]['frame_index']}"
            )
            continue
        chosen.append({"role": role, "frame_index": int(frame), "rationale": why})
    if len(chosen) < 4:
        notes.append(f"only {len(chosen)} candidate frames after de-duplication")
    metadata = {
        "grasp_event_frame": int(grasp_event),
        "approach_event_frame": int(approach_event) if close_events else None,
        "first_close_frame": gripper["first_close_frame"],
        "last_close_frame": gripper["last_close_frame"],
        "last_open_frame": last_open,
        "retry_attempts": retry_attempts,
        "target_colours": list(colours),
        "candidate_count": len(chosen),
        "lift_note": "lift station is a mid-hold proposal; camera ego-motion makes blob rise unreliable",
    }
    return chosen, metadata, notes


# ------------------------------------------------------------------- stability
def stability_check(motion: np.ndarray, frame: int, frames: Dict[int, np.ndarray],
                    colours: Sequence[str], events: List[Dict]) -> Dict:
    length = len(motion)
    low = max(0, frame - STABILITY_HALF_WINDOW)
    high = min(length - 1, frame + STABILITY_HALF_WINDOW)
    sample = sorted(set(range(low, high + 1, STABILITY_STEP)) | {frame})
    motion_stats = motion_window(motion, frame)
    presence = 0
    centroids: List[Tuple[float, float]] = []
    for sample_frame in sample:
        blob, _ = pick_target(frames[sample_frame], colours)
        if blob is not None:
            presence += 1
            centroids.append((blob["cx"], blob["cy"]))
    present_fraction = round(presence / len(sample), 3) if sample else 0.0
    centroid_span = 0.0
    if len(centroids) >= 2:
        coords = np.asarray(centroids, dtype=np.float64)
        centroid_span = round(float(np.linalg.norm(coords - coords.mean(axis=0), axis=1).max()), 1)
    nearest_events = [
        {"event": event["event"], "frame": event["frame"], "offset": int(event["frame"] - frame)}
        for event in events
        if abs(event["frame"] - frame) <= STABILITY_HALF_WINDOW
    ]
    baseline = motion[motion > 0]
    threshold = round(float(max(0.8, 1.2 * np.percentile(baseline, 75))), 3) if baseline.size else 1.0
    reasons: List[str] = []
    if motion_stats["mean"] > threshold:
        reasons.append(f"window motion {motion_stats['mean']} > threshold {threshold}")
    if colours and present_fraction < 0.6:
        reasons.append(f"target blob present in only {present_fraction:.0%} of the window samples")
    if centroid_span > 20.0:
        reasons.append(f"target centroid span {centroid_span}px > 20px")
    if nearest_events:
        reasons.append("gripper event inside the +/-10 frame window")
    return {
        "window": motion_stats["window"],
        "sample_frames": sample,
        "sample_count": len(sample),
        "motion": motion_stats,
        "motion_threshold": threshold,
        "target_present_fraction": present_fraction,
        "target_centroid_span_px": centroid_span,
        "nearest_gripper_events": nearest_events,
        "stable": len(reasons) == 0,
        "reasons": reasons,
    }


def background_descriptors(frames: Dict[int, np.ndarray]) -> Dict:
    if not frames:
        return {"hint": "unknown", "frames": 0}
    hsv_values: List[np.ndarray] = []
    bgr_values: List[np.ndarray] = []
    edges: List[float] = []
    for frame in frames.values():
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        hsv_values.append(hsv.reshape(-1, 3).mean(axis=0))
        bgr_values.append(frame.reshape(-1, 3).mean(axis=0))
        grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        edges.append(float((cv2.Canny(grey, 60, 140) > 0).mean()))
    hsv_mean = np.asarray(hsv_values).mean(axis=0)
    bgr_mean = np.asarray(bgr_values).mean(axis=0)
    brightness = float(hsv_mean[2])
    if brightness >= 150 and float(bgr_mean[2]) >= 120:
        hint = "bright_shallow_like"
    elif brightness <= 135:
        hint = "dark_factory_like"
    else:
        hint = "ambiguous"
    return {
        "hint": hint,
        "note": "heuristic only (brightness/colour of sampled frames); factory vs shallow is NOT verified",
        "frames": len(frames),
        "mean_bgr": [round(float(value), 1) for value in bgr_mean],
        "mean_hsv": [round(float(value), 1) for value in hsv_mean],
        "edge_density": round(float(np.mean(edges)), 4),
    }


# ------------------------------------------------------------------------ L=5
def predicate_key(predicate: str, *arguments: str) -> str:
    return f"{predicate}|{','.join(arguments)}"


def state_hypothesis(role: str, task_text: str, target_id: str) -> Dict[str, object]:
    """Heuristic predicate snapshot per lifecycle role (hypothesis, not a label)."""
    transfer = task_text == "Pick up the red cylinder and transfer it to the box"
    states: Dict[str, object] = {
        predicate_key("OnSeabed", target_id): False,
        predicate_key("InGripper", target_id): False,
        predicate_key("Lifted", target_id): False,
        predicate_key("NextTo", "robot", target_id): False,
    }
    if role == "start":
        states[predicate_key("OnSeabed", target_id)] = True
    elif role == "approach":
        states[predicate_key("OnSeabed", target_id)] = True
        states[predicate_key("NextTo", "robot", target_id)] = True
    elif role == "touch":
        states[predicate_key("OnSeabed", target_id)] = True
        states[predicate_key("Touching", "robot", target_id)] = True
    elif role == "grasp":
        states[predicate_key("InGripper", target_id)] = True
    elif role == "lift":
        states[predicate_key("InGripper", target_id)] = True
        states[predicate_key("Lifted", target_id)] = True
    elif role == "carry":
        states[predicate_key("InGripper", target_id)] = True
        states[predicate_key("Lifted", target_id)] = True
        if transfer:
            states[predicate_key("NextTo", "robot", "green_box")] = True
    elif role == "release_settle":
        if transfer:
            states[predicate_key("InBox", target_id)] = True
            states[predicate_key("NextTo", "robot", "green_box")] = True
        else:
            states[predicate_key("OnSeabed", target_id)] = True
    elif role == "end":
        states[predicate_key("InGripper", target_id)] = True
        states[predicate_key("Lifted", target_id)] = True
    return states


def transition_changes(before: Dict[str, object], after: Dict[str, object]) -> List[Dict]:
    changes = []
    for key in sorted(set(before) | set(after)):
        old = before.get(key)
        new = after.get(key)
        if old == new:
            continue
        predicate, arguments = key.split("|", 1)
        changes.append(
            {
                "predicate": predicate,
                "arguments": arguments.split(","),
                "before": old,
                "after": new,
            }
        )
    return changes


def transition_evidence(change_list: List[Dict], frame_a: int, frame_b: int, gripper: Dict,
                        candidates: Dict[str, Dict]) -> str:
    parts = [
        f"{item['predicate']}({','.join(item['arguments'])}): "
        f"{str(item['before']).lower()} -> {str(item['after']).lower()}"
        for item in change_list
    ]
    if any(item["predicate"] == "InGripper" for item in change_list):
        if gripper.get("first_close_frame") is not None:
            parts.append(f"gripper close event at f{gripper['first_close_frame']}")
    if any(item["predicate"] == "Lifted" for item in change_list):
        parts.append("target centroid rises between the two frames (blob tracking)")
    if any(item["predicate"] == "InBox" for item in change_list):
        if gripper.get("last_open_frame") is not None:
            parts.append(f"release (gripper open) at f{gripper['last_open_frame']}; settle frames inspected")
    if any(item["predicate"] == "NextTo" and "green_box" in item["arguments"] for item in change_list):
        parts.append("green box enters/large in the ego frame (heuristic blob area)")
    evidence_a = candidates.get("a", {}).get("evidence", "")
    evidence_b = candidates.get("b", {}).get("evidence", "")
    parts.append(f"frames f{frame_a} -> f{frame_b}")
    if not change_list:
        parts.append("no predicate change (not usable as a transition)")
    return "; ".join(parts)


def l5_analysis(gripper: Dict, task_text: str, candidates: List[Dict], candidate_by_role: Dict[str, Dict],
                boxes: Dict[int, Optional[Dict]], targets: Dict[int, Optional[Dict]], length: int) -> Dict:
    transfer = task_text == "Pick up the red cylinder and transfer it to the box"
    target_id = TARGET_OBJECT.get(task_text, {}).get("object_id", "target_object")
    first_close = gripper.get("first_close_frame")
    last_open = gripper.get("last_open_frame")
    frames_after = gripper.get("frames_after_final_open")
    route_candidates: List[Dict] = []
    candidate_map = {
        item["role"]: item for item in candidates
    }

    def role_frames(roles: Sequence[str]) -> Optional[List[Dict]]:
        out = []
        for role in roles:
            item = candidate_map.get(role)
            if item is None:
                return None
            out.append(item)
        return out

    def build_route(route: str, roles: Sequence[str], available: bool, confidence: str,
                    requirements: Sequence[str], risks: Sequence[str], notes: str = "") -> Dict:
        items = role_frames(roles) or []
        # Merge stations that are < MIN_STATION_GAP frames apart: they are not
        # visually separable and cannot carry an independent transition.
        kept: List[Dict] = []
        merged: List[str] = []
        for item in items:
            if kept and item["frame_index"] - kept[-1]["frame_index"] < MIN_STATION_GAP:
                merged.append(item["role"])
                continue
            kept.append(item)
        states = [
            {
                "role": item["role"],
                "frame_index": item["frame_index"],
                "predicates_hypothesis": {
                    key: value
                    for key, value in state_hypothesis(item["role"], task_text, target_id).items()
                },
                "hypothesis": True,
                "evidence": item["evidence"],
            }
            for item in kept
        ]
        transitions = []
        for left, right in zip(states, states[1:]):
            changes = transition_changes(left["predicates_hypothesis"], right["predicates_hypothesis"])
            transitions.append(
                {
                    "from": left["role"],
                    "to": right["role"],
                    "changes": changes,
                    "visible_if_hypothesis_holds": bool(changes),
                    "evidence": transition_evidence(
                        changes,
                        left["frame_index"],
                        right["frame_index"],
                        gripper,
                        {"a": left, "b": right},
                    ),
                }
            )
        return {
            "route": route,
            "available": bool(available),
            "confidence": confidence,
            "needs_review": True,
            "states": states,
            "merged_roles": merged,
            "transitions": transitions,
            "num_states": len(states),
            "num_distinguishable_transitions": sum(
                1 for transition in transitions if transition["visible_if_hypothesis_holds"]
            ),
            "required_relations": list(requirements),
            "risks": list(risks),
            "notes": notes,
        }

    def filtered_station_count(roles: Sequence[str]) -> int:
        items = role_frames(roles) or []
        count = 0
        previous = None
        for item in items:
            if previous is not None and item["frame_index"] - previous < MIN_STATION_GAP:
                continue
            count += 1
            previous = item["frame_index"]
        return count

    touching = candidate_map.get("touch")
    if transfer and last_open is not None and int(frames_after or 0) >= MIN_RELEASE_SETTLE_FRAMES:
        settle = candidate_map.get("release_settle") or {}
        settle_blob = targets.get(settle.get("frame_index"), None)
        settle_box = boxes.get(settle.get("frame_index"), None)
        inside = False
        if settle_blob is not None and settle_box is not None:
            inside = bbox_contains(settle_box["bbox"], (settle_blob["cx"], settle_blob["cy"]))
        route_candidates.append(
            build_route(
                "transfer_inbox",
                ["start", "approach", "grasp", "lift", "carry", "release_settle"],
                available=True,
                confidence="signal+blob evidence" if settle_blob is not None and settle_box is not None
                else "signal evidence; object not detected after release",
                requirements=["InBox(red_cylinder)", "visibility of the object after release"],
                risks=[
                    "v0.1 episode 1302 released the object above the box rim and it never settled inside",
                    "InBox needs the object visibly resting in the box for several frames",
                ],
                notes=(
                    f"release at f{last_open}, {frames_after} frames to settle; "
                    f"settle frame blob present={settle_blob is not None}, box present={settle_box is not None}, "
                    f"target centroid inside box bbox={inside}"
                ),
            )
        )
        route_candidates.append(
            build_route(
                "transfer_at_box",
                ["start", "approach", "grasp", "lift", "carry"],
                available=True,
                confidence="blob evidence (box visible)",
                requirements=["NextTo(robot, green_box)"],
                risks=["NextTo still needs a documented distance criterion; ego-only judgement"],
                notes="fallback 5th state if InBox cannot be established; green box is visible while carrying",
            )
        )
    if (not transfer) and last_open is not None and int(frames_after or 0) >= MIN_RELEASE_SETTLE_FRAMES:
        route_candidates.append(
            build_route(
                "release_settle",
                ["start", "approach", "grasp", "lift", "release_settle"],
                available=True,
                confidence="signal+blob evidence",
                requirements=["OnSeabed(target) true again after the release"],
                risks=["object must be visible on the seabed after release; sinking may hide it"],
                notes=f"release at f{last_open}, {frames_after} frames to settle",
            )
        )
    if touching is not None and first_close is not None:
        route_candidates.append(
            build_route(
                "touching",
                ["start", "approach", "touch", "grasp", "lift"],
                available=True,
                confidence="weak; needs visual review",
                requirements=["Touching(robot, target) visible in ego between NextTo and InGripper"],
                risks=[
                    "gripper close command can land 10-40 frames before the object is actually held",
                    "contact may be hard to distinguish from 'next to' in the ego stream",
                ],
                notes=f"close command at f{first_close}; touch candidate at f{touching['frame_index']}",
            )
        )
    if not route_candidates:
        route_candidates.append(
            {
                "route": "none",
                "available": False,
                "confidence": "no L=5 route evidence",
                "needs_review": True,
                "states": [],
                "transitions": [],
                "num_states": 4 if candidate_map.get("lift") else 3,
                "num_distinguishable_transitions": 3 if candidate_map.get("lift") else 2,
                "required_relations": [],
                "risks": ["no release and no transfer: L=5 via existing predicates not evidenced"],
                "notes": "finite lifecycle: OnSeabed -> NextTo -> InGripper -> Lifted (L<=4)",
            }
        )

    priority = {"transfer_inbox": 0, "release_settle": 1, "transfer_at_box": 2, "touching": 3, "none": 9}
    route_candidates.sort(key=lambda item: priority.get(item["route"], 8))
    primary = route_candidates[0]
    baseline = filtered_station_count(["start", "approach", "grasp", "lift"])
    if baseline < 3:
        baseline = min(3, sum(1 for role in ("start", "approach", "grasp", "lift") if candidate_map.get(role)))
    optimistic = (
        primary["num_states"]
        if primary["available"] and primary["route"] != "none"
        else baseline
    )
    if primary["route"] == "transfer_inbox":
        if optimistic >= 6:
            conclusion = (
                "L=5/6 possible if the object is visibly inside the box after release and every "
                "station is visually separable; L=5 is also reachable via transfer_at_box "
                "(NextTo(robot, green_box)) if InBox cannot be established."
            )
        elif optimistic >= 5:
            conclusion = (
                "L=5 possible if the final release leaves the object visibly inside the box; "
                "otherwise fall back to transfer_at_box (NextTo(robot, green_box)) or L=4."
            )
        else:
            conclusion = (
                "L=4 baseline (start->approach->grasp->lift); L=5 needs a station merged because "
                "frames are too close - review the candidate sheet."
            )
    elif primary["route"] == "release_settle":
        conclusion = "L=5 possible if the released object is visibly back on the seabed."
    elif primary["route"] == "touching":
        conclusion = (
            f"L={baseline} is solid; L={optimistic} only if the Touching(robot, object) state between "
            "NextTo and InGripper is visually distinguishable (needs review)."
        )
    else:
        conclusion = "L=4 maximum under the current predicate set; no L=5 evidence."
    return {
        "route": primary["route"],
        "route_candidates": route_candidates,
        "l_max_states_baseline": baseline,
        "l_max_states_optimistic": optimistic,
        "l5_target_feasible": bool(primary["available"] and optimistic >= 5),
        "needs_review": True,
        "conclusion": conclusion,
    }


# ----------------------------------------------------------------------- build
def build_package(reader: USIMReader, row: Dict, out_root: Path, dataset_root: Path,
                  include_wrist: bool = True) -> Dict:
    episode_index = int(row["episode_index"])
    episode = reader.episode(episode_index)
    length = int(episode.length)
    table = reader.load_table(episode_index)
    state = np.stack([np.asarray(value, dtype=np.float64) for value in table["observation.state"]])
    action = np.stack([np.asarray(value, dtype=np.float64) for value in table["action"]])
    timestamps = np.asarray(table["timestamp"], dtype=np.float64)
    joint0 = state[:, 0]
    gripper = events_from_joint0(joint0, timestamps)

    scan = scan_video(reader, episode_index, length)
    motion = scan["motion"]
    stride_frames = scan["stride_frames"]
    warnings: List[str] = []
    if scan["decoded_frames"] != length:
        warnings.append(
            f"ego video decoded {scan['decoded_frames']} frames but parquet has {length} rows"
        )

    candidates, candidate_meta, candidate_notes = choose_candidates(
        gripper, stride_frames, length, episode.task_text
    )

    # frames needed: candidates, their +/-10 stability windows, timeline
    requested = set(item["frame_index"] for item in candidates)
    for item in candidates:
        low = max(0, item["frame_index"] - STABILITY_HALF_WINDOW)
        high = min(length - 1, item["frame_index"] + STABILITY_HALF_WINDOW)
        requested.update(range(low, high + 1, STABILITY_STEP))
    timeline_frames = sorted(
        {round(number * (length - 1) / (TIMELINE_TILES - 1)) for number in range(TIMELINE_TILES)}
    )
    requested.update(timeline_frames)
    frames, decoded_second = decode_requests(reader, episode_index, sorted(requested), length)
    if decoded_second != length:
        warnings.append(f"second ego decode saw {decoded_second} frames (expected {length})")

    blobs = {frame: colour_blobs(frames[frame]) for frame in frames if frame in frames}
    colours = TARGET_COLOURS.get(episode.task_text, ())
    target_at = {frame: pick_target(frames[frame], colours)[0] for frame in frames}
    target_count_at = {frame: pick_target(frames[frame], colours)[1] for frame in frames}
    box_at = {frame: box_blob(blobs[frame]) for frame in frames}

    candidate_entries = []
    for item in candidates:
        frame = item["frame_index"]
        stability = stability_check(motion, frame, frames, colours, gripper["events"])
        target = target_at.get(frame)
        box = box_at.get(frame)
        evidence_bits = [item["rationale"]]
        if not colours:
            evidence_bits.append("grey pipe: no colour signature by design; rely on motion/robot pose review")
        elif target is None:
            evidence_bits.append("target colour blob NOT detected at this frame")
        else:
            evidence_bits.append(
                f"target blob {target['colour']} area={target['area']} centroid=({target['cx']},{target['cy']})"
            )
            if target.get("ambiguous"):
                evidence_bits.append(
                    f"{target['component_count']} same-colour components: instance reference needs review"
                )
        if box is not None:
            evidence_bits.append(f"green box blob area={box['area']} bbox={box['bbox']}")
        if gripper["first_close_frame"] is not None:
            evidence_bits.append(
                f"offset to first close command f{gripper['first_close_frame']}: "
                f"{frame - gripper['first_close_frame']:+d} frames"
            )
        if candidate_meta.get("grasp_event_frame") is not None:
            evidence_bits.append(
                f"offset to successful close f{candidate_meta['grasp_event_frame']}: "
                f"{frame - candidate_meta['grasp_event_frame']:+d} frames"
            )
        if gripper["last_open_frame"] is not None:
            evidence_bits.append(
                f"offset to release event f{gripper['last_open_frame']}: "
                f"{frame - gripper['last_open_frame']:+d} frames"
            )
        evidence_bits.append(
            "stability: %s (motion mean %.2f, target present %.0f%%, centroid span %.1fpx)"
            % (
                "stable" if stability["stable"] else "unstable",
                stability["motion"]["mean"],
                100.0 * stability["target_present_fraction"],
                stability["target_centroid_span_px"],
            )
        )
        if stability["reasons"]:
            evidence_bits.append("stability flags: " + "; ".join(stability["reasons"]))
        candidate_entries.append(
            {
                "role": item["role"],
                "frame_index": int(frame),
                "timestamp_seconds": round(float(timestamps[frame]), 3),
                "evidence": "; ".join(evidence_bits),
                "target_blob": target,
                "box_blob": box,
                "stability": stability,
            }
        )
    candidate_by_role = {item["role"]: item for item in candidate_entries}
    ambiguous_frames = [
        item["frame_index"]
        for item in candidate_entries
        if item["target_blob"] is not None and item["target_blob"].get("ambiguous")
    ]
    if ambiguous_frames:
        warnings.append(
            "multiple same-colour components at candidate frame(s) "
            f"{ambiguous_frames}: instance reference must be reviewed"
        )
    target_tracking = {
        "method": "colour components (annotate_helper COLOUR_RANGES), border/oversize filtered",
        "note": (
            "for blue tasks the water background is a large blue component and is filtered by the "
            "border/oversize rule; same-colour distractor objects are only counted, not separated"
        ),
        "ambiguous_candidate_frames": ambiguous_frames,
    }

    # ------------------------------------------------------------- contact sheets
    package_dir = out_root / episode.key
    package_dir.mkdir(parents=True, exist_ok=True)
    candidate_tiles = [
        (f"{item['role']} f{item['frame_index']}", frames[item["frame_index"]])
        for item in candidate_entries
    ]
    candidate_sheet = package_dir / "sheet_candidates.png"
    if not cv2.imwrite(str(candidate_sheet), build_sheet(candidate_tiles, columns=4)):
        raise RuntimeError(f"failed to write {candidate_sheet}")
    timeline_tiles = [(f"f{frame}", frames[frame]) for frame in timeline_frames]
    timeline_sheet = package_dir / "sheet_timeline.png"
    if not cv2.imwrite(str(timeline_sheet), build_sheet(timeline_tiles, columns=4)):
        raise RuntimeError(f"failed to write {timeline_sheet}")

    sheets = {
        "candidates": {
            "path": "sheet_candidates.png",
            "layout": "4 columns, frame number + lifecycle role burned in",
            "sha256": sha256_file(candidate_sheet),
            "frames": [item["frame_index"] for item in candidate_entries],
        },
        "timeline": {
            "path": "sheet_timeline.png",
            "layout": "4 columns, 8 evenly spaced frames",
            "sha256": sha256_file(timeline_sheet),
            "frames": timeline_frames,
        },
    }
    if include_wrist:
        try:
            wrist_frames, _ = decode_requests(
                USIMReader(dataset_root, split=episode.split),
                episode_index,
                [item["frame_index"] for item in candidate_entries],
                length,
            )
            wrist_tiles = [
                (f"{item['role']} f{item['frame_index']}", wrist_frames[item["frame_index"]])
                for item in candidate_entries
            ]
            wrist_sheet = package_dir / "sheet_candidates_wrist.png"
            if cv2.imwrite(str(wrist_sheet), build_sheet(wrist_tiles, columns=4)):
                sheets["candidates_wrist"] = {
                    "path": "sheet_candidates_wrist.png",
                    "layout": "4 columns, wrist camera, same frames (auxiliary evidence only)",
                    "sha256": sha256_file(wrist_sheet),
                    "frames": [item["frame_index"] for item in candidate_entries],
                }
            else:
                warnings.append("failed to write wrist contact sheet")
        except Exception as exc:  # pragma: no cover - video decode guard
            warnings.append(f"wrist view unavailable: {exc}")

    # ------------------------------------------------------------------ metadata
    parquet_path = reader.parquet_path(episode_index)
    ego_path = reader.video_path(episode_index, "ego")
    wrist_path = reader.video_path(episode_index, "wrist")
    motion_nonzero = motion[motion > 0]
    top_bursts = []
    if motion_nonzero.size:
        order = np.argsort(motion)[::-1][:5]
        top_bursts = [
            {"frame_index": int(index), "motion": round(float(motion[index]), 3)}
            for index in sorted(int(value) for value in order)
        ]
    scene = background_descriptors({frame: frames[frame] for frame in timeline_frames})
    l5 = l5_analysis(gripper, episode.task_text, candidate_entries, candidate_by_role, box_at, target_at, length)

    target_object = dict(TARGET_OBJECT.get(episode.task_text, {}))
    primary_route = l5["route_candidates"][0]
    primary_route_roles = [state["role"] for state in primary_route["states"]]
    annotation_brief = {
        "note": "PROPOSAL ONLY - this package is not an annotation; every state needs visual review",
        "objects": [
            {"object_id": "robot", "category": "agent", "description": "the robot"},
            {
                "object_id": target_object.get("object_id", "target_object"),
                "category": target_object.get("category", "object"),
                **({"color": target_object["color"]} if target_object.get("color") else {}),
                "description": f"the {target_object.get('color', '') + ' ' if target_object.get('color') else ''}"
                f"{target_object.get('category', 'object')}".strip(),
            },
            *(
                [{"object_id": "green_box", "category": "box", "color": "green",
                  "description": "the green box"}]
                if episode.task_index == TRANSFER_TASK_INDEX
                else []
            ),
        ],
        "base_relations": [
            ["OnSeabed", target_object.get("object_id", "target_object")],
            ["InGripper", target_object.get("object_id", "target_object")],
            ["Lifted", target_object.get("object_id", "target_object")],
            ["NextTo", "robot", target_object.get("object_id", "target_object")],
        ],
        "l4_key_frame_roles": ["start", "approach", "grasp", "lift"],
        "l5_key_frame_roles": primary_route_roles[:5],
        "l5_key_frame_roles_if_six": primary_route_roles[:6] if len(primary_route_roles) > 5 else [],
        "l5_extra_relations": primary_route["required_relations"],
        "l5_confidence": primary_route["confidence"],
        "l5_risks": primary_route["risks"],
        "candidate_by_role": {
            item["role"]: item["frame_index"] for item in candidate_entries
        },
    }

    package = {
        "schema_version": 1,
        "builder": "scripts/usim/build_episode_package.py",
        "episode_key": episode.key,
        "source_split": episode.split,
        "episode_index": episode_index,
        "task_index": episode.task_index,
        "task_text": episode.task_text,
        "block_id": row.get("block_id"),
        "block_range": row.get("block_range"),
        "length": length,
        "fps": reader.fps,
        "duration_seconds": round(length / float(reader.fps), 2),
        "selection": {
            key: row.get(key)
            for key in (
                "selection_strategy",
                "selection_note",
                "supports_l5_candidate",
                "l5_route_hint",
                "l5_evidence",
            )
        },
        "source_files": {
            "parquet": {"path": str(parquet_path), "sha256": sha256_file(parquet_path)},
            "ego_video": {"path": str(ego_path), "sha256": sha256_file(ego_path)},
            "wrist_video": (
                {"path": str(wrist_path), "sha256": sha256_file(wrist_path)}
                if wrist_path.exists()
                else {"path": str(wrist_path), "sha256": "missing"}
            ),
            "parquet_rows": int(len(state)),
            "decoded_ego_frames": int(scan["decoded_frames"]),
        },
        "gripper": gripper,
        "state_summary": {
            "shape": [int(state.shape[0]), int(state.shape[1])],
            "slices": slice_summary(state, STATE_SLICES),
            "gripper_joint_range": [round(float(joint0.min()), 5), round(float(joint0.max()), 5)],
        },
        "action_summary": {
            "shape": [int(action.shape[0]), int(action.shape[1])],
            "slices": slice_summary(action, ACTION_SLICES),
        },
        "motion": {
            "method": "mean absolute grey-level difference between consecutive ego frames",
            "mean": round(float(motion.mean()), 3),
            "p95": round(float(np.percentile(motion, 95)), 3),
            "max": round(float(motion.max()), 3),
            "top_bursts": top_bursts,
        },
        "candidate_frames": candidate_entries,
        "candidate_notes": candidate_notes,
        "candidate_meta": candidate_meta,
        "target_tracking": target_tracking,
        "sheets": sheets,
        "scene": scene,
        "l5": l5,
        "annotation_brief": annotation_brief,
        "warnings": warnings,
    }
    package_path = package_dir / "package.json"
    payload = json.dumps(package, indent=2, ensure_ascii=False) + "\n"
    package_path.write_text(payload, encoding="utf-8", newline="\n")
    package["package_path"] = str(package_path)
    package["package_sha256"] = sha256_file(package_path)
    return package


# -------------------------------------------------------------------------- main
def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dataset-root", default=str(resolve_dataset_root()))
    parser.add_argument("--selection", default=str(ROOT / "data" / "usim_enact" / "_expansion" / "selection.jsonl"))
    parser.add_argument("--out", default=str(ROOT / "data" / "usim_enact" / "_expansion" / "packages"))
    parser.add_argument("--only", default="", help="comma separated episode indices")
    parser.add_argument("--no-wrist", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    dataset_root = Path(args.dataset_root)
    rows = load_selection(Path(args.selection))
    only = {int(value) for value in args.only.split(",") if value.strip()}
    if only:
        rows = [row for row in rows if int(row["episode_index"]) in only]
    reader = USIMReader(dataset_root, split="train")
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    results = []
    for row in rows:
        episode_index = int(row["episode_index"])
        package_dir = out_root / f"usim_train_episode_{episode_index:06d}"
        package_path = package_dir / "package.json"
        if package_path.exists() and not args.overwrite:
            print(f"[skip] {package_path} exists (pass --overwrite to rebuild)")
            package = json.loads(package_path.read_text(encoding="utf-8"))
        else:
            package = build_package(reader, row, out_root, dataset_root, include_wrist=not args.no_wrist)
            route = package["l5"]["route"]
            print(
                f"[built] {package['episode_key']}: {len(package['candidate_frames'])} frames, "
                f"l5_route={route}, sheets={len(package['sheets'])}, warnings={len(package['warnings'])}"
            )
        results.append(
            {
                "episode_key": package["episode_key"],
                "episode_index": package["episode_index"],
                "task_text": package["task_text"],
                "block_id": package.get("block_id"),
                "length": package["length"],
                "l5_route": package["l5"]["route"],
                "l5_route_available": package["l5"]["route_candidates"][0]["available"],
                "supports_l5_candidate": package["selection"].get("supports_l5_candidate"),
                "candidate_frames": [item["frame_index"] for item in package["candidate_frames"]],
                "sheets": {key: value["path"] for key, value in package["sheets"].items()},
                "package_json": str(package_dir / "package.json"),
                "package_sha256": package.get("package_sha256"),
                "warnings": package["warnings"],
            }
        )

    # -------------------------------------------------------------- index file
    by_task: Dict[str, int] = {}
    by_block: Dict[str, int] = {}
    by_route: Dict[str, int] = {}
    for item in results:
        by_task[item["task_text"]] = by_task.get(item["task_text"], 0) + 1
        by_block[str(item["block_id"])] = by_block.get(str(item["block_id"]), 0) + 1
        by_route[item["l5_route"]] = by_route.get(item["l5_route"], 0) + 1
    missing_sheets = []
    for item in results:
        for relative in item["sheets"].values():
            path = Path(item["package_json"]).parent / relative
            if not path.exists() or path.stat().st_size == 0:
                missing_sheets.append(str(path))
    index = {
        "schema_version": 1,
        "builder": "scripts/usim/build_episode_package.py",
        "selection": str(Path(args.selection)),
        "packages": len(results),
        "counts_by_task": by_task,
        "counts_by_block": by_block,
        "counts_by_l5_route": by_route,
        "l5_route_candidates": sorted(by_route),
        "missing_sheets": missing_sheets,
        "warnings": [item["episode_key"] for item in results if item["warnings"]],
        "episodes": results,
        "note": "L=5 routes are evidence proposals from gripper signal + colour blobs; every state needs visual review",
    }
    index_path = out_root / "index.json"
    index_path.write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps({key: index[key] for key in ("packages", "counts_by_task", "counts_by_l5_route")},
                     indent=2, ensure_ascii=False))
    print(f"index: {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
