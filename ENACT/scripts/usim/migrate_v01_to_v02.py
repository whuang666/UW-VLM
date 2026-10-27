"""Migrate the v0.1 pilot annotations to the v0.2 label semantics.

Only the seven v0.1 episodes are migrated here; the 20 new v0.2 episodes are
annotated from scratch.  Changes applied (all evidence recorded in the migration
manifest, no v0.1 file is modified):

1. ``protocol_version`` -> ``usim-enact-v0.2``.
2. **``OnSeabed`` physical-support correction (review round 2, M1-M3).**  The v0.1
   template set ``OnSeabed=false`` at the grasp frame although the object was
   still resting on the seabed (dvl altitude at its minimum, ascent onset
   22-47 frames later; wrist shows no vertical displacement).  v0.2 keeps
   ``OnSeabed=true`` on every frame where ``InGripper=true`` and
   ``Lifted=false``.
3. Notes: "red cylinder is also present" corrected to "a small red fish may swim
   through the scene" (review M4); v0.2 semantics + review provenance appended.
4. ``NextTo`` stays approach-phase semantics (v0.2 guideline §2.2); the label
   values themselves are unchanged.

Usage:
    python scripts/usim/migrate_v01_to_v02.py \
        --annotations data/usim_enact/usim-enact-v0.1/annotations/episodes \
        --out data/usim_enact/usim-enact-v0.2/annotations/episodes
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enact.adapters.usim_annotations import (  # noqa: E402
    USIMEpisodeAnnotation,
    compile_action_descriptions,
    load_annotations,
    save_annotation,
)

V02_PROTOCOL = "usim-enact-v0.2"
NOTE_REPLACEMENTS = {
    "A red cylinder is also present but is not a manipulated object in this protocol.":
        "A small red fish may swim through the scene; it is not a manipulated object in this protocol.",
    "Blue cylinder; a red cylinder is visible in some frames but is not modelled.":
        "Blue cylinder; a small red fish may pass through some frames and is not modelled.",
    "Clean single grasp; gripper closes at f264, object held at f284, carried clear of the seabed by f364.":
        "Clean single grasp; gripper closes at f264. The object is grasped at f284 but still supported by the seabed "
        "(dvl altitude at its minimum); it is carried clear of the seabed by f364.",
}

# Review round 2 (B group) found annotations that claimed object visibility while the
# target has zero visible pixels in the ego frame.  The corrected visibility makes the
# corresponding transition empty, so the QA builder cannot use it as a reference edge.
VISIBILITY_FIXES = {
    "usim_train_episode_000555": [{"frame_index": 140, "object_id": "red_cylinder", "from": True, "to": False}],
    "usim_train_episode_000556": [{"frame_index": 180, "object_id": "red_cylinder", "from": True, "to": False}],
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def migrate(annotation: USIMEpisodeAnnotation) -> Dict[str, object]:
    payload = annotation.to_dict()
    payload["protocol_version"] = V02_PROTOCOL
    changed_facts: List[Dict[str, object]] = []
    changed_visibility: List[Dict[str, object]] = []

    for fix in VISIBILITY_FIXES.get(annotation.episode_key, []):
        for frame in payload["frames"]:
            if int(frame["frame_index"]) != int(fix["frame_index"]):
                continue
            for entry in frame["visibility"]:
                if entry["object_id"] == fix["object_id"] and bool(entry["value"]) != bool(fix["to"]):
                    entry["value"] = fix["to"]
                    changed_visibility.append(
                        {
                            "frame_index": int(fix["frame_index"]),
                            "object_id": fix["object_id"],
                            "from": fix["from"],
                            "to": fix["to"],
                            "reason": "target has zero visible pixels in the ego frame (review round 2, B group)",
                        }
                    )

    for frame in payload["frames"]:
        values = {(fact["predicate"], tuple(fact["arguments"])): fact for fact in frame["facts"]}
        on_seabed = values.get(("OnSeabed", (frame["facts"][0]["arguments"][0],))) if frame["facts"] else None
        if on_seabed is not None:
            target = on_seabed["arguments"][0]
            in_gripper = values.get(("InGripper", (target,)))
            lifted = values.get(("Lifted", (target,)))
        else:
            in_gripper = lifted = None
        if in_gripper and lifted and on_seabed:
            if in_gripper["value"] is True and lifted["value"] is False and on_seabed["value"] is not True:
                on_seabed["value"] = True
                on_seabed["evidence"] = "review_round2_physical_support+dvl_altitude"
                changed_facts.append(
                    {
                        "frame_index": frame["frame_index"],
                        "relation": "OnSeabed",
                        "from": False,
                        "to": True,
                        "reason": "object is grasped but still supported by the seabed (dvl altitude minimum)",
                    }
                )

    notes = payload.get("notes", "")
    for old, new in NOTE_REPLACEMENTS.items():
        notes = notes.replace(old, new)
    suffix = (
        " [v0.2 migration] OnSeabed uses physical-support semantics: being grasped does not imply leaving the "
        "seabed; OnSeabed flips to false only when Lifted is visible. NextTo keeps approach-phase semantics "
        "(true shortly before the grasp closes, false once grasped). Review: "
        "_review/round2/reviewer_a (A group) and reviewer_b (B group), 2026-10-27."
    )
    if "[v0.2 migration]" not in notes:
        notes = notes.rstrip() + suffix
    payload["notes"] = notes

    migrated = USIMEpisodeAnnotation.from_dict(payload)
    transitions = compile_action_descriptions(migrated)
    return {
        "annotation": migrated,
        "changed_facts": changed_facts,
        "changed_visibility": changed_visibility,
        "transitions": [
            {"from": item["from"], "to": item["to"], "visible": item["visible"], "text": item["text"]}
            for item in transitions
        ],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--annotations", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--manifest", default="")
    args = parser.parse_args(argv)

    annotations = load_annotations(args.annotations)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    entries: List[Dict[str, object]] = []
    for annotation in annotations:
        result = migrate(annotation)
        migrated: USIMEpisodeAnnotation = result["annotation"]  # type: ignore[assignment]
        out_path = out_dir / f"{migrated.episode_key}.json"
        save_annotation(migrated, out_path)
        entries.append(
            {
                "episode_key": migrated.episode_key,
                "source": str(Path(args.annotations) / f"{migrated.episode_key}.json"),
                "source_sha256": sha256_file(Path(args.annotations) / f"{migrated.episode_key}.json"),
                "output": str(out_path),
                "output_sha256": sha256_file(out_path),
                "changed_facts": result["changed_facts"],
                "changed_visibility": result["changed_visibility"],
                "transitions": result["transitions"],
            }
        )
        print(
            f"[migrate] {migrated.episode_key}: {len(result['changed_facts'])} corrected facts, "
            f"{sum(1 for t in result['transitions'] if t['visible'])}/{len(result['transitions'])} visible transitions"
        )

    manifest = {
        "migration_version": "v01-to-v02-labels-v1",
        "source_protocol": "usim-enact-v0.1",
        "target_protocol": V02_PROTOCOL,
        "rule": (
            "protocol bump; OnSeabed=physical support (grasped-but-resting stays true); notes corrected "
            "(red fish); NextTo approach semantics documented; label values otherwise unchanged"
        ),
        "episodes": entries,
    }
    manifest_path = Path(args.manifest) if args.manifest else out_dir.parent.parent / "migration_v01_to_v02.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
