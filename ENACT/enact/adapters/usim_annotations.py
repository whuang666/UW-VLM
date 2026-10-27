"""USIM annotation schema and compilation into ENACT scene graphs.

The annotation file is deliberately *not* an ENACT scene graph.  It is a neutral,
reviewable record with three-valued facts (``true`` / ``false`` / ``null``) and an
explicit relation scope.  Compilation to ENACT's closed-world scene graph is only
allowed when every relation in scope is fully labelled for every key frame in the
episode -- otherwise ``false`` would be invented from missing data (see docs/06 §3).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from enact.adapters.usim_translator import USIM_EDGE_PREDICATES, USIM_NODE_STATE_NAMES
from enact.utils.state_change_translator import StateChangeTranslator

PROTOCOL_VERSION = "usim-enact-v0.1"
SENSOR_NAME = "external_sensor1"          # upstream single-camera reader
USIM_CAMERA = "ego"
LABEL_SOURCE = "agent_visual_review"

EDGE_PREDICATES = set(USIM_EDGE_PREDICATES) | {
    "AttachedTo",
    "Contains",
    "Covered",
    "Draped",
    "Filled",
    "Overlaid",
    "Saturated",
    "Under",
    "LeftGrasping",
    "RightGrasping",
}
NODE_PREDICATES = set(USIM_NODE_STATE_NAMES) | {
    "Burnt",
    "Cooked",
    "Folded",
    "Unfolded",
    "Frozen",
    "HeatSourceOrSink",
    "Heated",
    "OnFire",
    "InFOVofRobot",
    "Open",
    "ToggledOn",
}


class AnnotationError(ValueError):
    """Raised when an annotation violates the USIM-ENACT protocol."""


# --------------------------------------------------------------------------- schema
def _parse_relation(item: Sequence) -> Tuple[str, Tuple[str, ...]]:
    """Accept both ``["NextTo", "robot", "red_cylinder"]`` and the nested form."""
    predicate = str(item[0])
    if len(item) == 2 and isinstance(item[1], (list, tuple)):
        return predicate, tuple(str(v) for v in item[1])
    return predicate, tuple(str(v) for v in item[1:])


@dataclass
class USIMObject:
    object_id: str
    category: str
    color: Optional[str] = None
    description: Optional[str] = None

    def to_node(self) -> Dict[str, object]:
        return {"name": self.object_id, "category": self.category, "states": []}


@dataclass
class USIMFact:
    predicate: str
    arguments: Tuple[str, ...]
    value: Optional[bool]
    evidence: str = "frame_review"

    @property
    def key(self) -> Tuple[str, Tuple[str, ...]]:
        return (self.predicate, tuple(self.arguments))


@dataclass
class USIMFrame:
    frame_index: int
    timestamp_seconds: Optional[float] = None
    facts: List[USIMFact] = field(default_factory=list)
    visibility: List[Dict[str, object]] = field(default_factory=list)
    note: Optional[str] = None


@dataclass
class USIMEpisodeAnnotation:
    episode_key: str
    source_split: str
    episode_index: int
    task_text: str
    objects: List[USIMObject]
    relations: List[Tuple[str, Tuple[str, ...]]]
    frames: List[USIMFrame]
    task_index: Optional[int] = None
    protocol_version: str = PROTOCOL_VERSION
    label_source: str = LABEL_SOURCE
    annotation_status: str = "reviewed"
    notes: str = ""

    # ---------------------------------------------------------------- loading
    @classmethod
    def from_json(cls, path: str | Path) -> "USIMEpisodeAnnotation":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(payload)

    @classmethod
    def from_dict(cls, payload: Dict) -> "USIMEpisodeAnnotation":
        objects = [
            USIMObject(
                object_id=item["object_id"],
                category=item["category"],
                color=item.get("color"),
                description=item.get("description"),
            )
            for item in payload["objects"]
        ]
        relations = [_parse_relation(item) for item in payload["relations"]]
        frames = []
        for raw_frame in payload["frames"]:
            facts = [
                USIMFact(
                    predicate=item["predicate"],
                    arguments=tuple(item["arguments"]),
                    value=item.get("value"),
                    evidence=item.get("evidence", "frame_review"),
                )
                for item in raw_frame.get("facts", [])
            ]
            frames.append(
                USIMFrame(
                    frame_index=int(raw_frame["frame_index"]),
                    timestamp_seconds=raw_frame.get("timestamp_seconds"),
                    facts=facts,
                    visibility=list(raw_frame.get("visibility", [])),
                    note=raw_frame.get("note"),
                )
            )
        annotation = cls(
            episode_key=payload["episode_key"],
            source_split=payload["source_split"],
            episode_index=int(payload["episode_index"]),
            task_text=payload.get("task_text", ""),
            objects=objects,
            relations=relations,
            frames=frames,
            task_index=payload.get("task_index"),
            protocol_version=payload.get("protocol_version", PROTOCOL_VERSION),
            label_source=payload.get("label_source", LABEL_SOURCE),
            annotation_status=payload.get("annotation_status", "reviewed"),
            notes=payload.get("notes", ""),
        )
        annotation.validate()
        return annotation

    def to_dict(self) -> Dict[str, object]:
        return {
            "protocol_version": self.protocol_version,
            "episode_key": self.episode_key,
            "source_split": self.source_split,
            "episode_index": self.episode_index,
            "task_index": self.task_index,
            "task_text": self.task_text,
            "label_source": self.label_source,
            "annotation_status": self.annotation_status,
            "notes": self.notes,
            "objects": [
                {
                    "object_id": obj.object_id,
                    "category": obj.category,
                    **({"color": obj.color} if obj.color else {}),
                    **({"description": obj.description} if obj.description else {}),
                }
                for obj in self.objects
            ],
            "relations": [[pred, *args] for pred, args in self.relations],
            "frames": [
                {
                    "frame_index": frame.frame_index,
                    **({"timestamp_seconds": frame.timestamp_seconds} if frame.timestamp_seconds is not None else {}),
                    "facts": [
                        {
                            "predicate": fact.predicate,
                            "arguments": list(fact.arguments),
                            "value": fact.value,
                            "evidence": fact.evidence,
                        }
                        for fact in frame.facts
                    ],
                    "visibility": frame.visibility,
                    **({"note": frame.note} if frame.note else {}),
                }
                for frame in self.frames
            ],
        }

    # ------------------------------------------------------------- validation
    def validate(self) -> None:
        object_ids = {obj.object_id for obj in self.objects}
        if len(object_ids) != len(self.objects):
            raise AnnotationError(f"{self.episode_key}: duplicate object_id")

        if not self.frames:
            raise AnnotationError(f"{self.episode_key}: no key frames")
        indices = [frame.frame_index for frame in self.frames]
        if indices != sorted(indices):
            raise AnnotationError(f"{self.episode_key}: key frames must be sorted, got {indices}")
        if len(set(indices)) != len(indices):
            raise AnnotationError(f"{self.episode_key}: duplicate key frame indices {indices}")

        for predicate, args in self.relations:
            if predicate in NODE_PREDICATES and len(args) != 1:
                raise AnnotationError(f"{self.episode_key}: node predicate {predicate} needs 1 argument")
            if predicate in EDGE_PREDICATES and len(args) != 2:
                raise AnnotationError(f"{self.episode_key}: edge predicate {predicate} needs 2 arguments")
            if predicate not in NODE_PREDICATES and predicate not in EDGE_PREDICATES:
                raise AnnotationError(
                    f"{self.episode_key}: predicate {predicate} is not in the upstream "
                    "StateChangeTranslator vocabulary, so it would render as an empty action"
                )
            for arg in args:
                if arg not in object_ids:
                    raise AnnotationError(f"{self.episode_key}: relation {predicate}{args} uses unknown object {arg}")

        relation_keys = {(pred, tuple(args)) for pred, args in self.relations}
        for frame in self.frames:
            seen = set()
            for fact in frame.facts:
                key = fact.key
                if key in seen:
                    raise AnnotationError(f"{self.episode_key}@{frame.frame_index}: duplicate fact {key}")
                seen.add(key)
                if key not in relation_keys:
                    raise AnnotationError(
                        f"{self.episode_key}@{frame.frame_index}: fact {key} is outside the declared relation scope"
                    )
                if fact.value is None:
                    raise AnnotationError(
                        f"{self.episode_key}@{frame.frame_index}: relation {key} is 'unknown'; "
                        "unknown relations must be removed from the scope instead of compiled"
                    )
            missing = relation_keys - seen
            if missing:
                raise AnnotationError(
                    f"{self.episode_key}@{frame.frame_index}: relation scope not fully labelled, missing {sorted(missing)}"
                )
            vis_ids = {item["object_id"] for item in frame.visibility}
            for obj in self.objects:
                if obj.object_id not in vis_ids:
                    raise AnnotationError(
                        f"{self.episode_key}@{frame.frame_index}: missing visibility for {obj.object_id}"
                    )

    # --------------------------------------------------------------- helpers
    def frame(self, frame_index: int) -> USIMFrame:
        for frame in self.frames:
            if frame.frame_index == frame_index:
                return frame
        raise KeyError(f"{self.episode_key}: frame {frame_index} not annotated")

    @property
    def key_frame_ids(self) -> List[str]:
        return [str(frame.frame_index) for frame in self.frames]

    def relation_values(self, frame: USIMFrame) -> Dict[Tuple[str, Tuple[str, ...]], bool]:
        return {fact.key: bool(fact.value) for fact in frame.facts}


# ----------------------------------------------------------------------- compile
def compile_scene_graph(annotation: USIMEpisodeAnnotation) -> Dict[str, Dict]:
    """Compile an annotation into the ENACT ``scene_graph_0.json`` layout."""
    annotation.validate()
    graph: Dict[str, Dict] = {}
    for frame in annotation.frames:
        nodes = []
        for obj in annotation.objects:
            node = obj.to_node()
            node["visibility"] = _visibility_payload(annotation, frame, obj.object_id)
            nodes.append(node)
        edges = [
            {"from": fact.arguments[0], "to": fact.arguments[1], "states": [fact.predicate]}
            for fact in frame.facts
            if fact.value is True and fact.predicate in EDGE_PREDICATES
        ]
        for node in nodes:
            states = [
                fact.predicate
                for fact in frame.facts
                if fact.value is True
                and fact.predicate in NODE_PREDICATES
                and fact.arguments[0] == node["name"]
            ]
            node["states"] = sorted(states)
        graph[str(frame.frame_index)] = {"type": "full", "nodes": nodes, "edges": edges}
    return graph


def _visibility_payload(annotation: USIMEpisodeAnnotation, frame: USIMFrame, object_id: str) -> Dict[str, object]:
    entry = next(item for item in frame.visibility if item["object_id"] == object_id)
    payload: Dict[str, object] = {
        "method": entry.get("method", annotation.label_source),
        "value": entry.get("value"),
    }
    for key in ("pixel_count", "bbox", "image_shape"):
        if entry.get(key) is not None:
            payload[key] = entry[key]
    if payload.get("pixel_count") is not None and payload.get("bbox") and payload.get("image_shape"):
        payload["upstream"] = [
            int(payload["pixel_count"]),
            *[int(v) for v in payload["bbox"]],
            *[int(v) for v in payload["image_shape"]],
        ]
    return {SENSOR_NAME: payload}


def compile_action_descriptions(annotation: USIMEpisodeAnnotation) -> List[Dict[str, object]]:
    """Human-readable transition list, used for review and for the run report."""
    from enact.adapters.usim_scene_graph import USIMSceneGraphReader
    from enact.adapters.usim_translator import USIMStateChangeTranslator

    translator = USIMStateChangeTranslator(type="multi_forward_world_modeling")
    graph = compile_scene_graph(annotation)
    reader = USIMSceneGraphReader.from_graph(graph)
    descriptions: List[Dict[str, object]] = []
    keys = list(graph.keys())
    for left, right in zip(keys, keys[1:]):
        diff = reader.get_visible_full_diff(left, right, [SENSOR_NAME], partial_diff=True)
        text = translator.translate_diff(diff)
        descriptions.append(
            {
                "from": left,
                "to": right,
                "visible": diff.get("type") != "empty",
                "text": text,
                "signatures": sorted(reader.diff_signature(diff)) if diff.get("type") != "empty" else [],
            }
        )
    return descriptions


def load_annotations(directory: str | Path) -> List[USIMEpisodeAnnotation]:
    annotations = []
    for path in sorted(Path(directory).glob("*.json")):
        annotations.append(USIMEpisodeAnnotation.from_json(path))
    return annotations


def save_annotation(annotation: USIMEpisodeAnnotation, path: str | Path) -> None:
    annotation.validate()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(annotation.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def summary_table(annotations: Sequence[USIMEpisodeAnnotation]) -> List[Dict[str, object]]:
    rows = []
    for annotation in annotations:
        descriptions = compile_action_descriptions(annotation)
        rows.append(
            {
                "episode_key": annotation.episode_key,
                "task_text": annotation.task_text,
                "key_frames": len(annotation.frames),
                "relations": len(annotation.relations),
                "valid_transitions": sum(1 for item in descriptions if item["visible"]),
                "transitions": len(descriptions),
            }
        )
    return rows
