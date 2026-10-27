"""Compile USIM annotations into an ENACT-compatible directory tree.

Output layout (see docs/04 §5 and docs/06):

    data/usim_enact/v0.1/
      manifest.json
      annotations/episodes/<episode_key>.json
      replayed_activities/<episode_key>/scene_graph_0.json
      replayed_activities/<episode_key>/external_sensor1/00000.png ...
      segmented_activities/<episode_key>/segmented_scene_graph_0.json
      segmented_activities/<episode_key>/external_sensor1/<frame>.png

Frame ids are the original USIM ``frame_index`` (0-based).  Images are named
``%05d.png`` so that frame 0 is ``00000.png`` -- the upstream helper would start at
``00001.png`` and silently shift everything by one frame (docs/03 §7).

Usage (PowerShell):
    python scripts/usim/build_dataset.py --check
    python scripts/usim/build_dataset.py --out data/usim_enact/v0.1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enact.adapters.usim_annotations import (  # noqa: E402
    PROTOCOL_VERSION,
    SENSOR_NAME,
    USIMEpisodeAnnotation,
    compile_action_descriptions,
    compile_scene_graph,
    load_annotations,
)
from enact.adapters.usim_reader import USIMReader, resolve_dataset_root  # noqa: E402

DEFAULT_ANNOTATIONS = ROOT / "data" / "usim_enact" / PROTOCOL_VERSION / "annotations" / "episodes"


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def git_commit(path: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def dump_frames(reader: USIMReader, episode_index: int, frame_ids: List[int], target_dir: Path) -> Dict[int, Dict]:
    target_dir.mkdir(parents=True, exist_ok=True)
    written: Dict[int, Dict] = {}
    for frame_index in frame_ids:
        frame = reader.read_frame(episode_index, frame_index, camera="ego")
        path = target_dir / f"{int(frame_index):05d}.png"
        if not cv2.imwrite(str(path), frame):
            raise RuntimeError(f"failed to write {path}")
        written[int(frame_index)] = {
            "path": str(path.relative_to(target_dir.parents[2])),
            "height": int(frame.shape[0]),
            "width": int(frame.shape[1]),
            "sha256": sha256_file(path),
        }
    return written


def compile_episode(
    annotation: USIMEpisodeAnnotation,
    reader: USIMReader,
    out_root: Path,
    overwrite: bool = False,
) -> Dict[str, object]:
    key = annotation.episode_key
    replayed = out_root / "replayed_activities" / key
    segmented = out_root / "segmented_activities" / key
    if replayed.exists() and not overwrite:
        raise FileExistsError(f"{replayed} already exists; pass --overwrite to rebuild")

    for path in (replayed, segmented):
        if path.exists():
            shutil.rmtree(path)

    frame_ids = [frame.frame_index for frame in annotation.frames]

    # Raw (dense-capable) activity: full graph at every annotated key frame.
    scene_graph = compile_scene_graph(annotation)
    replayed.mkdir(parents=True, exist_ok=True)
    (replayed / "scene_graph_0.json").write_text(
        json.dumps(scene_graph, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    raw_images = dump_frames(reader, annotation.episode_index, frame_ids, replayed / SENSOR_NAME)

    # Segmented activity: key frames only (manual key-frame route, docs/04 §5).
    segmented.mkdir(parents=True, exist_ok=True)
    (segmented / "segmented_scene_graph_0.json").write_text(
        json.dumps(scene_graph, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    key_images = dump_frames(reader, annotation.episode_index, frame_ids, segmented / SENSOR_NAME)

    transitions = compile_action_descriptions(annotation)
    return {
        "episode_key": key,
        "source_split": annotation.source_split,
        "episode_index": annotation.episode_index,
        "task_text": annotation.task_text,
        "task_index": annotation.task_index,
        "key_frame_ids": [str(fid) for fid in frame_ids],
        "frames": raw_images,
        "segmented_frames": key_images,
        "transitions": transitions,
        "valid_transitions": sum(1 for item in transitions if item["visible"]),
        "scene_graph_sha256": sha256_file(replayed / "scene_graph_0.json"),
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset-root", default=str(resolve_dataset_root()))
    parser.add_argument("--annotations", default=str(DEFAULT_ANNOTATIONS))
    parser.add_argument("--out", default=str(ROOT / "data" / "usim_enact" / PROTOCOL_VERSION))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--check", action="store_true", help="only verify Parquet/video alignment, do not compile")
    parser.add_argument("--check-episodes", default="", help="comma separated episode indices for --check")
    args = parser.parse_args(argv)

    dataset_root = Path(args.dataset_root)
    if args.check:
        episodes = [int(v) for v in args.check_episodes.split(",") if v.strip()]
        if not episodes:
            print("--check needs --check-episodes", file=sys.stderr)
            return 2
        split = "train"
        reader = USIMReader(dataset_root, split=split)
        reports = [reader.align_check(ep) for ep in episodes]
        print(json.dumps(reports, indent=2, ensure_ascii=False))
        return 0 if all(r["ok"] for r in reports) else 1

    annotations = load_annotations(args.annotations)
    if not annotations:
        print(f"no annotations found in {args.annotations}", file=sys.stderr)
        return 2

    readers: Dict[str, USIMReader] = {}
    out_root = Path(args.out)
    entries = []
    for annotation in annotations:
        if annotation.source_split not in readers:
            readers[annotation.source_split] = USIMReader(dataset_root, split=annotation.source_split)
        reader = readers[annotation.source_split]
        entry = compile_episode(annotation, reader, out_root, overwrite=args.overwrite)
        entries.append(entry)
        print(
            f"[compiled] {entry['episode_key']}: {len(entry['key_frame_ids'])} frames, "
            f"{entry['valid_transitions']}/{len(entry['transitions'])} visible transitions"
        )

    usim_manifest = dataset_root / "_download_manifest.json"
    manifest = {
        "protocol_version": PROTOCOL_VERSION,
        "camera_mapping": {"ego": SENSOR_NAME},
        "visibility": {
            "method": "annotated_boolean",
            "note": (
                "Primary signal is visual review of the ego stream. Detector pixel counts are "
                "stored as auxiliary evidence only, never used to pass the upstream 0.005% rule."
            ),
        },
        "usim": {
            "root": str(dataset_root),
            "download_manifest_sha256": sha256_file(usim_manifest) if usim_manifest.exists() else "missing",
        },
        "enact_commit": git_commit(ROOT),
        "annotations_dir": str(Path(args.annotations)),
        "annotation_sha256": {
            path.name: sha256_file(path) for path in sorted(Path(args.annotations).glob("*.json"))
        },
        "episodes": entries,
        "counts": {
            "episodes": len(entries),
            "key_frames": sum(len(entry["key_frame_ids"]) for entry in entries),
            "transitions": sum(len(entry["transitions"]) for entry in entries),
            "visible_transitions": sum(entry["valid_transitions"] for entry in entries),
        },
    }
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
