"""Re-draw the presented label order of a generated QA file with a controlled seed.

Upstream ENACT calls ``random.seed(42)`` inside every generator's ``generate()``, so
the shuffle of future images / action labels is *identical* for every episode.  On
the USIM pilot this produced 60% identity answers where chance alone predicts 43%
(chance for 2 actions is 1/2, for 3 actions 1/6) -- i.e. a constant ``[1, 2]``
answer would beat a real model.  ``docs/04`` §6 requires checking exactly this.

This script re-permutes the presented labels with ``--seed`` while keeping the
semantics untouched:

* forward  -- future images are re-rendered with new "Next State N" labels;
* inverse  -- only the numbered action block is rebuilt (images stay chronological).

The reference answer is recomputed from the new permutation, so every record stays
self-consistent (verified by running ``evaluate.py --synthetic oracle`` afterwards).

Usage:
    python scripts/usim/reseed_answers.py --seed 20261023
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import cv2

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enact.adapters.usim_annotations import PROTOCOL_VERSION, SENSOR_NAME  # noqa: E402
from enact.adapters.usim_visual_prompt import render_label  # noqa: E402

DEFAULT_DATA_ROOT = ROOT / "data" / "usim_enact" / PROTOCOL_VERSION
ACTION_LINE = re.compile(r"^\[Action (\d+)\] (.*)$", re.MULTILINE)


def chronological_from_labels(gt: Sequence[int]) -> List[int]:
    """``gt[j]`` is the label position of chronological item ``j``; invert it."""
    order = [0] * len(gt)
    for chrono_index, label in enumerate(gt):
        order[label - 1] = chrono_index
    return order


def new_permutation(length: int, rng: random.Random) -> List[int]:
    order = list(range(length))
    rng.shuffle(order)
    return order


def labels_from_order(order: Sequence[int]) -> List[int]:
    gt = [0] * len(order)
    for slot, chrono_index in enumerate(order):
        gt[chrono_index] = slot + 1
    return gt


def reseed_forward(record: Dict, data_root: Path, rng: random.Random) -> Dict:
    """Re-draw which future image sits in which labelled slot.

    ``new_order[slot]`` is the chronological future-state index shown in that slot,
    so the reference answer is ``labels_from_order(new_order)``.
    """
    gt = record["gt_answer"]
    length = len(gt)
    chrono_frames = record["key_frame_ids"][1:]     # chronological future frames
    if len(chrono_frames) != length:
        raise ValueError(f"{record['id']}: {len(chrono_frames)} future frames for {length} labels")

    new_order = new_permutation(length, rng)

    task_name = record["task_name"]
    image_dir = data_root / "QA" / "images" / record["type"] / task_name
    image_dir.mkdir(parents=True, exist_ok=True)
    stem = record["id"]
    sensor_dir = data_root / "replayed_activities" / task_name / SENSOR_NAME

    # "Current State" is re-rendered from the raw frame so the label is drawn once.
    current_frame = record["key_frame_ids"][0]
    current_source = sensor_dir / f"{int(current_frame):05d}.png"
    current_target = image_dir / f"{stem}_cur_state.png"
    render_label(str(current_source), "Current State", str(current_target))

    new_images: List[str] = [str(current_target.relative_to(data_root))]
    for slot, chrono_index in enumerate(new_order, start=1):
        source = sensor_dir / f"{int(chrono_frames[chrono_index]):05d}.png"
        target = image_dir / f"{stem}_next_state_{slot}.png"
        render_label(str(source), f"Next State {slot}", str(target))
        new_images.append(str(target.relative_to(data_root)))

    record["images"] = new_images
    record["gt_answer"] = labels_from_order(new_order)
    return record


def reseed_inverse(record: Dict, rng: random.Random) -> Dict:
    """Re-draw the numbering of the shuffled action block (images stay chronological)."""
    gt = record["gt_answer"]
    length = len(gt)
    order = chronological_from_labels(gt)   # slot -> chronological index
    question = record["question"]

    block = question.split("## Shuffled Actions")[1]
    lines = ACTION_LINE.findall(block)
    if len(lines) != length:
        raise ValueError(f"{record['id']}: expected {length} action lines, found {len(lines)}")
    by_slot = {int(index): text for index, text in lines}
    chronological_actions: List[str] = [""] * length
    for slot, chrono_index in enumerate(order):
        chronological_actions[chrono_index] = by_slot[slot + 1]

    new_order = new_permutation(length, rng)
    new_block = "\n".join(
        f"[Action {slot}] {chronological_actions[chrono_index]}"
        for slot, chrono_index in enumerate(new_order, start=1)
    )
    head, _, tail = question.partition("## Shuffled Actions")
    after = tail.split("\n\nNow please provide", 1)[1] if "\n\nNow please provide" in tail else ""
    record["question"] = f"{head}## Shuffled Actions\n{new_block}\n\nNow please provide{after}"
    record["gt_answer"] = labels_from_order(new_order)
    return record


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--qa", default="")
    parser.add_argument("--seed", type=int, default=20261023)
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)

    data_root = Path(args.data_root)
    qa_path = Path(args.qa) if args.qa else data_root / "QA" / "train" / "enact_ordering.jsonl"
    out_path = Path(args.out) if args.out else qa_path
    records = [json.loads(line) for line in qa_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    rng = random.Random(args.seed)
    reseeded = 0
    for record in records:
        if "forward" in record["type"]:
            reseed_forward(record, data_root, rng)
        else:
            reseed_inverse(record, rng)
        reseeded += 1

    with out_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps({"reseeded": reseeded, "seed": args.seed, "output": str(out_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
