"""Read-only inventory and integrity audit for a local USIM/LeRobot dataset.

Writes only the explicitly requested JSON report. Does not download, repair,
convert, or edit source data. Run after any concurrent download has finished.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(root):
    return {
        str(path.relative_to(root)).replace("\\", "/"): {
            "bytes": path.stat().st_size,
            "mtime_ns": path.stat().st_mtime_ns,
        }
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".cache" not in path.parts and ".git" not in path.parts
    }


def audit_split(root, split, pq, np):
    folder = root / split
    report = {"present": folder.exists(), "metadata": {}, "episodes": []}
    for name in ["info.json", "modality.json", "tasks.jsonl", "episodes.jsonl", "episodes_stats.jsonl"]:
        path = folder / "meta" / name
        entry = {"present": path.is_file()}
        if path.is_file():
            entry["sha256"] = sha256(path)
            try:
                value = path.read_text(encoding="utf-8")
                entry["content"] = json.loads(value) if name.endswith(".json") else [
                    json.loads(line) for line in value.splitlines() if line.strip()
                ]
            except Exception as exc:
                entry["error"] = str(exc)
        report["metadata"][name] = entry
    schemas = Counter()
    task_rows, task_episodes = Counter(), Counter()
    files = sorted((folder / "data").rglob("*.parquet")) if folder.exists() else []
    for path in files:
        item = {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size}
        try:
            item["sha256"] = sha256(path)
            source = pq.ParquetFile(path)
            item["rows"] = source.metadata.num_rows
            item["writer"] = source.metadata.created_by
            schema = str(source.schema_arrow.remove_metadata())
            schemas[schema] += 1
            table = source.read()
            item["readable"] = True
            values = {name: table[name].to_pylist() for name in table.column_names}
            checks = {}
            for name, width in [("observation.state", 29), ("action", 13), ("target_pos", 6)]:
                array = np.asarray(values[name], dtype=float)
                checks[name + "_shape"] = list(array.shape) == [table.num_rows, width]
                checks[name + "_finite"] = bool(np.isfinite(array).all())
                if name == "target_pos":
                    item["target_pos_all_zero_rows"] = int(np.all(array == 0, axis=1).sum())
            frames = np.asarray(values["frame_index"])
            times = np.asarray(values["timestamp"], dtype=float)
            checks["frame_indices_zero_based_contiguous"] = bool(np.array_equal(frames, np.arange(len(frames))))
            checks["timestamp_finite"] = bool(np.isfinite(times).all())
            checks["timestamp_strictly_increasing"] = bool(np.all(np.diff(times) > 0))
            if len(times) > 1:
                item["median_frame_interval_seconds"] = float(np.median(np.diff(times)))
            episode_ids = sorted(set(values["episode_index"]))
            task_ids = sorted(set(values["task_index"]))
            item["episode_ids"], item["task_ids"] = episode_ids, task_ids
            checks["single_episode_index"] = len(episode_ids) == 1
            checks["single_task_index"] = len(task_ids) == 1
            checks["episode_index_matches_filename"] = episode_ids == [int(path.stem.split("_")[-1])]
            item["checks"] = checks
            for task in task_ids:
                task_rows[str(task)] += values["task_index"].count(task)
                task_episodes[str(task)] += 1
        except Exception as exc:
            item["readable"] = False
            item["error"] = type(exc).__name__ + ": " + str(exc)
        report["episodes"].append(item)
    videos = sorted((folder / "videos").rglob("*.mp4")) if folder.exists() else []
    report.update({
        "parquet_count": len(files),
        "footer_row_count": sum(item.get("rows", 0) for item in report["episodes"]),
        "readable_count": sum(item["readable"] for item in report["episodes"]),
        "episodes_with_failed_checks": sum(not all(item.get("checks", {"read": False}).values()) for item in report["episodes"]),
        "schemas": [{"schema": schema, "file_count": count} for schema, count in schemas.items()],
        "episodes_by_task_index": dict(sorted(task_episodes.items())),
        "rows_by_task_index": dict(sorted(task_rows.items())),
        "target_pos_all_zero_rows": sum(item.get("target_pos_all_zero_rows", 0) for item in report["episodes"]),
        "video_count": len(videos),
        "videos_by_camera": dict(Counter(path.parent.name for path in videos)),
        "video_contents_verified": False,
    })
    info = report["metadata"]["info.json"].get("content", {})
    if isinstance(info, dict) and info:
        report["matches_info_episode_count"] = len(files) == info.get("total_episodes")
        report["matches_info_frame_count"] = report["footer_row_count"] == info.get("total_frames")
        report["matches_info_video_count"] = len(videos) == info.get("total_videos")
    report["declared_asset_counts_complete"] = bool(
        report["present"]
        and all(item["present"] for item in report["metadata"].values())
        and all(report.get(key, False) for key in [
            "matches_info_episode_count", "matches_info_frame_count", "matches_info_video_count"
        ])
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pyarrow-site", type=Path, help="Optional isolated pyarrow installation directory")
    args = parser.parse_args()
    if args.pyarrow_site:
        sys.path.insert(0, str(args.pyarrow_site.resolve()))
    import numpy as np
    import pyarrow
    import pyarrow.parquet as pq

    root = args.dataset_root.resolve()
    if not root.is_dir():
        parser.error("dataset root does not exist")
    output = args.output.resolve()
    if output == root or root in output.parents:
        parser.error("write the audit report outside the source dataset")
    started = datetime.now(timezone.utc).isoformat()
    before = inventory(root)
    splits = {name: audit_split(root, name, pq, np) for name in ["train", "test"]}
    after = inventory(root)
    changed = sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))
    report = {
        "started_at_utc": started,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_root": str(root),
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "numpy_version": np.__version__,
        "pyarrow_version": pyarrow.__version__,
        "pyarrow_location": pyarrow.__file__,
        "source_unchanged_during_scan": not changed,
        "changed_paths_during_scan": changed,
        "declared_asset_counts_complete": all(s["declared_asset_counts_complete"] for s in splits.values()),
        "file_inventory": before,
        "splits": splits,
        "scope": "File inventory, metadata, parquet full reads and numeric integrity; no semantic labels or video decoding validation.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output), "source_unchanged_during_scan": not changed,
        "declared_asset_counts_complete": report["declared_asset_counts_complete"],
        "splits": {name: {key: entry[key] for key in ["present", "parquet_count", "footer_row_count", "readable_count", "episodes_with_failed_checks", "video_count", "target_pos_all_zero_rows"]} for name, entry in splits.items()},
    }, ensure_ascii=False, indent=2))
    return 0 if not changed and report["declared_asset_counts_complete"] and all(
        s["readable_count"] == s["parquet_count"] and not s["episodes_with_failed_checks"]
        for s in splits.values()
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
