"""Acceptance declarations must stay bound to reviewed source facts and frames."""

import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ENACT"))
from scripts.usim.validate_acceptance_reviews import validate_bundle
from scripts.usim.prepare_acceptance_workpack import ATTESTATION, CRITERIA


def example(episode=1078):
    key = f"usim_train_episode_{episode:06d}"
    annotation = {"frames": [{"frame_index": i, "facts": [{"predicate": "InGripper", "arguments": ["target"], "value": i == 20}]}
                              for i in (0, 10, 20)]}
    item = {"episode_key": key, "episode": episode, "source_annotation_sha256": "sourcehash",
            "objects": [{"object_id": "target"}], "scope": [["InGripper", "target"]],
            "frames": [{"source_frame": i, "sha256": f"png{i}"} for i in (0, 10, 20)]}
    packet = {"version": "synthetic_test", "episodes": [item]}
    worksheet = {"episode_key": key, "source_annotation_sha256": "sourcehash", "decision": "accept_current_snapshot",
                 "review_complete": True, "decision_reason": "Independent image evidence reviewed.",
                 "signature_name": "Human Reviewer", "signed_at": "2026-10-29T18:00:00+08:00", "attestation": ATTESTATION,
                 "criteria": {k: True for k in CRITERIA},
                 "frames": [{"source_frame": f["frame_index"], "native_png_sha256": f"png{f['frame_index']}",
                             "facts": copy.deepcopy(f["facts"]), "visibility": {"target": True}, "evidence_note": "Observed in native image and context."}
                            for f in annotation["frames"]],
                 "transitions": [{"from_frame": a, "to_frame": b, "ego_decidable": True, "evidence_note": "Visible change recorded."}
                                 for a, b in ((0, 10), (10, 20))]}
    bundle = {"reviewer_identity": "Human Reviewer", "reviewer_is_human": True,
              "reviewer_independent_of_first_pass": True, "prior_answer_exposure": False, "worksheets": [worksheet]}
    return packet, bundle, {key: annotation}


class AcceptanceReviewTests(unittest.TestCase):
    def test_complete_matching_review_never_grants_release(self):
        result = validate_bundle(*example())
        self.assertTrue(result["all_current_snapshot_episodes_accepted"])
        self.assertFalse(result["release_eligible"])
        self.assertFalse(result["identity_independently_authenticated"])

    def test_nonhuman_or_same_first_annotator_cannot_pass(self):
        for name in ("reviewer_is_human", "reviewer_independent_of_first_pass"):
            p, b, a = example()
            b[name] = False
            self.assertFalse(validate_bundle(p, b, a)["all_dispositions_complete"])

    def test_unknown_fact_cannot_be_converted_to_false(self):
        p, b, a = example()
        b["worksheets"][0]["frames"][0]["facts"][0]["value"] = None
        self.assertFalse(validate_bundle(p, b, a)["all_current_snapshot_episodes_accepted"])

    def test_wrong_source_frame_or_png_hash_rejected(self):
        for field in ("source_frame", "native_png_sha256"):
            p, b, a = example()
            b["worksheets"][0]["frames"][0][field] = "other"
            self.assertFalse(validate_bundle(p, b, a)["all_dispositions_complete"])

    def test_disagreement_requires_adjudication_or_new_version(self):
        p, b, a = example()
        b["worksheets"][0]["frames"][0]["facts"][0]["value"] = True
        self.assertFalse(validate_bundle(p, b, a)["all_current_snapshot_episodes_accepted"])

    def test_false_visibility_pending_transition_or_missing_evidence_rejected(self):
        for change in ("visibility", "transition", "evidence"):
            p, b, a = example()
            w = b["worksheets"][0]
            if change == "visibility":
                w["frames"][0]["visibility"]["target"] = False
            elif change == "transition":
                w["transitions"][0]["ego_decidable"] = None
            else:
                w["frames"][0]["evidence_note"] = ""
            self.assertFalse(validate_bundle(p, b, a)["all_dispositions_complete"])

    def test_duplicate_or_missing_worksheet_rejected(self):
        p, b, a = example()
        b["worksheets"] *= 2
        self.assertFalse(validate_bundle(p, b, a)["all_dispositions_complete"])
        b["worksheets"] = []
        self.assertFalse(validate_bundle(p, b, a)["all_dispositions_complete"])

    def test_missing_or_naive_signing_timestamp_rejected(self):
        for value in ("", "2026-10-29T18:00:00"):
            p, b, a = example()
            b["worksheets"][0]["signed_at"] = value
            self.assertFalse(validate_bundle(p, b, a)["all_dispositions_complete"])

    def test_exclusion_is_a_complete_disposition_but_requires_rebuild(self):
        p, b, a = example()
        b["worksheets"][0]["decision"] = "exclude"
        b["worksheets"][0]["frames"][0]["facts"][0]["value"] = None
        result = validate_bundle(p, b, a)
        self.assertTrue(result["all_dispositions_complete"])
        self.assertEqual(result["accepted_current_snapshot_episodes"], 0)
        self.assertTrue(result["candidate_rebuild_needed"])
        self.assertFalse(result["release_eligible"])

    def test_known_1650_frame0_issue_cannot_be_signed_away(self):
        result = validate_bundle(*example(1650))
        self.assertFalse(result["all_dispositions_complete"])
        self.assertTrue(any("1650@f0" in text for text in result["episodes"][0]["errors"]))

    def test_null_nested_lists_return_rejection_instead_of_crashing(self):
        for field in ("frames", "transitions", "criteria"):
            p, b, a = example()
            b["worksheets"][0][field] = None
            result = validate_bundle(p, b, a)
            self.assertFalse(result["all_dispositions_complete"])
            self.assertEqual(result["accepted_current_snapshot_episodes"], 0)
            self.assertTrue(result["errors"])

    def test_string_booleans_and_integer_completion_are_rejected(self):
        for change in ("fact", "visibility", "completion"):
            p, b, a = example()
            if change == "fact":
                b["worksheets"][0]["frames"][0]["facts"][0]["value"] = "false"
            elif change == "visibility":
                b["worksheets"][0]["frames"][0]["visibility"]["target"] = "true"
            else:
                b["worksheets"][0]["review_complete"] = 1
            self.assertFalse(validate_bundle(p, b, a)["all_dispositions_complete"])

    def test_malformed_top_level_identity_and_worksheet_type_rejected(self):
        for change in ("identity", "worksheets", "worksheet"):
            p, b, a = example()
            if change == "identity":
                b["reviewer_identity"] = None
            elif change == "worksheets":
                b["worksheets"] = None
            else:
                b["worksheets"] = [None]
            self.assertFalse(validate_bundle(p, b, a)["all_dispositions_complete"])


if __name__ == "__main__":
    unittest.main()
