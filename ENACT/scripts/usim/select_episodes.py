"""Select v0.2 expansion episodes from the USIM train split (deterministic).

Rules (see ``ENACT/docs/WBW/ENACT-USIM-扩展候选与工具-20261027.md``):

* source split is ``train`` only (the outer USIM test split is never a source);
* the seven v0.1 episodes are excluded;
* length must be inside ``[150, 700]`` frames (15-70 s at 10 fps);
* only manipulation tasks (pipe / blue cylinder / red cylinder / transfer) are used;
* episode "blocks" are contiguous runs of the same task text in
  ``episodes.jsonl``.  One run in the released metadata is 200 episodes long
  while the upstream sub-folder summary (``episode_frame_summary_lerobot_train.csv``)
  declares only 100 episodes per pick sub-folder, so that run is split at the
  100-episode boundary (inference recorded in the manifest);
* at most two episodes per block, except the transfer block which gets 4-6
  candidates because it is the main L=5 (InBox) route;
* a fixed seed and per-block RNG make the choice reproducible byte-for-byte.

The selection is *evidence gathering*, not annotation.  Gripper close/open
events are derived from ``observation.state[0]`` (>0.004 = closed) purely to
propose review material and to mark which episodes may support an L=5 route.

Usage (PowerShell):
    python scripts/usim/select_episodes.py
    python scripts/usim/select_episodes.py --seed 20261027 --out-dir data/usim_enact/_expansion
    python scripts/usim/select_episodes.py --dataset-root E:\\code\\UW-VLM\\usim
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enact.adapters.usim_reader import USIMReader, resolve_dataset_root  # noqa: E402
from scripts.usim.annotate_helper import colour_blobs  # noqa: E402

SEED = 20261027
LENGTH_MIN = 150
LENGTH_MAX = 700
GRIPPER_CLOSED_THRESHOLD = 0.004
USED_EPISODES = (200, 201, 552, 553, 555, 556, 1302)
MANIPULATION_TASK_INDICES = {1, 2, 6, 7}
TRANSFER_TASK_INDEX = 7
# Quota per block: transfer block 4-6 (L=5 InBox route), every other block <= 2.
TRANSFER_QUOTA = 6
OTHER_QUOTA = 2
# A released object needs time to settle before "OnSeabed again" / "InBox" can
# be judged: 8 frames = 0.8 s at 10 fps is the minimum used to *flag* a
# candidate for review (NOT a label).
MIN_RELEASE_SETTLE_FRAMES = 8
SUBFOLDER_EPISODES = 100  # from episode_frame_summary_lerobot_train.csv
SCAN_LIMIT = 25  # max episodes inspected per block when looking for a release
MIN_TARGET_BLOB_AREA = {"red": 60, "blue": 80, "green": 500}
TARGET_COLOURS = {
    "Pick up the pipe": (),
    "Pick up the blue cylinder": ("blue",),
    "Pick up the red cylinder": ("red",),
    "Pick up the red cylinder and transfer it to the box": ("red", "green"),
}
TARGET_TASK_TRANSFER = "Pick up the red cylinder and transfer it to the box"


# --------------------------------------------------------------------------- io
def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> List[Dict]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


# ------------------------------------------------------------------------ model
def load_meta(root: Path) -> Tuple[List[Dict], Dict[str, int], Dict]:
    split_root = root / "train"
    info = json.loads((split_root / "meta" / "info.json").read_text(encoding="utf-8"))
    tasks = {
        record["task"]: int(record["task_index"])
        for record in read_jsonl(split_root / "meta" / "tasks.jsonl")
    }
    episodes = read_jsonl(split_root / "meta" / "episodes.jsonl")
    for record in episodes:
        task_text = (record.get("tasks") or [""])[0]
        record["task_text"] = task_text
        record["task_index"] = tasks.get(task_text)
    return episodes, tasks, info


def build_blocks(episodes: Sequence[Dict]) -> List[Dict]:
    """Group contiguous runs of the same task text and split >100-episode runs."""
    runs: List[Dict] = []
    current: Optional[Dict] = None
    for record in episodes:
        task_text = record["task_text"]
        if current is None or task_text != current["task_text"]:
            current = {
                "task_text": task_text,
                "task_index": record["task_index"],
                "start": int(record["episode_index"]),
                "episodes": [],
            }
            runs.append(current)
        current["episodes"].append(int(record["episode_index"]))

    blocks: List[Dict] = []
    for run in runs:
        indices = run["episodes"]
        chunks = [indices[i:i + SUBFOLDER_EPISODES] for i in range(0, len(indices), SUBFOLDER_EPISODES)]
        for chunk_index, chunk in enumerate(chunks):
            blocks.append(
                {
                    "task_text": run["task_text"],
                    "task_index": run["task_index"],
                    "start": min(chunk),
                    "end": max(chunk),
                    "episode_indices": list(chunk),
                    "split_from_meta_run": len(indices) > SUBFOLDER_EPISODES,
                    "meta_run_span": [min(indices), max(indices)],
                    "subfolder_index": chunk_index,
                    "split_note": (
                        "meta/esodes.jsonl run merges 2 upstream sub-folders with the same "
                        "task text; split at the 100-episode boundary based on "
                        "episode_frame_summary_lerobot_train.csv (100 episodes per pick sub-folder)"
                        if len(indices) > SUBFOLDER_EPISODES
                        else ""
                    ),
                }
            )
    for number, block in enumerate(blocks, start=1):
        block["block_id"] = f"train_b{number:02d}"
        block["frame_total"] = 0
    return blocks


def block_frame_totals(blocks: List[Dict], by_index: Dict[int, Dict]) -> None:
    for block in blocks:
        block["frame_total"] = sum(by_index[index]["length"] for index in block["episode_indices"])


# --------------------------------------------------------------------- gripper
def gripper_events(joint0: np.ndarray, threshold: float = GRIPPER_CLOSED_THRESHOLD) -> List[Dict]:
    closed = joint0 > threshold
    events: List[Dict] = []
    for index in range(1, len(closed)):
        if closed[index] and not closed[index - 1]:
            events.append({"event": "close", "frame": int(index)})
        elif not closed[index] and closed[index - 1]:
            events.append({"event": "open", "frame": int(index)})
    return events


def gripper_summary(joint0: np.ndarray, timestamps: np.ndarray) -> Dict:
    closed = joint0 > GRIPPER_CLOSED_THRESHOLD
    events = gripper_events(joint0)
    length = int(len(joint0))
    for event in events:
        event["timestamp"] = round(float(timestamps[event["frame"]]), 3)
    final_open = events[-1] if events and events[-1]["event"] == "open" else None
    last_close = next((event for event in reversed(events) if event["event"] == "close"), None)
    frames_after_final_open = (
        length - 1 - int(final_open["frame"]) if final_open is not None else None
    )
    return {
        "signal": "observation.state[0] (joint_pos[0]); > %.3f means closed" % GRIPPER_CLOSED_THRESHOLD,
        "threshold": GRIPPER_CLOSED_THRESHOLD,
        "range": [round(float(joint0.min()), 5), round(float(joint0.max()), 5)],
        "closed_frames": int(closed.sum()),
        "closed_fraction": round(float(closed.mean()), 4),
        "events": events,
        "event_count": len(events),
        "final_state": "closed" if closed[-1] else "open",
        "last_close_frame": int(last_close["frame"]) if last_close else None,
        "last_open_frame": int(final_open["frame"]) if final_open else None,
        "frames_after_final_open": frames_after_final_open,
    }


def episode_gripper(reader: USIMReader, episode_index: int) -> Tuple[np.ndarray, np.ndarray, Dict]:
    table = reader.load_table(episode_index)
    joint0 = np.array([np.asarray(v, dtype=np.float32) for v in table["observation.state"]])[:, 0]
    timestamps = np.asarray(table["timestamp"], dtype=np.float64)
    return joint0, timestamps, gripper_summary(joint0, timestamps)


# ------------------------------------------------------------------- visual qa
def end_frame_box_area(reader: USIMReader, episode_index: int) -> Optional[int]:
    """Green-blob area of the last decodable frame (box proxy, NOT a label)."""
    episode = reader.episode(episode_index)
    try:
        frame = reader.read_frame(episode_index, episode.length - 1)
    except Exception:  # pragma: no cover - defensive
        return None
    return int(colour_blobs(frame)["green"]["area"])


# -------------------------------------------------------------------- selection
def pick_candidates(
    reader: USIMReader,
    block: Dict,
    by_index: Dict[int, Dict],
    rng: random.Random,
    limit: int,
) -> Tuple[List[Dict], List[Dict]]:
    """Pick episodes from one block; returns (accepted, rejected_length/used notes)."""
    pool = [
        index
        for index in block["episode_indices"]
        if index not in USED_EPISODES and LENGTH_MIN <= int(by_index[index]["length"]) <= LENGTH_MAX
    ]
    excluded_length = sum(
        1
        for index in block["episode_indices"]
        if index not in USED_EPISODES and not (LENGTH_MIN <= int(by_index[index]["length"]) <= LENGTH_MAX)
    )
    excluded_used = sum(1 for index in block["episode_indices"] if index in USED_EPISODES)
    rng.shuffle(pool)

    accepted: List[Dict] = []
    scanned = 0
    cache: Dict[int, Dict] = {}

    def inspect(index: int) -> Dict:
        nonlocal scanned
        if index not in cache:
            _, _, summary = episode_gripper(reader, index)
            cache[index] = summary
            scanned += 1
        return cache[index]

    if block["task_index"] == TRANSFER_TASK_INDEX:
        # The transfer block is the clean InBox route: require a final release
        # with enough frames left for the object to settle, and record whether
        # the green box is visible at the end.  Falls back to release-only, then
        # to any episode (recorded in the block notes).
        tiers = (
            lambda row: row["final_state"] == "open"
            and int(row["frames_after_final_open"] or 0) >= MIN_RELEASE_SETTLE_FRAMES,
            lambda row: row["final_state"] == "open",
            lambda row: True,
        )
        seen: set = set()
        for tier, predicate in enumerate(tiers):
            for index in pool:
                if len(accepted) >= limit:
                    break
                if index in seen:
                    continue
                summary = inspect(index)
                if not predicate(summary):
                    continue
                seen.add(index)
                box_area = end_frame_box_area(reader, index) if tier == 0 else None
                accepted.append(
                    {
                        "episode_index": index,
                        "strategy": [
                            "transfer_inbox_precheck",
                            "transfer_release_only",
                            "transfer_fallback",
                        ][tier],
                        "gripper": summary,
                        "box_green_area_end": box_area,
                        "selection_note": (
                            "final open event with >= %d frames to settle; end-frame green blob area %s"
                            % (MIN_RELEASE_SETTLE_FRAMES, box_area)
                        ),
                    }
                )
            if len(accepted) >= limit:
                break
    else:
        # Slot A prefers a release-visible episode (L=5 route ii evidence) if one
        # exists within SCAN_LIMIT; the remaining slots are random draws from the
        # per-block shuffle.  Both stay within the block quota (default 2).
        release_slot: Optional[int] = None
        for index in pool[:SCAN_LIMIT]:
            summary = inspect(index)
            if (
                summary["final_state"] == "open"
                and int(summary["frames_after_final_open"] or 0) >= MIN_RELEASE_SETTLE_FRAMES
            ):
                release_slot = index
                break
        order: List[int] = ([release_slot] if release_slot is not None else []) + [
            index for index in pool if index != release_slot
        ]
        for index in order:
            if len(accepted) >= limit:
                break
            summary = inspect(index)
            is_release_slot = index == release_slot
            if is_release_slot:
                note = (
                    "slot A: release (final open) with %s frames to settle"
                    % summary["frames_after_final_open"]
                )
            elif summary["frames_after_final_open"] is not None:
                note = (
                    "random slot: final open with %s frames to settle"
                    % summary["frames_after_final_open"]
                )
            else:
                note = "random slot: object still held at video end (L=3/4 candidate)"
            accepted.append(
                {
                    "episode_index": index,
                    "strategy": "slot_a_release_preferred" if is_release_slot else "random",
                    "gripper": summary,
                    "box_green_area_end": None,
                    "selection_note": note,
                }
            )

    notes = []
    if excluded_used:
        notes.append(f"{excluded_used} v0.1-used episode(s) excluded")
    if excluded_length:
        notes.append(f"{excluded_length} episode(s) outside [{LENGTH_MIN},{LENGTH_MAX}] excluded")
    if len(accepted) < limit:
        notes.append(f"only {len(accepted)}/{limit} selected (pool short after filters)")
    return accepted, [{"block_id": block["block_id"], "scanned": scanned, "notes": notes}]


# ------------------------------------------------------------------------ flags
def l5_flags(task_text: str, gripper: Dict, box_area: Optional[int], length: int) -> Dict:
    """Mark L=5 candidate routes from signal-only evidence (no labels)."""
    final_open = gripper["final_state"] == "open"
    settle = gripper["frames_after_final_open"]
    has_settle = final_open and settle is not None and settle >= MIN_RELEASE_SETTLE_FRAMES
    last_close = gripper["last_close_frame"]
    # Route evidence is *proposal* evidence: every flag must be reviewed visually.
    if task_text == TARGET_TASK_TRANSFER and has_settle:
        supports = True
        hint = "transfer_inbox"
        reason = (
            f"final open at f{gripper['last_open_frame']} with {settle} frames (>=0.8 s) to settle; "
            f"end-frame green-box blob area={box_area} (heuristic box visibility)"
        )
    elif has_settle and last_close is not None:
        supports = True
        hint = "release_settle"
        reason = (
            f"open-after-close at f{gripper['last_open_frame']} with {settle} frames (>=0.8 s) to settle; "
            "object must be visible on the seabed in the settle frames (review required)"
        )
    else:
        supports = False
        hint = "touching"
        reason = (
            "object is still held at video end (no release); the only extra L=5 state would be "
            "Touching(robot, object) between NextTo and InGripper (review required)"
        )
    return {
        "supports_l5_candidate": supports,
        "l5_route_hint": hint,
        "l5_evidence": reason,
        "release_settle_frames": settle,
        "touching_route_candidate": (not supports) and last_close is not None,
    }


# -------------------------------------------------------------------------- main
def main(argv: Optional[Sequence[str]] = None) -> int:
    global LENGTH_MIN, LENGTH_MAX
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dataset-root", default=str(resolve_dataset_root()))
    parser.add_argument("--out-dir", default=str(ROOT / "data" / "usim_enact" / "_expansion"))
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--length-min", type=int, default=LENGTH_MIN)
    parser.add_argument("--length-max", type=int, default=LENGTH_MAX)
    parser.add_argument("--transfer-quota", type=int, default=TRANSFER_QUOTA)
    parser.add_argument("--block-quota", type=int, default=OTHER_QUOTA)
    parser.add_argument("--target", type=int, default=0, help="0 = auto (24-30), else exact target")
    args = parser.parse_args(argv)

    LENGTH_MIN, LENGTH_MAX = args.length_min, args.length_max

    dataset_root = Path(args.dataset_root)
    episodes, tasks, info = load_meta(dataset_root)
    by_index = {int(record["episode_index"]): record for record in episodes}

    test_episodes: List[Dict] = []
    test_meta = dataset_root / "test" / "meta" / "episodes.jsonl"
    if test_meta.exists():
        test_episodes = read_jsonl(test_meta)

    blocks = build_blocks(episodes)
    block_frame_totals(blocks, by_index)
    manipulation_blocks = [
        block for block in blocks if block["task_index"] in MANIPULATION_TASK_INDICES
    ]
    non_manipulation_blocks = [
        block for block in blocks if block["task_index"] not in MANIPULATION_TASK_INDICES
    ]

    selected: List[Dict] = []
    block_notes: List[Dict] = []
    reader = USIMReader(dataset_root, split="train")
    for block in manipulation_blocks:
        quota = args.transfer_quota if block["task_index"] == TRANSFER_TASK_INDEX else args.block_quota
        rng = random.Random(f"{args.seed}:{block['block_id']}")
        accepted, notes = pick_candidates(
            reader=reader, block=block, by_index=by_index, rng=rng, limit=quota
        )
        block_notes.extend(notes)
        for item in accepted:
            selected.append(
                {
                    "episode_key": f"usim_train_episode_{item['episode_index']:06d}",
                    "source_split": "train",
                    "episode_index": item["episode_index"],
                    "task_text": block["task_text"],
                    "task_index": block["task_index"],
                    "block_id": block["block_id"],
                    "block_range": [block["start"], block["end"]],
                    "length": int(by_index[item["episode_index"]]["length"]),
                    "selection_strategy": item["strategy"],
                    "selection_note": item["selection_note"],
                    "gripper": item["gripper"],
                    "box_green_area_end": item["box_green_area_end"],
                    **l5_flags(block["task_text"], item["gripper"], item["box_green_area_end"],
                               int(by_index[item["episode_index"]]["length"])),
                }
            )

    # Fill from neighbouring blocks only if the target is not reached (record it).
    target = args.target
    if target <= 0:
        target = args.transfer_quota + args.block_quota * (len(manipulation_blocks) - 1)
    fills: List[Dict] = []
    if len(selected) < max(24, target):
        taken = {item["episode_key"] for item in selected}
        for block in manipulation_blocks:
            if len(selected) >= target:
                break
            used_here = sum(1 for item in selected if item["block_id"] == block["block_id"])
            limit = args.transfer_quota if block["task_index"] == TRANSFER_TASK_INDEX else args.block_quota
            if used_here >= limit:
                continue
            rng = random.Random(f"{args.seed}:fill:{block['block_id']}")
            pool = [
                index
                for index in block["episode_indices"]
                if index not in USED_EPISODES
                and LENGTH_MIN <= int(by_index[index]["length"]) <= LENGTH_MAX
                and f"usim_train_episode_{index:06d}" not in taken
            ]
            rng.shuffle(pool)
            for index in pool:
                if len(selected) >= target:
                    break
                _, _, gripper = episode_gripper(USIMReader(dataset_root, split="train"), index)
                selected.append(
                    {
                        "episode_key": f"usim_train_episode_{index:06d}",
                        "source_split": "train",
                        "episode_index": index,
                        "task_text": block["task_text"],
                        "task_index": block["task_index"],
                        "block_id": block["block_id"],
                        "block_range": [block["start"], block["end"]],
                        "length": int(by_index[index]["length"]),
                        "selection_strategy": "neighbour_fill",
                        "selection_note": "filled from a block below quota to reach the 24-30 target",
                        "gripper": gripper,
                        "box_green_area_end": None,
                        **l5_flags(block["task_text"], gripper, None, int(by_index[index]["length"])),
                    }
                )
                fills.append(
                    {
                        "block_id": block["block_id"],
                        "episode_index": index,
                        "reason": "24-30 candidate target not reached by primary block quotas",
                    }
                )
                taken.add(f"usim_train_episode_{index:06d}")

    selected.sort(key=lambda item: (item["block_id"], item["episode_index"]))
    for item in selected:
        item.pop("gripper_events", None)

    # ------------------------------------------------------------- task x block
    distribution: Dict[str, Dict[str, int]] = {}
    for item in selected:
        distribution.setdefault(item["task_text"], {})
        distribution[item["task_text"]][item["block_id"]] = (
            distribution[item["task_text"]].get(item["block_id"], 0) + 1
        )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    selection_path = out_dir / "selection.jsonl"
    payload = "".join(
        json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in selected
    )
    selection_path.write_text(payload, encoding="utf-8", newline="\n")

    inputs = {}
    for relative in (
        "train/meta/info.json",
        "train/meta/episodes.jsonl",
        "train/meta/tasks.jsonl",
        "train/episode_frame_summary_lerobot_train.csv",
    ):
        path = dataset_root / relative
        if path.exists():
            inputs[relative] = sha256_file(path)

    v01_dir = ROOT / "data" / "usim_enact" / "usim-enact-v0.1" / "annotations" / "episodes"
    v01_used = []
    if v01_dir.exists():
        v01_used = sorted(int(path.stem.split("_")[-1]) for path in v01_dir.glob("*.json"))

    manifest = {
        "schema_version": 1,
        "script": "scripts/usim/select_episodes.py",
        "dataset": {
            "root": str(dataset_root),
            "source_split": "train",
            "repo": "Vincent2025hello/usim",
            "commit": "88c3612bf99d10652f19ec531052a38c04f0202e",
            "fps": float(info.get("fps", 10.0)),
            "train_episodes": len(episodes),
            "test_episodes_checked_but_never_used": len(test_episodes),
        },
        "rules": {
            "seed": int(args.seed),
            "rng": "random.Random(f'{seed}:{block_id}') per block; slot_b is the next shuffled draw",
            "length_filter": [LENGTH_MIN, LENGTH_MAX],
            "manipulation_task_indices": sorted(MANIPULATION_TASK_INDICES),
            "manipulation_task_texts": {
                str(index): text for text, index in tasks.items() if index in MANIPULATION_TASK_INDICES
            },
            "quota_per_block": {"transfer_block": args.transfer_quota, "other_blocks": args.block_quota},
            "used_episodes_excluded": list(USED_EPISODES),
            "used_episodes_from_v01_annotations": v01_used,
            "gripper_threshold": GRIPPER_CLOSED_THRESHOLD,
            "min_release_settle_frames": MIN_RELEASE_SETTLE_FRAMES,
            "l5_route_priority": ["transfer_inbox", "release_settle", "touching"],
            "block_definition": (
                "contiguous run of identical tasks[0] in train/meta/episodes.jsonl; a run longer "
                "than the upstream sub-folder size (100) is split at the 100-episode boundary"
            ),
            "block_split_inference": (
                "one 200-episode 'Pick up the red cylinder' run exists, while "
                "episode_frame_summary_lerobot_train.csv declares four 100-episode red sub-folders; "
                "the split at the 100-episode boundary is therefore inferred, not declared in meta"
            ),
        },
        "exclusions": {
            "used_episodes": [
                {"episode_index": index, "reason": "annotated in usim-enact-v0.1"}
                for index in sorted(USED_EPISODES)
            ],
            "test_split": {
                "episodes": len(test_episodes),
                "reason": "outer USIM test split is reserved for frozen testing; never a selection source",
            },
            "non_manipulation_blocks": [
                {
                    "block_id": block["block_id"],
                    "task_text": block["task_text"],
                    "episodes": len(block["episode_indices"]),
                    "reason": "not a manipulation task (no gripper lifecycle / no L=3+ state changes planned)",
                }
                for block in non_manipulation_blocks
            ],
            "length_outside_range": {
                "min_length": int(min(record["length"] for record in episodes)),
                "max_length": int(max(record["length"] for record in episodes)),
                "candidates_inside_range": sum(
                    1
                    for record in episodes
                    if LENGTH_MIN <= int(record["length"]) <= LENGTH_MAX
                    and int(record["episode_index"]) not in USED_EPISODES
                ),
            },
        },
        "blocks": [
            {
                "block_id": block["block_id"],
                "task_text": block["task_text"],
                "task_index": block["task_index"],
                "episode_range": [block["start"], block["end"]],
                "episodes": len(block["episode_indices"]),
                "frame_total": block["frame_total"],
                "manipulation": block["task_index"] in MANIPULATION_TASK_INDICES,
                "split_from_meta_run": block["split_from_meta_run"],
                "split_note": block["split_note"],
            }
            for block in blocks
        ],
        "counts": {
            "blocks_total": len(blocks),
            "blocks_manipulation": len(manipulation_blocks),
            "candidates": len(selected),
            "candidates_transfer": sum(
                1 for item in selected if item["task_index"] == TRANSFER_TASK_INDEX
            ),
            "supports_l5_candidate": sum(
                1 for item in selected if item["supports_l5_candidate"]
            ),
            "l5_route_hint_distribution": {
                route: sum(1 for item in selected if item["l5_route_hint"] == route)
                for route in ("transfer_inbox", "release_settle", "touching")
            },
        },
        "task_block_distribution": distribution,
        "selection": [
            {
                "episode_key": item["episode_key"],
                "episode_index": item["episode_index"],
                "task_text": item["task_text"],
                "block_id": item["block_id"],
                "length": item["length"],
                "selection_strategy": item["selection_strategy"],
                "supports_l5_candidate": item["supports_l5_candidate"],
                "l5_route_hint": item["l5_route_hint"],
                "l5_evidence": item["l5_evidence"],
                "release_settle_frames": item["release_settle_frames"],
                "box_green_area_end": item["box_green_area_end"],
                "final_gripper_state": item["gripper"]["final_state"],
                "gripper_events": item["gripper"]["events"],
            }
            for item in selected
        ],
        "fill_events": fills,
        "block_selection_notes": block_notes,
        "inputs_sha256": inputs,
        "selection_jsonl": str(selection_path),
        "selection_sha256": sha256_file(selection_path),
        "python": sys.version.split()[0],
    }
    manifest_path = out_dir / "selection_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )

    print(json.dumps(manifest["counts"], indent=2, ensure_ascii=False))
    print("task x block:")
    for task, blocks_for_task in distribution.items():
        print(f"  {task}: " + ", ".join(f"{k}={v}" for k, v in sorted(blocks_for_task.items())))
    print(f"selection: {selection_path}")
    print(f"manifest : {manifest_path}")
    print(f"sha256   : {manifest['selection_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
