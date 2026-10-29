"""Synthetic signed-review routing; no test-reserve ground truth is fabricated."""

from __future__ import annotations

from contextlib import redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ENACT"))
from enact.adapters.usim_annotations import USIMEpisodeAnnotation, compile_scene_graph
from scripts.usim.prepare_acceptance_workpack import ATTESTATION, CRITERIA
from scripts.usim import advance_signed_candidates as flow


def fixture(workspace: Path):
    """Ten fictional chains: 8 pick/2 transfer; last pick is the blocked 1650."""
    dataset, packet_dir = workspace / "synthetic_dataset", workspace / "synthetic_packet"
    dataset.mkdir()
    packet_dir.mkdir()
    (packet_dir / "images").mkdir()
    episodes, entries, worksheets, records = [], [], [], []
    for index in range(10):
        transfer = index in (8, 9)
        number = 1650 if index == 7 else index + 1
        key = f"synthetic_episode_{number:06d}"
        frames = [0, 30, 60, 90] if transfer else [0, 30, 60]
        target = "red_cylinder" if transfer else "blue_cylinder"
        objects = [{"object_id": "robot", "category": "agent"}, {"object_id": target, "category": "cylinder"}]
        if transfer:
            objects.append({"object_id": "green_box", "category": "box"})
        relations = [["InGripper", target], ["NextTo", "robot", target]]
        relations.append(["NearBox", "robot", "green_box"] if transfer else ["OnSeabed", target])
        raw_frames = []
        for position, frame in enumerate(frames):
            values = [position >= 2, position == 1, position == 3 if transfer else True]
            raw_frames.append({"frame_index": frame, "facts": [
                {"predicate": relation[0], "arguments": relation[1:], "value": value}
                for relation, value in zip(relations, values)],
                "visibility": [{"object_id": o["object_id"], "value": True} for o in objects]})
        annotation = {"episode_key": key, "episode_index": number, "source_split": "train",
                      "task_text": "synthetic transfer" if transfer else "synthetic pick", "objects": objects,
                      "relations": relations, "frames": raw_frames, "annotation_status": "synthetic_test_only"}
        annotation_path = dataset / "annotations/episodes" / f"{key}.json"
        flow.save(annotation_path, annotation)
        graph = compile_scene_graph(USIMEpisodeAnnotation.from_dict(annotation))
        images, packet_frames = {}, []
        for branch, graph_name in (("replayed_activities", "scene_graph_0.json"), ("segmented_activities", "segmented_scene_graph_0.json")):
            folder = dataset / branch / key
            flow.save(folder / graph_name, graph)
            for position, frame in enumerate(frames):
                image = folder / "external_sensor1" / f"{frame:05d}.png"
                image.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (320, 240), (30 + position * 30, 70 + index, 90)).save(image)
                if branch == "replayed_activities":
                    relative = image.relative_to(dataset).as_posix()
                    images[str(frame)] = {"path": relative, "width": 320, "height": 240, "sha256": flow.sha(image)}
                    copied = packet_dir / "images" / f"{key}_{frame}.png"
                    copied.write_bytes(image.read_bytes())
                    packet_frames.append({"source_frame": frame, "path": copied.relative_to(packet_dir).as_posix(),
                                          "sha256": flow.sha(copied), "context": []})
        episode = {"episode_key": key, "episode": number, "family": "transfer" if transfer else "pick",
                   "objects": objects, "scope": relations, "frames": packet_frames,
                   "source_annotation_path": annotation_path.relative_to(workspace).as_posix(),
                   "source_annotation_sha256": flow.sha(annotation_path)}
        episodes.append(episode)
        entries.append({"episode_key": key, "episode_index": number, "task_text": annotation["task_text"],
                        "key_frame_ids": [str(f) for f in frames], "frames": images, "valid_transitions": len(frames) - 1})
        worksheets.append({"episode_key": key, "source_annotation_sha256": flow.sha(annotation_path),
                           "frames": [{"source_frame": f["frame_index"], "native_png_sha256": images[str(f["frame_index"])]["sha256"],
                                       "visibility": {o["object_id"]: True for o in objects}, "facts": copy.deepcopy(f["facts"]),
                                       "evidence_note": "SYNTHETIC UNIT FIXTURE; not an image judgment"} for f in raw_frames],
                           "transitions": [{"from_frame": a, "to_frame": b, "ego_decidable": True, "evidence_note": "SYNTHETIC UNIT FIXTURE"}
                                           for a, b in zip(frames, frames[1:])],
                           "criteria": {c: True for c in CRITERIA}, "decision": "exclude" if number == 1650 else "accept_current_snapshot",
                           "decision_reason": "SYNTHETIC UNIT FIXTURE", "review_complete": True,
                           "signature_name": "FICTIONAL_UNIT_TEST_REVIEWER", "signed_at": "2026-10-29T18:00:00+08:00", "attestation": ATTESTATION})
        actions = [f"The robot becomes in position for the pre-grasp approach beside the {target.replace('_', ' ')}.",
                   f"The {target.replace('_', ' ')} becomes grasped by the robot. The robot is no longer in position for the pre-grasp approach beside the {target.replace('_', ' ')}."]
        if transfer:
            actions.append("The robot becomes near the green box.")
        for direction in ("forward", "inverse"):
            question = "Synthetic fixture only\n\n## " + ("Actions in Order" if direction == "forward" else "Shuffled Actions")
            question += "\n" + "\n".join(f"[Action {i+1}] {text}" for i, text in enumerate(actions)) + "\n\nNow please provide your answer.\n"
            records.append({"id": f"fixture_{key}_{direction}", "type": f"{direction}_world_modeling_{len(frames)}_steps",
                            "task_name": key, "key_frame_ids": list(images), "images": [images[f]["path"] for f in images],
                            "question": question, "options": [], "gt_answer": list(range(1, len(frames)))})
    flow.save(dataset / "manifest.json", {"protocol_version": "synthetic_fixture_only", "episodes": entries})
    qa = dataset / "qa.jsonl"
    qa.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    snapshot = {"qa": "qa.jsonl", "qa_sha256": flow.sha(qa), "files": {p.relative_to(dataset).as_posix(): flow.sha(p)
                for p in dataset.rglob('*') if p.is_file()}}
    snapshot["payload_sha256"] = hashlib.sha256(flow.canonical(snapshot)).hexdigest()
    flow.save(dataset / "candidate_input_snapshot.json", snapshot)
    packet = {"schema": "usim-human-review-packet/v1", "version": "synthetic_packet_only",
              "candidate_qa_version": "synthetic_fixture_only", "episodes": episodes,
              "candidate_snapshot_path": (dataset / "candidate_input_snapshot.json").relative_to(workspace).as_posix(),
              "candidate_snapshot_sha256": flow.sha(dataset / "candidate_input_snapshot.json"),
              "dataset_root": dataset.relative_to(workspace).as_posix()}
    flow.save(packet_dir / "packet_manifest.json", packet)
    bundle = {"schema": "usim-human-review-bundle/v1", "packet_version": packet["version"],
              "packet_manifest_sha256": flow.sha(packet_dir / "packet_manifest.json"),
              "reviewer_identity": "FICTIONAL_UNIT_TEST_REVIEWER", "reviewer_is_human": True,
              "reviewer_independent_of_first_pass": True, "prior_answer_exposure": False, "worksheets": worksheets}
    reviews = workspace / "synthetic_signed_fixture.json"
    flow.save(reviews, bundle)
    return packet_dir, reviews, bundle


class SignedFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        self.packet, self.reviews, self.bundle = fixture(self.workspace)

    def tearDown(self):
        self.temp.cleanup()

    def context(self):
        flow.save(self.reviews, self.bundle)
        return flow.load_context(self.packet, self.reviews, self.workspace)

    def plan(self):
        return flow.selection_plan(self.context(), "synthetic-reviewed-v1", 20261029)

    def test_nine_accepted_excluding_blocked_one_gives_18_and_23_over54(self):
        plan = self.plan()
        self.assertTrue(plan["ready_for_qa_rebuild"])
        self.assertEqual((plan["episode_count"], plan["question_count"]), (9, 18))
        self.assertEqual(plan["uniform_random_EM_exact"], "23/54")
        self.assertFalse(plan["release_eligible"])
        self.assertFalse(plan["identity_independently_authenticated"])

    def test_count_is_derived_and_not_hardcoded_to_18(self):
        self.bundle["worksheets"][0]["decision"] = "exclude"
        plan = self.plan()
        self.assertEqual((plan["episode_count"], plan["question_count"]), (8, 16))
        self.assertEqual(plan["uniform_random_EM_exact"], "5/12")

    def test_unsigned_or_nonhuman_bundle_emits_no_accepted_selection(self):
        self.bundle["reviewer_is_human"] = False
        plan = self.plan()
        self.assertFalse(plan["ready_for_qa_rebuild"])
        self.assertEqual(plan["selected"], [])
        self.assertIsNone(plan["uniform_random_EM_exact"])

    def test_malformed_null_worksheets_stays_blocked_without_crashing(self):
        self.bundle["worksheets"] = None
        plan = self.plan()
        self.assertFalse(plan["ready_for_qa_rebuild"])
        self.assertEqual(plan["selected"], [])
        self.assertIsNone(plan["uniform_random_EM_exact"])

    def test_pending_frame_or_scope_change_blocks_automatic_rebuild(self):
        self.bundle["worksheets"][0]["decision"] = "changes_required"
        plan = self.plan()
        self.assertTrue(plan["all_dispositions_complete"])
        self.assertFalse(plan["ready_for_qa_rebuild"])
        self.assertEqual(len(plan["changes_required"]), 1)

    def test_empty_selected_set_is_blocked_with_no_false_zero_chance(self):
        for worksheet in self.bundle["worksheets"]:
            worksheet["decision"] = "exclude"
        plan = self.plan()
        self.assertFalse(plan["ready_for_qa_rebuild"])
        self.assertEqual(plan["blocked_reason"], "no_accepted_episode")
        self.assertIsNone(plan["uniform_random_EM"])

    def test_wrong_packet_hash_is_rejected(self):
        self.bundle["packet_manifest_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            self.context()

    def test_mutated_candidate_image_is_rejected(self):
        target = next((self.workspace / "synthetic_dataset/replayed_activities").rglob('*.png'))
        target.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.context()

    def test_copy_rechecks_reviewed_hash_after_context_loading(self):
        context = self.context()
        plan = flow.selection_plan(context, "synthetic-reviewed-v1", 20261029)
        key = plan["selected"][0]["episode_key"]
        target = next((context.dataset / "replayed_activities" / key).rglob('*.png'))
        Image.new("RGB", (320, 240), "red").save(target)
        evidence = self.workspace / "copy_changed_evidence"
        evidence.mkdir()
        with self.assertRaises(ValueError):
            flow.build_selected_qa(context, plan, self.workspace / "copy_changed_dataset", evidence)

    def test_balancing_is_independent_of_parent_row_order(self):
        context = self.context()
        self.assertEqual(flow.balanced_mapping(context.qa_records, "synthetic-v1", 20261029),
                         flow.balanced_mapping(list(reversed(context.qa_records)), "synthetic-v1", 20261029))

    def test_new_qa_rebuild_reaudits_images_oracle_uniqueness_and_text(self):
        out, dataset = self.workspace / "evidence", self.workspace / "rebuilt"
        with redirect_stdout(io.StringIO()):
            result = flow.run_flow(self.packet, self.reviews, out, "synthetic-reviewed-v1", 20261029, dataset, self.workspace)
        self.assertTrue(result["qa_built"])
        self.assertEqual(result["planned_questions"], 18)
        gates = flow.read(out / "rebuild_gates.json")
        self.assertEqual(gates["uniform_random_EM_exact"], "23/54")
        self.assertEqual(gates["best_direction_length_constant_EM"], "5/9")
        self.assertEqual(gates["bound_presented_images"], 58)
        self.assertTrue(all(gates["oracle"][key] == 1 for key in ("EM", "TA", "PA_item_mean", "PA_transition_micro")))
        self.assertFalse(gates["release_eligible"])
        audit = flow.read(out / "permutation_audit.json")
        self.assertEqual(sum(r["permutations_total"] for r in audit["questions"]), 52)
        snapshot = flow.read(dataset / "candidate_input_snapshot.json")
        self.assertNotIn("candidate_input_snapshot.json", snapshot["files"])
        self.assertTrue(all(flow.sha(dataset / path) == digest for path, digest in snapshot["files"].items()))
        self.assertEqual(flow.sha(self.reviews), flow.sha(out / "review_bundle.json"))

    def test_existing_output_and_blocked_build_never_overwrite_data(self):
        out, dataset = self.workspace / "evidence", self.workspace / "rebuilt"
        out.mkdir()
        with self.assertRaises(FileExistsError):
            flow.run_flow(self.packet, self.reviews, out, "synthetic-v1", 1, dataset, self.workspace)
        self.bundle["reviewer_is_human"] = False
        flow.save(self.reviews, self.bundle)
        blocked = self.workspace / "blocked_evidence"
        result = flow.run_flow(self.packet, self.reviews, blocked, "synthetic-v1", 1, dataset, self.workspace)
        self.assertFalse(result["qa_built"])
        self.assertFalse(dataset.exists())

    def test_parent_qa_version_cannot_be_reused(self):
        context = self.context()
        with self.assertRaises(ValueError):
            flow.selection_plan(context, context.packet["candidate_qa_version"], 1)

    def test_failed_rebuild_writes_blocked_receipt_not_success(self):
        from unittest.mock import patch
        out, dataset = self.workspace / "failed_evidence", self.workspace / "failed_rebuild"
        with patch.object(flow, "build_selected_qa", side_effect=ValueError("synthetic gate failure")):
            with self.assertRaises(ValueError):
                flow.run_flow(self.packet, self.reviews, out, "synthetic-v1", 1, dataset, self.workspace)
        result = flow.read(out / "summary.json")
        self.assertFalse(result["qa_built"])
        self.assertFalse(result["release_eligible"])
        self.assertEqual(result["blocked_reason"], "rebuild_or_mechanical_gate_failed")


if __name__ == "__main__":
    unittest.main()
