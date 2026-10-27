"""LeRobot v2.1 reader for the USIM underwater dataset.

Design notes
------------
1. USIM ships Parquet rows (proprioception / action / target_pos) and RGB as
   separate MP4 streams.  Row ``i`` of an episode Parquet corresponds to video
   frame ``i``; ``frame_index`` restarts at 0 for every episode.  ``align_check``
   verifies this before any annotation is trusted.
2. Episode numbers are reused across the ``train`` and ``test`` splits, so every
   key carries the split prefix: ``usim_train_episode_001300``.
3. Nothing here writes into the USIM tree.  Original files are opened read-only.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence

import cv2
import numpy as np
import pyarrow.parquet as pq

CAMERAS = ("ego", "wrist")

# LeRobot feature key -> USIM camera name used by this adapter.
CAMERA_FEATURE = {
    "ego": "observation.images.ego",
    "wrist": "observation.images.wrist",
}

# Half-open state slices declared by meta/modality.json (verified in docs/03).
STATE_SLICES = {
    "joint_pos": (0, 5),
    "pwm": (5, 13),
    "joint_v": (13, 18),
    "dvl_v": (18, 21),
    "imu_av": (21, 24),
    "imu_la": (24, 27),
    "pressure": (27, 28),
    "dvl_h": (28, 29),
}


def episode_key(split: str, episode_index: int) -> str:
    """Globally unique episode key (split prefix is mandatory)."""
    if split not in ("train", "test"):
        raise ValueError(f"unknown split: {split!r}")
    return f"usim_{split}_episode_{int(episode_index):06d}"


def parse_episode_key(key: str) -> tuple[str, int]:
    parts = key.split("_")
    if len(parts) != 4 or parts[0] != "usim" or parts[2] != "episode":
        raise ValueError(f"not a USIM episode key: {key!r}")
    return parts[1], int(parts[3])


@dataclass
class USIMEpisode:
    """Metadata for one episode, as declared by the dataset itself."""

    split: str
    episode_index: int
    length: int
    task_text: str
    task_index: Optional[int] = None

    @property
    def key(self) -> str:
        return episode_key(self.split, self.episode_index)

    def to_dict(self) -> Dict[str, object]:
        return {
            "episode_key": self.key,
            "source_split": self.split,
            "episode_index": self.episode_index,
            "length": self.length,
            "task_text": self.task_text,
            "task_index": self.task_index,
        }


@dataclass
class USIMReader:
    """Read-only access to one split of the USIM dataset."""

    dataset_root: str | Path
    split: str = "train"
    _info: Dict = field(default_factory=dict, init=False, repr=False)
    _episodes: Dict[int, USIMEpisode] = field(default_factory=dict, init=False, repr=False)
    _task_to_index: Dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _frame_cache: Dict[tuple, np.ndarray] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self.dataset_root = Path(self.dataset_root)
        split_root = self.dataset_root / self.split
        if not split_root.is_dir():
            raise FileNotFoundError(f"split directory not found: {split_root}")
        self.split_root = split_root
        self._load_meta()

    # ------------------------------------------------------------------ meta
    def _load_meta(self) -> None:
        info_path = self.split_root / "meta" / "info.json"
        self._info = json.loads(info_path.read_text(encoding="utf-8"))
        self.fps = float(self._info.get("fps", 10.0))
        self.chunks_size = int(self._info.get("chunks_size", 1000))
        self.data_path_tpl = self._info["data_path"]
        self.video_path_tpl = self._info["video_path"]

        tasks_path = self.split_root / "meta" / "tasks.jsonl"
        if tasks_path.exists():
            for line in tasks_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                self._task_to_index[record["task"]] = int(record["task_index"])

        episodes_path = self.split_root / "meta" / "episodes.jsonl"
        for line in episodes_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            tasks = record.get("tasks") or []
            text = tasks[0] if tasks else ""
            self._episodes[int(record["episode_index"])] = USIMEpisode(
                split=self.split,
                episode_index=int(record["episode_index"]),
                length=int(record["length"]),
                task_text=text,
                task_index=self._task_to_index.get(text),
            )

    @property
    def info(self) -> Dict:
        return dict(self._info)

    @property
    def episodes(self) -> Dict[int, USIMEpisode]:
        return dict(self._episodes)

    def episode(self, episode_index: int) -> USIMEpisode:
        try:
            return self._episodes[int(episode_index)]
        except KeyError as exc:  # pragma: no cover - defensive
            raise KeyError(f"episode {episode_index} not declared in {self.split}/meta/episodes.jsonl") from exc

    def find_episodes(self, task_text: str) -> List[USIMEpisode]:
        return [e for e in self._episodes.values() if e.task_text == task_text]

    # ----------------------------------------------------------------- paths
    def _chunk(self, episode_index: int) -> int:
        return int(episode_index) // self.chunks_size

    def parquet_path(self, episode_index: int) -> Path:
        rel = self.data_path_tpl.format(
            episode_chunk=self._chunk(episode_index), episode_index=int(episode_index)
        )
        return self.split_root / rel

    def video_path(self, episode_index: int, camera: str = "ego") -> Path:
        if camera not in CAMERA_FEATURE:
            raise ValueError(f"unknown camera {camera!r}; expected one of {CAMERAS}")
        rel = self.video_path_tpl.format(
            episode_chunk=self._chunk(episode_index),
            video_key=CAMERA_FEATURE[camera],
            episode_index=int(episode_index),
        )
        return self.split_root / rel

    # ---------------------------------------------------------------- tables
    def load_table(self, episode_index: int) -> Dict[str, np.ndarray]:
        """Return the numeric columns of one episode as numpy arrays."""
        path = self.parquet_path(episode_index)
        table = pq.read_table(path)
        data: Dict[str, np.ndarray] = {}
        for name in table.column_names:
            column = table.column(name).combine_chunks()
            try:
                data[name] = np.asarray(column.to_numpy(zero_copy_only=False))
            except (TypeError, ValueError):
                data[name] = np.asarray(column.to_pylist())
        return data

    # ---------------------------------------------------------------- frames
    def frame_count(self, episode_index: int, camera: str = "ego") -> int:
        path = self.video_path(episode_index, camera)
        capture = cv2.VideoCapture(str(path))
        try:
            return int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        finally:
            capture.release()

    def read_frame(self, episode_index: int, frame_index: int, camera: str = "ego") -> np.ndarray:
        """Decode a single BGR frame by absolute frame index.

        ``CAP_PROP_POS_FRAMES`` seeking was verified against sequential decoding on
        USIM MP4s (identical frames for indices 0/100/300/500/566 of ep 1300), so the
        fast path is used.  ``sequential=True`` forces the exact-but-slow path and is
        used by the alignment audit.
        """
        cache_key = (int(episode_index), int(frame_index), camera)
        if cache_key in self._frame_cache:
            return self._frame_cache[cache_key].copy()
        frame = self._decode(episode_index, int(frame_index), camera)
        self._frame_cache[cache_key] = frame
        return frame.copy()

    def _decode(self, episode_index: int, frame_index: int, camera: str = "ego", sequential: bool = False) -> np.ndarray:
        path = self.video_path(episode_index, camera)
        capture = cv2.VideoCapture(str(path))
        try:
            if not capture.isOpened():
                raise RuntimeError(f"cannot open video: {path}")
            if not sequential:
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                ok, frame = capture.read()
                if ok and frame is not None:
                    return frame
            capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            current = 0
            ok, frame = capture.read()
            while ok and current < frame_index:
                ok, frame = capture.read()
                current += 1
            if not ok or frame is None:
                raise IndexError(f"frame {frame_index} not decodable in {path.name}")
            return frame
        finally:
            capture.release()

    def read_frames(self, episode_index: int, frame_indices: Sequence[int], camera: str = "ego") -> Dict[int, np.ndarray]:
        """Decode several frames from one episode, seeking in ascending order."""
        frames: Dict[int, np.ndarray] = {}
        path = self.video_path(episode_index, camera)
        capture = cv2.VideoCapture(str(path))
        try:
            if not capture.isOpened():
                raise RuntimeError(f"cannot open video: {path}")
            for index in sorted({int(v) for v in frame_indices}):
                capture.set(cv2.CAP_PROP_POS_FRAMES, index)
                ok, frame = capture.read()
                if not ok or frame is None:
                    raise IndexError(f"frame {index} not decodable in {path.name}")
                frames[index] = frame
        finally:
            capture.release()
        return frames

    def iter_frames(self, episode_index: int, camera: str = "ego", stride: int = 1) -> Iterator[tuple[int, np.ndarray]]:
        path = self.video_path(episode_index, camera)
        capture = cv2.VideoCapture(str(path))
        try:
            index = 0
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                if index % stride == 0:
                    yield index, frame
                index += 1
        finally:
            capture.release()

    # ----------------------------------------------------------- validation
    def align_check(self, episode_index: int, camera: str = "ego") -> Dict[str, object]:
        """Verify the frame<->row alignment assumptions for one episode.

        Checks performed:
        * decoded frame count equals ``meta/episodes.jsonl`` length;
        * ``frame_index`` is 0-based and contiguous;
        * Parquet row count equals video frame count.
        """
        episode = self.episode(episode_index)
        table = self.load_table(episode_index)
        rows = len(table["frame_index"])
        frame_index = np.asarray(table["frame_index"]).astype(np.int64)
        decoded = self.frame_count(episode_index, camera)
        report = {
            "episode_key": episode.key,
            "camera": camera,
            "meta_length": episode.length,
            "parquet_rows": rows,
            "decoded_frames": decoded,
            "frame_index_starts_at_zero": bool(rows and frame_index[0] == 0),
            "frame_index_contiguous": bool(rows and np.array_equal(frame_index, np.arange(rows))),
            "rows_match_meta": rows == episode.length,
            "rows_match_video": decoded == rows,
        }
        report["ok"] = bool(
            report["frame_index_starts_at_zero"]
            and report["frame_index_contiguous"]
            and report["rows_match_meta"]
            and report["rows_match_video"]
        )
        return report

    # ------------------------------------------------------------- helpers
    def task_text(self, episode_index: int) -> str:
        return self.episode(episode_index).task_text

    def timestamp_seconds(self, episode_index: int, frame_index: int) -> float:
        table = self.load_table(episode_index)
        timestamps = np.asarray(table["timestamp"], dtype=np.float64)
        return float(timestamps[int(frame_index)])


def iter_splits(dataset_root: str | Path, splits: Sequence[str] = ("train", "test")) -> Iterator[USIMReader]:
    for split in splits:
        yield USIMReader(dataset_root, split=split)


def resolve_dataset_root(default: str | Path = r"E:\code\UW-VLM\usim") -> Path:
    env = os.environ.get("USIM_ROOT")
    return Path(env) if env else Path(default)
