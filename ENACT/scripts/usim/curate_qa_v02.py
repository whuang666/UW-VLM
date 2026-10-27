"""Curate a balanced v0.2 ENACT-USIM QA set.

The upstream generators emit every valid key-frame combination (``C(n,3)`` L=3
questions for ``n`` annotated frames, ...), which would leave L=3 dominating the
set even though its chance level is 0.5.  For v0.2 we keep a fixed, documented
quota per episode and direction:

* L=5: all available up to the quota (rarest, lowest chance level),
* L=4: quota,
* L=3: small quota (compatibility with v0.1 / ENACT).

Forward and inverse questions that share the same chronological path
(``key_frame_ids``) are selected *together* so paired direction comparisons stay
exact.  Selection is deterministic: candidate paths are ordered by a seeded
hash of the path, never by model performance.

Usage:
    python scripts/usim/curate_qa_v02.py \
        --data-root data/usim_enact/usim-enact-v0.2 \
        --qa data/usim_enact/usim-enact-v0.2/QA/train/enact_ordering.jsonl \
        --out data/usim_enact/usim-enact-v0.2/QA/train/enact_ordering_curated.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# v0.2 composition rationale: L=3 has a chance level of 0.5 and is only kept for
# compatibility with the ENACT/v0.1 protocol (one per episode); L=4 (chance 1/6) and
# L=5 (chance 1/24) carry the discriminative signal.
DEFAULT_QUOTAS = {5: 2, 4: 3, 3: 1}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def direction_of(record: Dict) -> str:
    return "inverse" if "inverse" in record["type"] else "forward"


def length_of(record: Dict) -> int:
    return len(record["key_frame_ids"])


def parse_quotas(text: str) -> Dict[int, int]:
    quotas: Dict[int, int] = {}
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        length, quota = part.split(":")
        quotas[int(length)] = int(quota)
    return quotas


def stable_key(seed: int, *parts: object) -> str:
    payload = "|".join([str(seed), *[str(part) for part in parts]])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def curate(
    records: Sequence[Dict],
    quotas: Dict[int, int],
    seed: int,
) -> Tuple[List[Dict], Dict]:
    """Return ``(selected_records, manifest)``.

    Records are grouped by ``(episode, chronological path)``; every group may hold
    one forward and one inverse question.  Groups are visited by descending
    question length, then by seeded hash of the path.
    """
    by_episode: Dict[str, Dict[Tuple, Dict[str, Dict]]] = defaultdict(lambda: defaultdict(dict))
    for record in records:
        episode = record["task_name"]
        path = tuple(str(v) for v in record["key_frame_ids"])
        by_episode[episode][path][direction_of(record)] = record

    selected: List[Dict] = []
    selected_ids = set()
    excluded: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    per_setting: Dict[str, int] = defaultdict(int)
    per_episode_setting: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    pair_stats = {"paired_paths_selected": 0, "single_direction_paths_selected": 0, "missing_direction_paths": 0}

    episodes = sorted(by_episode)
    for episode in episodes:
        paths = by_episode[episode]
        taken: Dict[Tuple[int, str], int] = defaultdict(int)
        ordered = sorted(
            paths.items(),
            key=lambda item: (-len(item[0]), stable_key(seed, episode, *item[0])),
        )
        for path, group in ordered:
            length = len(path)
            quota = quotas.get(length)
            if quota is None:
                for record in group.values():
                    excluded["unsupported_length"][record["type"]] += 1
                continue
            directions = ["forward", "inverse"]
            wanted = [
                direction for direction in directions
                if direction in group and taken[(length, direction)] < quota
            ]
            if not wanted:
                for record in group.values():
                    if record["id"] not in selected_ids:
                        excluded["over_quota"][record["type"]] += 1
                continue
            if len(group) == 2:
                if len(wanted) == 2:
                    pair_stats["paired_paths_selected"] += 1
                else:
                    pair_stats["missing_direction_paths"] += 1
            else:
                pair_stats["single_direction_paths_selected"] += 1
            for direction in directions:
                if direction not in group:
                    excluded["missing_direction"][group[next(iter(group))]["type"]] += 1
                    continue
                record = group[direction]
                if direction not in wanted:
                    excluded["over_quota_unpaired"][record["type"]] += 1
                    continue
                if record["id"] in selected_ids:
                    continue
                selected.append(record)
                selected_ids.add(record["id"])
                taken[(length, direction)] += 1
                per_setting[record["type"]] += 1
                per_episode_setting[episode][record["type"]] += 1

    identity_hits = sum(
        1 for record in selected
        if list(record["gt_answer"]) == list(range(1, len(record["gt_answer"]) + 1))
    )
    total = len(selected)
    manifest = {
        "curation_version": "usim-enact-v0.2-curation-v1",
        "seed": seed,
        "quotas_per_episode_per_direction": {str(k): v for k, v in sorted(quotas.items(), reverse=True)},
        "method": (
            "group questions by (episode, chronological key_frame_ids); visit lengths 5->4->3; "
            "select paired forward+inverse paths first, order by seeded sha256, never by model score"
        ),
        "total_input_questions": len(records),
        "total_selected": total,
        "by_type": dict(sorted(per_setting.items())),
        "by_length": {
            str(length): sum(
                1 for record in selected if len(record["key_frame_ids"]) == length
            )
            for length in sorted({len(record["key_frame_ids"]) for record in selected}, reverse=True)
        },
        "identity_reference_rate": round(identity_hits / total, 4) if total else None,
        "pairing": pair_stats,
        "episodes": sorted({record["task_name"] for record in selected}),
        "per_episode_by_type": {episode: dict(sorted(counts.items())) for episode, counts in sorted(per_episode_setting.items())},
        "excluded_by_reason": {reason: dict(sorted(counts.items())) for reason, counts in sorted(excluded.items())},
    }
    return selected, manifest


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--qa", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--manifest", default="")
    parser.add_argument("--quotas", default=",".join(f"{k}:{v}" for k, v in sorted(DEFAULT_QUOTAS.items(), reverse=True)))
    parser.add_argument("--seed", type=int, default=20261027)
    args = parser.parse_args(argv)

    qa_path = Path(args.qa)
    records = [json.loads(line) for line in qa_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [record["id"] for record in records]
    if len(set(ids)) != len(ids):
        print("input QA has duplicate ids", file=sys.stderr)
        return 2
    quotas = parse_quotas(args.quotas)
    selected, manifest = curate(records, quotas, args.seed)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for record in selected:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    manifest.update(
        {
            "input_qa": str(qa_path),
            "input_qa_sha256": sha256_file(qa_path),
            "output_qa": str(out_path),
            "output_qa_sha256": sha256_file(out_path),
        }
    )
    manifest_path = Path(args.manifest) if args.manifest else out_path.with_name(out_path.stem + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: manifest[key] for key in ("total_input_questions", "total_selected", "by_type", "by_length", "identity_reference_rate")}, ensure_ascii=False, indent=1))
    print(f"curated: {out_path}")
    print(f"manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
