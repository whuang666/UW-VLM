"""``SceneGraphReader`` variant that understands USIM visibility annotations.

Upstream only understands numeric pixel lists.  USIM v0.1 annotations are boolean
(visual review), so we subclass rather than edit upstream code: every upstream
method (diffing, state-centric diffs, signature generation) is inherited unchanged,
only the visibility predicate is replaced.

Both shapes are accepted so that later versions can switch to mask-based
visibility without touching the generators or the verifier:

* ``{"external_sensor1": [count, xmin, ymin, xmax, ymax, h, w]}``  (upstream)
* ``{"external_sensor1": {"method": ..., "value": true, "pixel_count": 172}}``
"""

from __future__ import annotations

from typing import Dict, List, Optional

from enact.adapters.usim_visibility import UPSTREAM_THRESHOLD_PERCENT
from enact.utils.scene_graph_utils import SceneGraphReader


class USIMSceneGraphReader(SceneGraphReader):
    """Scene graph reader with annotation-aware visibility resolution."""

    def __init__(
        self,
        file_path: str,
        filter_transients: bool = False,
        always_full: bool = True,
        visibility_mode: str = "auto",
        unknown_is_visible: bool = False,
    ) -> None:
        """
        Args:
            file_path: Path to a ``*_scene_graph_0.json`` file.
            filter_transients: Passed through to the upstream reader.
            always_full: Passed through to the upstream reader.
            visibility_mode: ``auto`` (annotation wins, mask as fallback),
                ``annotation`` (annotation only) or ``mask`` (pixel count only).
            unknown_is_visible: What to do with ``value: null``.  Defaults to
                ``False`` so that unlabelled objects never leak into a diff.
        """
        if visibility_mode not in ("auto", "annotation", "mask"):
            raise ValueError(f"unknown visibility_mode: {visibility_mode!r}")
        self.visibility_mode = visibility_mode
        self.unknown_is_visible = unknown_is_visible
        self.visibility_source_counts: Dict[str, int] = {
            "annotation_true": 0,
            "annotation_false": 0,
            "annotation_unknown": 0,
            "mask_visible": 0,
            "mask_invisible": 0,
            "unavailable": 0,
        }
        super().__init__(file_path, filter_transients=filter_transients, always_full=always_full)

    # ----------------------------------------------------------------- API
    @classmethod
    def from_graph(cls, graph: Dict[str, Dict], **kwargs) -> "USIMSceneGraphReader":
        """Build a reader from an in-memory scene graph (no temporary file)."""
        instance = cls.__new__(cls)
        instance.visibility_mode = kwargs.get("visibility_mode", "auto")
        instance.unknown_is_visible = kwargs.get("unknown_is_visible", False)
        instance.visibility_source_counts = {
            "annotation_true": 0,
            "annotation_false": 0,
            "annotation_unknown": 0,
            "mask_visible": 0,
            "mask_invisible": 0,
            "unavailable": 0,
        }
        instance.file_path = "<memory>"
        instance.always_full = bool(kwargs.get("always_full", True))
        instance.data = graph
        return instance

    def is_object_visible(self, nodes: List[Dict], sensor_names: List[str], key_object: str) -> bool:
        target_node = next((node for node in nodes if node.get("name") == key_object), None)
        if target_node is None:
            return False
        visibility_data = target_node.get("visibility") or {}
        for camera in sensor_names:
            verdict = self._resolve_camera(visibility_data.get(camera))
            if verdict is True:
                return True
        return False

    def visibility_report(self) -> Dict[str, int]:
        return dict(self.visibility_source_counts)

    # ------------------------------------------------------------- internal
    def _resolve_camera(self, camera_data) -> Optional[bool]:
        if camera_data is None:
            self.visibility_source_counts["unavailable"] += 1
            return None

        # Legacy/upstream numeric list.
        if isinstance(camera_data, (list, tuple)):
            verdict = self._pixel_rule(camera_data)
            if verdict is not None:
                self.visibility_source_counts["mask_visible" if verdict else "mask_invisible"] += 1
            else:
                self.visibility_source_counts["unavailable"] += 1
            return verdict

        if isinstance(camera_data, dict):
            value = camera_data.get("value")
            if self.visibility_mode in ("auto", "annotation") and value is not None:
                verdict = bool(value)
                self.visibility_source_counts[
                    "annotation_true" if verdict else "annotation_false"
                ] += 1
                return verdict

            if self.visibility_mode in ("auto", "mask"):
                numbers = camera_data.get("upstream")
                if numbers is None and camera_data.get("pixel_count") is not None:
                    bbox = camera_data.get("bbox")
                    shape = camera_data.get("image_shape")
                    if bbox is not None and shape is not None:
                        numbers = [
                            camera_data["pixel_count"], *bbox, *shape
                        ]
                if numbers is not None:
                    verdict = self._pixel_rule(numbers)
                    if verdict is not None:
                        self.visibility_source_counts[
                            "mask_visible" if verdict else "mask_invisible"
                        ] += 1
                        return verdict

            if value is None:
                self.visibility_source_counts["annotation_unknown"] += 1
                return True if self.unknown_is_visible else None

        self.visibility_source_counts["unavailable"] += 1
        return None

    @staticmethod
    def _pixel_rule(numbers) -> Optional[bool]:
        try:
            obj_pixel_count, _xmin, _ymin, _xmax, _ymax, height, width = numbers
            total = float(height) * float(width)
            if total <= 0:
                return None
            return (float(obj_pixel_count) / total * 100.0) > UPSTREAM_THRESHOLD_PERCENT
        except (TypeError, ValueError):
            return None
