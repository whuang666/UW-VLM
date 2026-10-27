"""Visibility providers for the USIM adaptation.

Upstream ENACT stores per-camera visibility as
``[obj_pixel_count, xmin, ymin, xmax, ymax, img_height, img_width]`` and treats an
object as visible when it covers more than ``0.005`` percent of the frame.  That
format is only honest when a real mask exists.

For USIM the first protocol version uses **annotated boolean visibility** produced
by visual review of the ego stream.  We therefore keep the annotation value as the
primary signal and store the detector pixel count as auxiliary evidence, never as
a substitute for the annotation.  ``docs/06`` explicitly forbids inventing pixel
counts to slip through the upstream threshold, so the reader below understands
both shapes and records which one answered each query.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

UPSTREAM_THRESHOLD_PERCENT = 0.005


@dataclass
class VisibilityRecord:
    """One visibility statement for (object, camera) at one frame."""

    object_id: str
    camera: str
    value: Optional[bool]              # True / False / None (unknown)
    method: str                        # "agent_visual_review" | "mask_threshold"
    pixel_count: Optional[int] = None
    bbox: Optional[List[int]] = None   # xmin, ymin, xmax, ymax
    image_shape: Optional[List[int]] = None  # height, width

    def to_upstream(self) -> Optional[List[int]]:
        """Upstream list, only when a real mask pixel count exists."""
        if self.pixel_count is None or self.image_shape is None or self.bbox is None:
            return None
        height, width = self.image_shape
        xmin, ymin, xmax, ymax = self.bbox
        return [int(self.pixel_count), int(xmin), int(ymin), int(xmax), int(ymax), int(height), int(width)]

    def to_json(self) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "method": self.method,
            "value": self.value,
        }
        if self.pixel_count is not None:
            payload["pixel_count"] = int(self.pixel_count)
        if self.bbox is not None:
            payload["bbox"] = [int(v) for v in self.bbox]
        if self.image_shape is not None:
            payload["image_shape"] = [int(v) for v in self.image_shape]
        upstream = self.to_upstream()
        if upstream is not None:
            payload["upstream"] = upstream
        return payload


@dataclass
class BooleanVisibilityProvider:
    """Lookup of annotated boolean visibility keyed by (object_id, camera, frame)."""

    records: Dict[tuple, VisibilityRecord] = field(default_factory=dict)

    def add(self, frame_index: int, record: VisibilityRecord) -> None:
        self.records[(record.object_id, record.camera, int(frame_index))] = record

    def get(self, object_id: str, camera: str, frame_index: int) -> Optional[VisibilityRecord]:
        return self.records.get((object_id, camera, int(frame_index)))

    def truth(self, object_id: str, camera: str, frame_index: int) -> Optional[bool]:
        record = self.get(object_id, camera, frame_index)
        return None if record is None else record.value

    def objects_visible_at(self, camera: str, frame_index: int) -> List[str]:
        return sorted(
            object_id
            for (object_id, cam, frame), record in self.records.items()
            if cam == camera and frame == int(frame_index) and record.value is True
        )

    @classmethod
    def from_visibility_entries(
        cls, frame_index: int, entries: Iterable[Dict[str, object]]
    ) -> "BooleanVisibilityProvider":
        provider = cls()
        for entry in entries:
            provider.add(
                frame_index,
                VisibilityRecord(
                    object_id=str(entry["object_id"]),
                    camera=str(entry["camera"]),
                    value=entry.get("value"),
                    method=str(entry.get("method", "agent_visual_review")),
                    pixel_count=entry.get("pixel_count"),
                    bbox=entry.get("bbox"),
                    image_shape=entry.get("image_shape"),
                ),
            )
        return provider


@dataclass
class MaskVisibilityProvider:
    """Visibility derived from a real segmentation mask (pixel-count rule)."""

    threshold_percent: float = UPSTREAM_THRESHOLD_PERCENT

    def is_visible(self, record: VisibilityRecord) -> Optional[bool]:
        if record.pixel_count is None or record.image_shape is None:
            return None
        total = int(record.image_shape[0]) * int(record.image_shape[1])
        if total <= 0:
            return None
        return (record.pixel_count / total * 100.0) > self.threshold_percent
