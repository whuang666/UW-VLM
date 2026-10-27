"""Split a curated v0.2 QA file into development / validation (and test) inputs.

Split membership is defined **by trajectory** in
``data/usim_enact/_expansion/annotation_assignment.json``:

* ``dev`` = v0.1's 7 episodes + assignment ``dev_new``;
* ``val`` = assignment ``val_new``;
* ``test`` = assignment ``test_reserve`` (only present once the frozen test set is
  built after protocol freeze; absent in the development run).

Each output file keeps the original QA records byte-for-byte (one JSON object per
line).  The manifest records the split seed, membership, per-setting counts and
the SHA-256 of every output so a run can be re-verified.

Usage:
    python scripts/usim/make_splits_v02.py \
        --qa data/usim_enact/usim-enact-v0.2/QA/train/enact_ordering_curated.jsonl \
        --out-dir data/usim_enact/runs/qwen3.8-max/v0.2_dev_001/inputs
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_ASSIGNMENT = ROOT / "data" / "usim_enact" / "_expansion" / "annotation_assignment.json"
V01_DEV_EPISODES = [
    "usim_train_episode_000200",
    "usim_train_episode_000201",
    "usim_train_episode_000552",
    "usim_train_episode_000553",
    "usim_train_episode_000555",
    "usim_train_episode_000556",
    "usim_train_episode_001302",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_assignment(path: Path) -> Dict[str, List[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    splits: Dict[str, List[str]] = {
        "dev": list(payload.get("dev_new", [])) + V01_DEV_EPISODES,
        "val": list(payload.get("val_new", [])),
        "test": list(payload.get("test_reserve", [])),
    }
    return splits


def counts_by_type(records: Sequence[Dict]) -> Dict[str, int]:
    counts: Dict[str, int] = defaultdict(int)
    for record in records:
        counts[record["type"]] += 1
    return dict(sorted(counts.items()))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--qa", required=True)
    parser.add_argument("--assignment", default=str(DEFAULT_ASSIGNMENT))
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--seed", type=int, default=20261027)
    args = parser.parse_args(argv)

    qa_path = Path(args.qa)
    records = [json.loads(line) for line in qa_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [record["id"] for record in records]
    if len(set(ids)) != len(ids):
        print("QA has duplicate ids", file=sys.stderr)
        return 2

    episode_to_split: Dict[str, str] = {}
    for split, episodes in load_assignment(Path(args.assignment)).items():
        for episode in episodes:
            if episode in episode_to_split:
                print(f"episode {episode} assigned to two splits", file=sys.stderr)
                return 2
            episode_to_split[episode] = split

    unknown = sorted({record["task_name"] for record in records} - set(episode_to_split))
    if unknown:
        print(f"QA episodes missing from assignment: {unknown}", file=sys.stderr)
        return 2

    by_split: Dict[str, List[Dict]] = defaultdict(list)
    for record in records:
        by_split[episode_to_split[record["task_name"]]].append(record)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: Dict[str, object] = {
        "split_version": "usim-enact-v0.2-splits-v1",
        "seed": args.seed,
        "assignment": str(Path(args.assignment)),
        "assignment_sha256": sha256_file(Path(args.assignment)),
        "qa": str(qa_path),
        "qa_sha256": sha256_file(qa_path),
        "splits": {},
        "empty_splits": [],
    }
    for split in ("dev", "val", "test"):
        split_records = sorted(by_split.get(split, []), key=lambda record: record["id"])
        if not split_records:
            manifest["empty_splits"].append(split)
            continue
        path = out_dir / f"{split}.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for record in split_records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        episodes = sorted({record["task_name"] for record in split_records})
        manifest["splits"][split] = {
            "path": str(path),
            "sha256": sha256_file(path),
            "questions": len(split_records),
            "episodes": episodes,
            "episode_count": len(episodes),
            "by_type": counts_by_type(split_records),
            "num_images": sum(len(record["images"]) for record in split_records),
        }

    dev_val_path = out_dir / "dev_val.jsonl"
    combined = sorted(by_split.get("dev", []) + by_split.get("val", []), key=lambda record: record["id"])
    with dev_val_path.open("w", encoding="utf-8") as handle:
        for record in combined:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    manifest["dev_val"] = {
        "path": str(dev_val_path),
        "sha256": sha256_file(dev_val_path),
        "questions": len(combined),
    }

    manifest_path = out_dir / "splits_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for split, info in manifest["splits"].items():
        print(f"{split}: {info['questions']} questions / {info['episode_count']} episodes")
    print(f"manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
