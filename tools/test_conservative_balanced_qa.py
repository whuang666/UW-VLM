"""Boundary checks for the new balanced presentation builder; never call a model."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ENACT"))
from scripts.usim import build_conservative_balanced_qa as builder


def inverse_prompt() -> str:
    return "Header example [2, 3, 1]\n## Shuffled Actions\n[Action 1] first.\n[Action 2] second.\n[Action 3] third.\n\nNow please provide your answer.\n"


class BalancedPresentationTests(unittest.TestCase):
    def test_three_cycle_uses_inverse_mapping_for_forward_slots(self):
        self.assertEqual(builder.display_frames("forward", ["0", "10", "20", "30"], [2, 3, 1]),
                         ["0", "30", "10", "20"])

    def test_inverse_images_remain_chronological_for_three_cycle(self):
        self.assertEqual(builder.display_frames("inverse", ["0", "10", "20", "30"], [2, 3, 1]),
                         ["0", "10", "20", "30"])

    def test_inverse_relabels_action_content_and_preserves_surrounding_prompt(self):
        old = inverse_prompt()
        new = builder.remap_inverse(old, [1, 2, 3], [2, 3, 1])
        self.assertIn("[Action 1] third.\n[Action 2] first.\n[Action 3] second.", new)
        self.assertEqual(builder.chronological_actions(new, [2, 3, 1]), ["first.", "second.", "third."])
        self.assertEqual(builder.ACTION_LINE.sub("", old), builder.ACTION_LINE.sub("", new))

    def test_inverse_mapping_roundtrip_from_already_shuffled_input(self):
        old = builder.remap_inverse(inverse_prompt(), [1, 2, 3], [3, 1, 2])
        new = builder.remap_inverse(old, [3, 1, 2], [2, 1, 3])
        self.assertEqual(builder.chronological_actions(new, [2, 1, 3]), ["first.", "second.", "third."])

    def test_invalid_or_duplicate_permutation_labels_rejected(self):
        for answer in ([True, 2], [0, 1], [1, 1], [1], [1, 2, 3]):
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                builder.permutation(answer, 2)

    def test_missing_duplicate_or_repeated_inverse_action_blocks_rejected(self):
        base = inverse_prompt()
        for question in (base.replace("[Action 3] third.\n", ""),
                         base.replace("[Action 3]", "[Action 2]"),
                         base + "\n## Shuffled Actions\n"):
            with self.subTest(question=question), self.assertRaises(ValueError):
                builder.chronological_actions(question, [1, 2, 3])

    def test_nonidentity_only_l3_distribution_is_rejected(self):
        rows = [{"type": "forward_L3", "gt_answer": [2, 1]} for _ in range(8)]
        with self.assertRaises(ValueError):
            builder.balance_report(rows)

    def test_two_l4_questions_keep_finite_sample_half_constant_bound(self):
        rows = [{"type": "forward_L4", "gt_answer": p} for p in ([1, 2, 3], [3, 1, 2])]
        stats = builder.balance_report(rows)["direction_length"]["cells"]["forward_L4"]
        self.assertEqual(stats["minimum_possible_best_constant_EM"], "1/2")
        self.assertEqual(stats["uniform_random_EM"], "1/6")
        self.assertEqual(stats["EM_step_percentage_points"], "50")

    def test_dataset_output_cannot_overwrite_frozen_or_existing_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(builder, "BASE", root):
                with self.assertRaises(ValueError):
                    builder.fresh_dataset(root / "usim-enact-v0.2")
                existing = root / (builder.OUTPUT_PREFIX + "existing")
                existing.mkdir()
                with self.assertRaises(FileExistsError):
                    builder.fresh_dataset(existing)
                fresh = root / (builder.OUTPUT_PREFIX + "new")
                self.assertEqual(builder.fresh_dataset(fresh), fresh.resolve())
                self.assertFalse(fresh.exists())

    def test_rendering_preserves_source_pixels_outside_label_region(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "raw.png"
            Image.new("RGB", (320, 240), (31, 57, 83)).save(source)
            font = builder.resolve_font_path()
            self.assertIsNotNone(font)
            result, box = builder.rendered(source, "Next State 3", Path(font))
            changed = np.any(np.asarray(result) != np.asarray(Image.open(source)), axis=2)
            self.assertTrue(changed.any())
            changed[box[1]:box[3], box[0]:box[2]] = False
            self.assertFalse(changed.any())

    def test_binding_verifier_rejects_wrong_source_pixels_and_false_visibility(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            key = "synthetic_episode"
            frames = ["0", "10", "20"]
            source_dir = root / "replayed_activities" / key / builder.SENSOR_NAME
            source_dir.mkdir(parents=True)
            for i, frame in enumerate(frames):
                Image.new("RGB", (320, 240), (30 + i * 50, 70, 90)).save(source_dir / f"{int(frame):05d}.png")
            annotation = {"episode_key": key, "source_split": "train", "episode_index": 0,
                          "task_text": "synthetic", "objects": [{"object_id": "target", "category": "object"}],
                          "relations": [["InGripper", "target"]], "frames": [
                              {"frame_index": int(frame), "facts": [{"predicate": "InGripper", "arguments": ["target"], "value": i == 2}],
                               "visibility": [{"object_id": "target", "value": True}]}
                              for i, frame in enumerate(frames)]}
            annotation_path = root / "annotations/episodes" / f"{key}.json"
            annotation_path.parent.mkdir(parents=True)
            annotation_path.write_text(json.dumps(annotation), encoding="utf-8")
            parent = {"id": "parent", "task_name": key, "key_frame_ids": frames, "question": "unchanged"}
            record = {"id": "new", "parent_diagnostic_id": "parent", "task_name": key,
                      "key_frame_ids": frames, "question": "unchanged", "gt_answer": [2, 1], "images": []}
            font = Path(builder.resolve_font_path())
            for slot, frame in enumerate(["0", "20", "10"]):
                relative = f"slot_{slot}.png"
                image, _ = builder.rendered(source_dir / f"{int(frame):05d}.png", "Current State" if slot == 0 else f"Next State {slot}", font)
                image.save(root / relative)
                record["images"].append(relative)
            parents = {"parent": parent}
            planned = {"parent": {"direction": "forward", "proposed_gt": [2, 1]}}
            self.assertEqual(builder.verify_bindings(root, [record], parents, planned, font)["presented_images"], 3)
            original = (root / "slot_1.png").read_bytes()
            wrong, _ = builder.rendered(source_dir / "00010.png", "Next State 1", font)
            wrong.save(root / "slot_1.png")
            with self.assertRaises(ValueError):
                builder.verify_bindings(root, [record], parents, planned, font)
            (root / "slot_1.png").write_bytes(original)
            annotation["frames"][1]["visibility"][0]["value"] = False
            annotation_path.write_text(json.dumps(annotation), encoding="utf-8")
            with self.assertRaises(ValueError):
                builder.verify_bindings(root, [record], parents, planned, font)


if __name__ == "__main__":
    unittest.main()
