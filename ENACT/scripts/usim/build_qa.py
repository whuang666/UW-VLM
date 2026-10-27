"""Generate ENACT forward/inverse ordering QA from the compiled USIM dataset.

Reuses the upstream generators unchanged (DAG construction, DP path counting,
weighted sampling, permutation answers, visual prompts).  Only three things are
injected:

1. ``USIMSceneGraphReader``  -- annotation-aware visibility (docs/06 §3).
2. ``USIMStateChangeTranslator`` -- USIM object lifecycle vocabulary.
3. ``apply_local_font``      -- readable "Next State N" labels on Windows.

Output: ``<data-root>/QA/<split>/enact_ordering.jsonl`` (+ ``QA/images/...``).

Usage:
    python scripts/usim/build_qa.py --step-lengths 3,4 --num-to-sample 25
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enact.adapters.usim_annotations import PROTOCOL_VERSION, SENSOR_NAME  # noqa: E402
from enact.adapters.usim_scene_graph import USIMSceneGraphReader  # noqa: E402
from enact.adapters.usim_translator import USIMStateChangeTranslator  # noqa: E402
from enact.adapters.usim_visual_prompt import apply_local_font  # noqa: E402
from enact.core.forward_world_modeling import ForwardWorldModelingGenerator  # noqa: E402
from enact.core.inverse_world_modeling import InverseWorldModelingGenerator  # noqa: E402
from enact.utils.qa_gen_utils import TaskData  # noqa: E402

DEFAULT_DATA_ROOT = ROOT / "data" / "usim_enact" / PROTOCOL_VERSION


def load_task_data(data_root: Path) -> List[TaskData]:
    segmented_root = data_root / "segmented_activities"
    raw_root = data_root / "replayed_activities"
    tasks: List[TaskData] = []
    for task_dir in sorted(path for path in segmented_root.iterdir() if path.is_dir()):
        task_name = task_dir.name
        segmented_file = task_dir / "segmented_scene_graph_0.json"
        raw_dir = raw_root / task_name
        raw_file = raw_dir / "scene_graph_0.json"
        if not segmented_file.exists() or not raw_file.exists():
            print(f"[skip] {task_name}: missing scene graph")
            continue

        segmented_reader = USIMSceneGraphReader(str(segmented_file))
        key_frame_ids = segmented_reader.get_available_frame_ids()
        raw_reader = USIMSceneGraphReader(str(raw_file))

        image_paths: Dict[str, Dict[str, str]] = {}
        sensor_dir = raw_dir / SENSOR_NAME
        for frame_id in key_frame_ids:
            image_file = sensor_dir / f"{int(frame_id):05d}.png"
            if image_file.exists():
                image_paths[frame_id] = {SENSOR_NAME: str(image_file)}

        missing = [fid for fid in key_frame_ids if fid not in image_paths]
        if missing:
            print(f"[skip] {task_name}: missing images for frames {missing}")
            continue

        tasks.append(
            TaskData(
                task_name=task_name,
                scene_graph_reader=raw_reader,
                key_frame_ids=key_frame_ids,
                image_paths=image_paths,
                task_dir=str(task_dir),
                # upstream calls task_data.image_root_path.parent, so this must stay a Path
                image_root_path=raw_root,
            )
        )
    return tasks


def build_generator(direction: str, step_length: int):
    if direction == "forward":
        generator = ForwardWorldModelingGenerator(step_length=step_length)
        generator.translator = USIMStateChangeTranslator(type="multi_forward_world_modeling")
    elif direction == "inverse":
        generator = InverseWorldModelingGenerator(step_length=step_length)
        generator.translator = USIMStateChangeTranslator(type="multi_inverse_world_modeling")
    else:
        raise ValueError(f"unknown direction: {direction}")
    apply_local_font(generator)
    return generator


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--out", default="", help="defaults to <data-root>/QA/train/enact_ordering.jsonl")
    parser.add_argument("--step-lengths", default="3,4")
    parser.add_argument("--direction", default="both", choices=["forward", "inverse", "both"])
    parser.add_argument("--num-to-sample", type=int, default=25)
    args = parser.parse_args(argv)

    data_root = Path(args.data_root)
    out_path = Path(args.out) if args.out else data_root / "QA" / "train" / "enact_ordering.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    tasks = load_task_data(data_root)
    if not tasks:
        print("no tasks found", file=sys.stderr)
        return 2
    print(f"loaded {len(tasks)} episodes from {data_root}")

    directions = ["forward", "inverse"] if args.direction == "both" else [args.direction]
    step_lengths = [int(value) for value in args.step_lengths.split(",") if value.strip()]

    stats: List[Dict[str, object]] = []
    records = 0
    with out_path.open("w", encoding="utf-8") as handle:
        for direction in directions:
            for step_length in step_lengths:
                generator = build_generator(direction, step_length)
                produced = 0
                per_task: Dict[str, int] = {}
                for task_data in tasks:
                    try:
                        pairs = generator.generate(task_data, num_to_sample=args.num_to_sample)
                    except Exception as error:  # keep going, record the failure
                        print(f"[error] {direction} L={step_length} {task_data.task_name}: {error}")
                        per_task[task_data.task_name] = 0
                        continue
                    per_task[task_data.task_name] = len(pairs)
                    for pair in pairs:
                        handle.write(json.dumps(pair.to_dict(), ensure_ascii=False) + "\n")
                        produced += 1
                records += produced
                stats.append(
                    {
                        "direction": direction,
                        "step_length": step_length,
                        "qa_type": generator.qa_type,
                        "count": produced,
                        "per_episode": per_task,
                    }
                )
                print(f"[qa] {direction} L={step_length}: {produced} questions")

    manifest_path = data_root / "manifest.json"
    summary_protocol_version = PROTOCOL_VERSION
    if manifest_path.exists():
        try:
            summary_protocol_version = json.loads(manifest_path.read_text(encoding="utf-8")).get(
                "protocol_version", PROTOCOL_VERSION
            )
        except json.JSONDecodeError:
            pass

    summary = {
        "protocol_version": summary_protocol_version,
        "data_root": str(data_root),
        "output": str(out_path),
        "episodes": len(tasks),
        "episode_keys": [task.task_name for task in tasks],
        "num_to_sample": args.num_to_sample,
        "total": records,
        "by_setting": stats,
    }
    summary_path = out_path.parent / "build_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"total": records, "summary": str(summary_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
