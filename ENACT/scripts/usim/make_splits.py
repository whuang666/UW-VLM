"""Build preflight / smoke / full_dev question lists from a frozen QA file.

docs/WBR §9 requires a *stratified* 20-question smoke run across
``direction x L`` groups, with a fixed seed, prepared as its own JSONL file --
``--limit 20`` on the frozen file is wrong because the file starts with all
forward L=3 questions.

Usage:
    python scripts/usim/make_splits.py --data-root data/usim_enact/usim-enact-v0.1 \
        --out-dir data/usim_enact/runs/qwen3.8-max/dev_ego_thinking_false_001/inputs
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enact.adapters.usim_annotations import PROTOCOL_VERSION  # noqa: E402

DEFAULT_DATA_ROOT = ROOT / "data" / "usim_enact" / PROTOCOL_VERSION


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def group_key(record: Dict) -> str:
    direction = "inverse" if "inverse" in record["type"] else "forward"
    return f"{direction}_L{len(record['key_frame_ids'])}"


def pick_stratified(records: List[Dict], per_group: int, seed: int) -> List[Dict]:
    """Round-robin over episodes inside each group, then fill with the remainder."""
    buckets: Dict[str, List[Dict]] = defaultdict(list)
    for record in records:
        buckets[group_key(record)].append(record)

    rng = random.Random(seed)
    chosen: List[Dict] = []
    leftovers: List[Dict] = []
    for key in sorted(buckets):
        items = sorted(buckets[key], key=lambda r: r["id"])
        by_episode: Dict[str, List[Dict]] = defaultdict(list)
        for item in items:
            by_episode[item["task_name"]].append(item)
        episodes = sorted(by_episode)
        rng.shuffle(episodes)
        picked: List[Dict] = []
        cursor = 0
        while len(picked) < per_group and cursor < 1000:
            progressed = False
            for episode in episodes:
                if len(picked) >= per_group:
                    break
                pool = by_episode[episode]
                if cursor < len(pool):
                    picked.append(pool[cursor])
                    progressed = True
            if not progressed:
                break
            cursor += 1
        chosen.extend(picked)
        used = {item["id"] for item in picked}
        leftovers.extend(item for item in items if item["id"] not in used)
    return chosen, leftovers


def write_jsonl(path: Path, records: List[Dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--qa", default="")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--seed", type=int, default=20261024)
    parser.add_argument("--smoke-per-group", type=int, default=5)
    args = parser.parse_args(argv)

    data_root = Path(args.data_root)
    qa_path = Path(args.qa) if args.qa else data_root / "QA" / "train" / "enact_ordering.jsonl"
    records = [json.loads(line) for line in qa_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not records:
        raise SystemExit(f"empty QA file: {qa_path}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # preflight: one forward L=4 question (4 images in a single request)
    preflight_pool = [r for r in records if r["type"] == "forward_world_modeling_4_steps"]
    if not preflight_pool:
        preflight_pool = [r for r in records if r["type"] == "forward_world_modeling_3_steps"]
        print("[warn] no forward L=4 question, preflight falls back to L=3", file=sys.stderr)
    preflight = sorted(preflight_pool, key=lambda r: r["id"])[:1]

    smoke, leftovers = pick_stratified(records, args.smoke_per_group, args.seed)
    smoke_ids = {r["id"] for r in smoke}
    full = list(smoke) + [r for r in records if r["id"] not in smoke_ids]

    write_jsonl(out_dir / "preflight.jsonl", preflight)
    write_jsonl(out_dir / "smoke.jsonl", smoke)
    write_jsonl(out_dir / "full_dev.jsonl", full)

    def summary(items: List[Dict]) -> Dict[str, object]:
        counts: Dict[str, int] = defaultdict(int)
        for item in items:
            counts[group_key(item)] += 1
        return {
            "count": len(items),
            "by_setting": dict(sorted(counts.items())),
            "episodes": sorted({item["task_name"] for item in items}),
            "tasks": sorted({item["task_name"].split("_episode")[0] for item in items}),
        }

    manifest = {
        "source_qa": str(qa_path),
        "source_qa_sha256": sha256_file(qa_path),
        "seed": args.seed,
        "smoke_per_group": args.smoke_per_group,
        "preflight": summary(preflight),
        "smoke": summary(smoke),
        "full_dev": summary(full),
        "sha256": {
            "preflight.jsonl": sha256_file(out_dir / "preflight.jsonl"),
            "smoke.jsonl": sha256_file(out_dir / "smoke.jsonl"),
            "full_dev.jsonl": sha256_file(out_dir / "full_dev.jsonl"),
        },
    }
    (out_dir / "splits_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: manifest[k]["count"] for k in ("preflight", "smoke", "full_dev")}, ensure_ascii=False))
    print(json.dumps(manifest["smoke"]["by_setting"], ensure_ascii=False))
    print(f"written to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
