"""Turn a JSON annotation spec into a validated USIM-ENACT annotation.

The neutral annotation format is defined in ``enact/adapters/usim_annotations.py``
and the v0.2 rules in ``docs/WBR/ENACT-USIM-v0.2标注与关键帧规范-20261027.md``.
This tool does NOT invent labels: it only

1. expands the compact spec (facts/visibility shorthand) into the full
   ``USIMEpisodeAnnotation`` payload,
2. fills ``timestamp_seconds`` from the episode Parquet and checks every
   annotated frame exists in the episode,
3. runs ``USIMEpisodeAnnotation.validate()`` (scope completeness, no unknown,
   sorted unique frames, visibility for every object),
4. checks that every key-frame transition is non-empty (v0.2 hard rule), and
5. writes the JSON next to the frozen directory only when asked; ``--check``
   validates generated or existing annotations and prints transition counts.

Spec format (see ``data/usim_enact/_expansion/tools/annotate_spec_template.json``)::

    {
      "protocol_version": "usim-enact-v0.2",
      "episode_key": "usim_train_episode_001304",
      "source_split": "train",
      "objects": [{"object_id": "robot", "category": "agent"}, ...],
      "relations": [["OnSeabed", "red_cylinder"], ["InGripper", "red_cylinder"], ...],
      "frames": [
        {"frame_index": 150, "note": "start",
         "facts": [{"predicate": "OnSeabed", "arguments": ["red_cylinder"], "value": true, "evidence": "frame_review"}],
         "visibility": {"robot": true}},
        ...
      ],
      "visibility_default": true,
      "label_source": "agent_visual_review",
      "annotation_status": "reviewed",
      "notes": "..."
    }

Usage (PowerShell):
    python scripts/usim/annotate_episode.py --spec spec.json --out annotation.json --check
    python scripts/usim/annotate_episode.py --spec spec.json --out data/usim_enact/_expansion/annotation_work/me/ep/
    python scripts/usim/annotate_episode.py --check --annotations data/usim_enact/usim-enact-v0.1/annotations/episodes
    python scripts/usim/annotate_episode.py --check --annotation one.json --verify-frames
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enact.adapters.usim_annotations import (  # noqa: E402
    USIMFact,
    USIMFrame,
    USIMObject,
    USIMEpisodeAnnotation,
    compile_action_descriptions,
)
from enact.adapters.usim_reader import USIMReader, resolve_dataset_root  # noqa: E402

DEFAULT_PROTOCOL_VERSION = "usim-enact-v0.2"
DEFAULT_SPLIT = "train"


class SpecError(ValueError):
    """Raised when the compact spec cannot be expanded into a valid annotation."""


# ----------------------------------------------------------------------- spec io
def load_spec(path: Path) -> Dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SpecError(f"{path}: not valid JSON ({exc})") from exc
    if not isinstance(payload, dict):
        raise SpecError(f"{path}: spec must be a JSON object")
    return payload


def fact_key(predicate: str, arguments: Sequence[str]) -> Tuple[str, Tuple[str, ...]]:
    return str(predicate), tuple(str(value) for value in arguments)


def parse_fact(raw: Dict) -> USIMFact:
    missing = [key for key in ("predicate", "arguments", "value") if key not in raw]
    if missing:
        raise SpecError(f"fact {raw} missing field(s) {missing}")
    value = raw["value"]
    if value is not None and not isinstance(value, bool):
        raise SpecError(f"fact {raw}: value must be true/false (unknown facts must be removed from scope)")
    return USIMFact(
        predicate=str(raw["predicate"]),
        arguments=tuple(str(value) for value in raw["arguments"]),
        value=value,
        evidence=str(raw.get("evidence", "frame_review")),
    )


def parse_visibility(raw: Dict, objects: Sequence[USIMObject], default: bool, method: str) -> List[Dict]:
    object_ids = [obj.object_id for obj in objects]
    overrides = raw or {}
    unknown = sorted(set(overrides) - set(object_ids))
    if unknown:
        raise SpecError(f"visibility overrides use unknown object_id(s): {unknown}")
    entries = []
    for object_id in object_ids:
        value = overrides.get(object_id, default)
        if value is not None and not isinstance(value, bool):
            raise SpecError(f"visibility for {object_id} must be true/false (remove unknown from scope)")
        entries.append(
            {
                "object_id": object_id,
                "camera": "ego",
                "value": value,
                "method": method,
            }
        )
    return entries


def build_annotation_from_spec(spec: Dict, dataset_root: Path, reader: Optional[USIMReader] = None,
                               protocol_version: Optional[str] = None,
                               with_timestamps: bool = True) -> USIMEpisodeAnnotation:
    episode_key = spec.get("episode_key", "")
    source_split = spec.get("source_split", DEFAULT_SPLIT)
    episode_index = spec.get("episode_index")
    if not episode_key and episode_index is None:
        raise SpecError("spec needs episode_key or episode_index")
    if episode_index is None:
        parts = episode_key.split("_")
        if len(parts) != 4 or parts[0] != "usim" or parts[2] != "episode":
            raise SpecError(f"cannot parse episode_index from episode_key {episode_key!r}")
        source_split = parts[1]
        episode_index = int(parts[3])
    reader = reader or USIMReader(dataset_root, split=source_split)
    episode = reader.episode(int(episode_index))
    if episode_key and episode_key != episode.key:
        raise SpecError(f"episode_key {episode_key!r} does not match reader key {episode.key!r}")

    objects = [
        USIMObject(
            object_id=str(item["object_id"]),
            category=str(item["category"]),
            color=item.get("color"),
            description=item.get("description"),
        )
        for item in spec.get("objects", [])
    ]
    if not objects:
        raise SpecError("spec needs at least one object")
    object_ids = {obj.object_id for obj in objects}
    if "robot" not in object_ids:
        raise SpecError("spec objects must include the 'robot' agent object")

    relations: List[Tuple[str, Tuple[str, ...]]] = []
    for raw in spec.get("relations", []):
        if not isinstance(raw, (list, tuple)) or len(raw) < 2:
            raise SpecError(f"relation {raw!r} must look like [predicate, arg1, ...]")
        predicate = str(raw[0])
        arguments = tuple(str(value) for value in raw[1:])
        relations.append((predicate, arguments))
    if not relations:
        raise SpecError("spec needs at least one relation (the annotation scope)")

    frame_payloads = spec.get("frames", [])
    if not frame_payloads:
        raise SpecError("spec needs at least one key frame")
    label_source = str(spec.get("label_source", "agent_visual_review"))
    visibility_default = spec.get("visibility_default", True)
    if not isinstance(visibility_default, bool):
        raise SpecError("visibility_default must be true/false")

    frames: List[USIMFrame] = []
    timestamps = None
    for raw_frame in frame_payloads:
        frame_index = int(raw_frame["frame_index"])
        if not (0 <= frame_index < episode.length):
            raise SpecError(
                f"frame {frame_index} outside episode range [0,{episode.length - 1}] for {episode.key}"
            )
        if timestamps is None and with_timestamps:
            table = reader.load_table(episode.episode_index)
            timestamps = [float(value) for value in table["timestamp"]]
        facts = [parse_fact(item) for item in raw_frame.get("facts", [])]
        # explicit spec check: scope must be complete per frame
        expected = {fact_key(predicate, arguments) for predicate, arguments in relations}
        seen = set()
        for fact in facts:
            if fact.key in seen:
                raise SpecError(f"{episode.key}@{frame_index}: duplicate fact {fact.key}")
            seen.add(fact.key)
        if seen != expected:
            missing = sorted(expected - seen)
            extra = sorted(seen - expected)
            problems = []
            if missing:
                problems.append(f"missing facts {missing}")
            if extra:
                problems.append(f"facts outside the declared relation scope {extra}")
            raise SpecError(f"{episode.key}@{frame_index}: " + "; ".join(problems))
        frames.append(
            USIMFrame(
                frame_index=frame_index,
                timestamp_seconds=(
                    round(timestamps[frame_index], 3)
                    if timestamps is not None and 0 <= frame_index < len(timestamps)
                    else None
                ),
                facts=facts,
                visibility=parse_visibility(
                    raw_frame.get("visibility", {}), objects, visibility_default, label_source
                ),
                note=raw_frame.get("note"),
            )
        )
    frames.sort(key=lambda item: item.frame_index)

    annotation = USIMEpisodeAnnotation(
        episode_key=episode.key,
        source_split=source_split,
        episode_index=episode.episode_index,
        task_text=episode.task_text,
        objects=objects,
        relations=relations,
        frames=frames,
        task_index=episode.task_index,
        protocol_version=protocol_version or spec.get("protocol_version", DEFAULT_PROTOCOL_VERSION),
        label_source=label_source,
        annotation_status=str(spec.get("annotation_status", "reviewed")),
        notes=str(spec.get("notes", "")),
    )
    annotation.validate()
    return annotation


# ---------------------------------------------------------------------- checking
def annotation_report(annotation: USIMEpisodeAnnotation) -> Dict:
    descriptions = compile_action_descriptions(annotation)
    transitions = len(descriptions)
    visible = sum(1 for item in descriptions if item["visible"])
    empty = [item for item in descriptions if not item["visible"]]
    return {
        "episode_key": annotation.episode_key,
        "protocol_version": annotation.protocol_version,
        "key_frames": len(annotation.frames),
        "frame_indices": [frame.frame_index for frame in annotation.frames],
        "relations": [[item[0], *item[1]] for item in annotation.relations],
        "transitions": transitions,
        "visible_transitions": visible,
        "empty_transitions": [
            {"from": item["from"], "to": item["to"], "text": item["text"]} for item in empty
        ],
        "transition_texts": [
            {"from": item["from"], "to": item["to"], "visible": item["visible"], "text": item["text"]}
            for item in descriptions
        ],
        "ok": bool(transitions > 0 and visible == transitions),
    }


def verify_frames(annotation: USIMEpisodeAnnotation, dataset_root: Path) -> List[Dict]:
    reader = USIMReader(dataset_root, split=annotation.source_split)
    episode = reader.episode(annotation.episode_index)
    results = []
    for frame in annotation.frames:
        try:
            image = reader.read_frame(annotation.episode_index, frame.frame_index, camera="ego")
            results.append(
                {
                    "frame_index": frame.frame_index,
                    "ok": True,
                    "shape": list(image.shape),
                }
            )
        except Exception as exc:  # pragma: no cover - decode guard
            results.append(
                {"frame_index": frame.frame_index, "ok": False, "error": str(exc)}
            )
    return {
        "episode_key": episode.key,
        "camera": "ego",
        "checked": len(results),
        "ok": all(item["ok"] for item in results),
        "frames": results,
    }


def print_report(report: Dict) -> None:
    print(
        f"[check] {report['episode_key']}: {report['key_frames']} key frames "
        f"{report['frame_indices']}, {report['transitions']} transitions, "
        f"{report['visible_transitions']} visible, {len(report['empty_transitions'])} empty"
    )
    for item in report["transition_texts"]:
        flag = "OK " if item["visible"] else "EMPTY"
        print(f"  [{flag}] {item['from']} -> {item['to']}: {item['text']}")
    for item in report["empty_transitions"]:
        print(f"  ! transition {item['from']}->{item['to']} is empty (v0.2 requires non-empty transitions)")
    print(f"  relations: {report['relations']}")


def resolve_output_path(out: Optional[str], out_dir: Optional[str], episode_key: str) -> Optional[Path]:
    if out_dir:
        return Path(out_dir) / f"{episode_key}.json"
    if out:
        target = Path(out)
        if target.suffix.lower() == ".json":
            return target
        return target / f"{episode_key}.json"
    return None


# -------------------------------------------------------------------------- main
def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--spec", default="", help="compact annotation spec JSON")
    parser.add_argument("--out", default="", help="output JSON file or directory")
    parser.add_argument("--out-dir", default="", help="output directory (file named <episode_key>.json)")
    parser.add_argument("--dataset-root", default=str(resolve_dataset_root()))
    parser.add_argument("--protocol-version", default="", help="override spec protocol_version")
    parser.add_argument("--check", action="store_true", help="validate and print transition counts")
    parser.add_argument("--annotations", default="", help="directory of existing annotations to check")
    parser.add_argument("--annotation", default="", help="single existing annotation to check")
    parser.add_argument("--verify-frames", action="store_true", help="decode every key frame from ego video")
    parser.add_argument("--allow-empty-transitions", action="store_true",
                        help="only for historical v0.1 checks: do not fail on empty transitions")
    parser.add_argument("--no-timestamps", action="store_true", help="do not fill timestamp_seconds")
    parser.add_argument("--dry-run", action="store_true", help="validate only, do not write")
    args = parser.parse_args(argv)

    dataset_root = Path(args.dataset_root)
    exit_code = 0

    # ------------------------------------------------- existing annotations check
    existing_paths: List[Path] = []
    if args.annotation:
        existing_paths.append(Path(args.annotation))
    if args.annotations:
        directory = Path(args.annotations)
        if not directory.is_dir():
            print(f"not a directory: {directory}", file=sys.stderr)
            return 2
        existing_paths.extend(sorted(directory.glob("*.json")))
    if existing_paths:
        if args.spec:
            print("--spec cannot be combined with --annotation/--annotations", file=sys.stderr)
            return 2
        reports = []
        for path in existing_paths:
            try:
                annotation = USIMEpisodeAnnotation.from_json(path)
            except Exception as exc:  # validation / parse errors
                print(f"[FAIL] {path}: {exc}")
                exit_code = 1
                continue
            report = annotation_report(annotation)
            if args.verify_frames:
                report["frames_check"] = verify_frames(annotation, dataset_root)
                if not report["frames_check"]["ok"]:
                    exit_code = 1
            reports.append(report)
            print_report(report)
            if not report["ok"] and not args.allow_empty_transitions:
                exit_code = 1
        summary = {
            "checked": len(reports),
            "ok": sum(1 for report in reports if report["ok"]),
            "key_frames": sum(report["key_frames"] for report in reports),
            "transitions": sum(report["transitions"] for report in reports),
            "visible_transitions": sum(report["visible_transitions"] for report in reports),
            "episodes": [
                {
                    "episode_key": report["episode_key"],
                    "key_frames": report["key_frames"],
                    "transitions": report["transitions"],
                    "visible_transitions": report["visible_transitions"],
                    "ok": report["ok"],
                }
                for report in reports
            ],
        }
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return exit_code

    # ----------------------------------------------------- spec -> annotation
    if not args.spec:
        print("nothing to do: pass --spec or --annotation/--annotations", file=sys.stderr)
        return 2
    spec_path = Path(args.spec)
    try:
        spec = load_spec(spec_path)
        annotation = build_annotation_from_spec(
            spec,
            dataset_root,
            protocol_version=args.protocol_version or None,
            with_timestamps=not args.no_timestamps,
        )
    except Exception as exc:
        print(f"[FAIL] {spec_path}: {exc}", file=sys.stderr)
        return 1

    report = annotation_report(annotation)
    if not report["ok"] and not args.allow_empty_transitions:
        print_report(report)
        print("[FAIL] empty transitions violate the v0.2 contract", file=sys.stderr)
        return 1

    output_path = resolve_output_path(args.out or None, args.out_dir or None, annotation.episode_key)
    if args.check:
        print_report(report)
        if args.verify_frames:
            frames_check = verify_frames(annotation, dataset_root)
            print(json.dumps(frames_check, indent=2, ensure_ascii=False))
            if not frames_check["ok"]:
                return 1
    if output_path is not None and not args.dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(annotation.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"[wrote] {output_path}")
    elif output_path is not None and args.dry_run:
        print(f"[dry-run] would write {output_path}")
    if not args.check:
        print_report(report)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
