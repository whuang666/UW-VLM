"""Collect, validate and freeze the v0.2 annotation drafts into the dataset tree.

Annotators write working copies under
``data/usim_enact/_expansion/annotation_work/<annotator>/<episode>/annotation_spec.json``.
This script validates every draft against the v0.2 rules and copies the accepted
files into ``usim-enact-v0.2/annotations/episodes/`` (the seven migrated v0.1
episodes are already there and are never overwritten unless ``--overwrite``).

Validation gates (all must pass, otherwise exit 2 and nothing is published):

* schema validation via :class:`USIMEpisodeAnnotation.from_json` (scope coverage,
  sorted unique frames, no ``unknown`` values, visibility for every object);
* ``protocol_version == usim-enact-v0.2`` and episode in ``dev_new``/``val_new``
  of ``annotation_assignment.json`` (test_reserve is never collected before freeze);
* 4-6 key frames; every adjacent transition visible and non-empty
  (``visible == len(frames) - 1``) -- this is the reference-transition gate that
  the v0.3 scorer will later enforce again;
* at least one transition for every episode and at least 2 for episodes with 4+
  frames (a single-state episode cannot produce a question);
* target object visible in every key frame.

Usage:
    python scripts/usim/collect_v02_annotations.py
    python scripts/usim/collect_v02_annotations.py --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enact.adapters.usim_annotations import (  # noqa: E402
    USIMEpisodeAnnotation,
    compile_action_descriptions,
)

V02_PROTOCOL = "usim-enact-v0.2"
EXPANSION = ROOT / "data" / "usim_enact" / "_expansion"
V02_ROOT = ROOT / "data" / "usim_enact" / "usim-enact-v0.2"
ASSIGNMENT = EXPANSION / "annotation_assignment.json"
WORK_ROOT = EXPANSION / "annotation_work"
TARGET_DIR = V02_ROOT / "annotations" / "episodes"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_one(path: Path, allowed_episodes: set) -> Dict:
    annotation = USIMEpisodeAnnotation.from_json(path)
    problems: List[str] = []
    if annotation.protocol_version != V02_PROTOCOL:
        problems.append(f"protocol_version={annotation.protocol_version!r}, expected {V02_PROTOCOL}")
    if annotation.episode_key not in allowed_episodes:
        problems.append(f"episode {annotation.episode_key} is not in dev_new/val_new (test_reserve must stay untouched)")
    if annotation.source_split != "train":
        problems.append(f"source_split={annotation.source_split!r}, expected 'train'")
    frame_count = len(annotation.frames)
    if not 3 <= frame_count <= 6:
        problems.append(f"{frame_count} key frames, expected 3-6 (3 only when the episode truly has 3 states)")

    transitions = compile_action_descriptions(annotation)
    visible = [item for item in transitions if item["visible"] and item["text"].strip()]
    if len(visible) != len(transitions):
        problems.append(
            f"{len(transitions) - len(visible)}/{len(transitions)} adjacent transitions are empty/invisible"
        )
    if len(visible) < 2:
        problems.append(f"only {len(visible)} visible transitions; cannot build L>=3 questions")

    for frame in annotation.frames:
        for entry in frame.visibility:
            if entry.get("value") is not True:
                problems.append(f"frame {frame.frame_index}: object {entry.get('object_id')} visibility is not true")

    status = "ok" if not problems else "rejected"
    return {
        "episode_key": annotation.episode_key,
        "source": str(path.relative_to(ROOT)),
        "source_sha256": sha256_file(path),
        "status": status,
        "problems": problems,
        "key_frames": annotation.key_frame_ids,
        "frame_count": frame_count,
        "relations": [[predicate, *args] for predicate, args in annotation.relations],
        "visible_transitions": len(visible),
        "transitions": [
            {"from": item["from"], "to": item["to"], "visible": item["visible"], "text": item["text"]}
            for item in transitions
        ],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="validate only, do not copy")
    parser.add_argument("--overwrite", action="store_true", help="overwrite existing v0.2 annotation files")
    parser.add_argument("--manifest", default=str(EXPANSION / "annotation_collection.json"))
    args = parser.parse_args(argv)

    assignment = json.loads(ASSIGNMENT.read_text(encoding="utf-8"))
    allowed = set(assignment["dev_new"]) | set(assignment["val_new"])
    expected = sorted(allowed)

    drafts: Dict[str, Path] = {}
    draft_names = ("annotation_spec.json", "annotation.json")
    candidates: Dict[str, List[Path]] = {}
    for path in sorted(WORK_ROOT.glob("*/*/*.json")):
        if path.name not in draft_names:
            continue
        if path.parent.name in ("_tools", "_shared", "review"):
            continue
        candidates.setdefault(path.parent.name, []).append(path)

    def loads_as_annotation(path: Path) -> bool:
        try:
            USIMEpisodeAnnotation.from_json(path)
            return True
        except Exception:
            return False

    for episode, paths in sorted(candidates.items()):
        # Annotators may keep both a compact spec and the compiled annotation; use
        # whichever file validates as a full USIMEpisodeAnnotation (prefer the tool
        # output ``annotation.json``), else fall back for a readable error.
        ordered = [path for path in paths if path.name == "annotation.json"] + [
            path for path in paths if path.name == "annotation_spec.json"
        ]
        valid = [path for path in ordered if loads_as_annotation(path)]
        drafts[episode] = valid[0] if valid else (ordered[0] if ordered else paths[0])

    entries = []
    rejected = []
    for episode, path in sorted(drafts.items()):
        try:
            entry = validate_one(path, allowed)
        except Exception as error:  # schema error is a hard failure
            entry = {
                "episode_key": episode,
                "source": str(path.relative_to(ROOT)),
                "source_sha256": sha256_file(path),
                "status": "rejected",
                "problems": [f"{type(error).__name__}: {error}"],
            }
        entries.append(entry)
        if entry["status"] != "ok":
            rejected.append(entry)

    missing = sorted(allowed - set(drafts))
    manifest = {
        "collection_version": "v02-annotation-collection-v1",
        "protocol_version": V02_PROTOCOL,
        "assignment": str(ASSIGNMENT.relative_to(ROOT)),
        "assignment_sha256": sha256_file(ASSIGNMENT),
        "expected_episodes": expected,
        "collected_episodes": sorted(drafts),
        "missing_episodes": missing,
        "entries": entries,
        "counts": {
            "expected": len(expected),
            "drafted": len(drafts),
            "accepted": len([entry for entry in entries if entry["status"] == "ok"]),
            "rejected": len(rejected),
        },
        "target_dir": str(TARGET_DIR.relative_to(ROOT)),
    }

    if rejected:
        print(f"{len(rejected)} annotation draft(s) rejected:", file=sys.stderr)
        for entry in rejected:
            print(f"  - {entry['episode_key']}: {entry['problems']}", file=sys.stderr)
        Path(args.manifest).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return 2

    if args.dry_run:
        print(json.dumps(manifest["counts"], ensure_ascii=False))
        print(f"dry-run: would collect {len(entries)} annotations into {TARGET_DIR}")
        return 0

    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        source = Path(ROOT) / entry["source"]
        destination = TARGET_DIR / f"{entry['episode_key']}.json"
        if destination.exists() and not args.overwrite:
            print(f"refusing to overwrite existing annotation: {destination}", file=sys.stderr)
            return 2
        shutil.copy2(source, destination)
        entry["published"] = str(destination.relative_to(ROOT))
        entry["published_sha256"] = sha256_file(destination)

    Path(args.manifest).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(manifest["counts"], ensure_ascii=False))
    if missing:
        print(f"WARNING: {len(missing)} assigned episodes still missing: {missing}", file=sys.stderr)
    print(f"manifest: {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
