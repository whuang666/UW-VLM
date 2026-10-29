"""Validate human review declarations and source bindings; never grant a release."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.usim.prepare_acceptance_workpack import ATTESTATION, CRITERIA  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fact_key(fact: dict) -> tuple:
    return fact["predicate"], tuple(fact["arguments"])


def review_shape_errors(bundle: object) -> list[str]:
    """Reject malformed imported trees before any semantic field access."""
    errors = []
    if not isinstance(bundle, dict):
        return ["Review bundle must be an object"]
    if not isinstance(bundle.get("reviewer_identity"), str):
        errors.append("Reviewer identity must be text")
    for field in ("reviewer_is_human", "reviewer_independent_of_first_pass", "prior_answer_exposure"):
        if bundle.get(field) is not None and type(bundle[field]) is not bool:
            errors.append(f"{field} must be a boolean or null")
    worksheets = bundle.get("worksheets")
    if not isinstance(worksheets, list):
        return errors + ["Worksheets must be a list"]
    for index, worksheet in enumerate(worksheets):
        where = f"worksheet[{index}]"
        if not isinstance(worksheet, dict):
            errors.append(f"{where} must be an object")
            continue
        for field in ("episode_key", "source_annotation_sha256", "decision_reason", "signature_name", "signed_at", "attestation"):
            if not isinstance(worksheet.get(field), str):
                errors.append(f"{where}.{field} must be text")
        if worksheet.get("decision") not in (None, "accept_current_snapshot", "changes_required", "exclude"):
            errors.append(f"{where}.decision is unsupported")
        if type(worksheet.get("review_complete")) is not bool:
            errors.append(f"{where}.review_complete must be boolean")
        criteria = worksheet.get("criteria")
        if not isinstance(criteria, dict) or any(v is not None and type(v) is not bool for v in criteria.values()):
            errors.append(f"{where}.criteria must contain boolean/null values")
        frames = worksheet.get("frames")
        if not isinstance(frames, list):
            errors.append(f"{where}.frames must be a list")
        else:
            for frame in frames:
                if not isinstance(frame, dict):
                    errors.append(f"{where} contains a non-object frame")
                    continue
                if type(frame.get("source_frame")) is not int or not isinstance(frame.get("native_png_sha256"), str):
                    errors.append(f"{where} has malformed frame identity/hash")
                if not isinstance(frame.get("evidence_note"), str):
                    errors.append(f"{where} has a non-text frame evidence note")
                visibility = frame.get("visibility")
                if not isinstance(visibility, dict) or any(v is not None and type(v) is not bool for v in visibility.values()):
                    errors.append(f"{where} has malformed visibility")
                facts = frame.get("facts")
                if not isinstance(facts, list):
                    errors.append(f"{where} has non-list facts")
                    continue
                for fact in facts:
                    if (not isinstance(fact, dict) or not isinstance(fact.get("predicate"), str)
                            or not isinstance(fact.get("arguments"), list)
                            or any(not isinstance(v, str) for v in fact.get("arguments", []))
                            or "value" not in fact or (fact["value"] is not None and type(fact["value"]) is not bool)):
                        errors.append(f"{where} has malformed predicate data")
        transitions = worksheet.get("transitions")
        if not isinstance(transitions, list):
            errors.append(f"{where}.transitions must be a list")
        else:
            for transition in transitions:
                if (not isinstance(transition, dict) or type(transition.get("from_frame")) is not int
                        or type(transition.get("to_frame")) is not int
                        or not isinstance(transition.get("evidence_note"), str)
                        or transition.get("ego_decidable") is not None and type(transition["ego_decidable"]) is not bool):
                    errors.append(f"{where} has malformed transition data")
    return errors


def validate_bundle(packet: dict, bundle: dict, annotations: dict) -> dict:
    shape_errors = review_shape_errors(bundle)
    if shape_errors:
        return {"schema": "usim-human-review-validation/v1", "packet_version": packet["version"],
                "declared_reviewer_identity": "", "identity_independently_authenticated": False,
                "reviewer_declaration_valid": False, "prior_answer_exposure": None,
                "complete_review_declarations": 0, "accepted_current_snapshot_episodes": 0,
                "all_dispositions_complete": False, "all_current_snapshot_episodes_accepted": False,
                "candidate_rebuild_needed": False, "episodes": [], "errors": shape_errors,
                "release_eligible": False, "final_execution_protocol_frozen": False, "model_api_calls": 0}
    errors = []
    identity = bundle.get("reviewer_identity", "").strip()
    qualified = (bool(identity) and bundle.get("reviewer_is_human") is True
                 and bundle.get("reviewer_independent_of_first_pass") is True
                 and isinstance(bundle.get("prior_answer_exposure"), bool))
    if not qualified:
        errors.append("Human identity, independence or prior-answer-exposure declaration missing")
    reviews = bundle.get("worksheets", [])
    keys = [w.get("episode_key") for w in reviews]
    expected = [e["episode_key"] for e in packet["episodes"]]
    if len(keys) != len(set(keys)) or set(keys) != set(expected):
        errors.append("Worksheet episode coverage missing, duplicated or unknown")
    by_key = {w.get("episode_key"): w for w in reviews}
    outcomes = []
    for episode in packet["episodes"]:
        key = episode["episode_key"]
        worksheet = by_key.get(key, {})
        problems = []
        annotation = annotations[key]
        decision = worksheet.get("decision")
        if worksheet.get("source_annotation_sha256") != episode["source_annotation_sha256"]:
            problems.append("Annotation hash binding differs")
        if worksheet.get("review_complete") is not True:
            problems.append("Review incomplete")
        if decision not in ("accept_current_snapshot", "changes_required", "exclude"):
            problems.append("Decision missing or unsupported")
        if not worksheet.get("decision_reason", "").strip():
            problems.append("Decision reason missing")
        if not identity or worksheet.get("signature_name", "").strip() != identity or worksheet.get("attestation") != ATTESTATION:
            problems.append("Named reviewer signature/attestation missing or inconsistent")
        try:
            signed = datetime.fromisoformat(worksheet.get("signed_at", "").replace("Z", "+00:00"))
            if signed.tzinfo is None:
                raise ValueError("Missing timezone")
        except (TypeError, ValueError):
            problems.append("Valid signed_at with timezone missing")
        frames = worksheet.get("frames", [])
        frame_ids = [f.get("source_frame") for f in frames]
        wanted_frames = [f["source_frame"] for f in episode["frames"]]
        if frame_ids != wanted_frames:
            problems.append("Frame order/identity missing, duplicated or changed")
        objects = {obj["object_id"] for obj in episode["objects"]}
        scope = {(r[0], tuple(r[1:])) for r in episode["scope"]}
        annotation_frames = {f["frame_index"]: f for f in annotation["frames"]}
        for review_frame, bound in zip(frames, episode["frames"]):
            if review_frame.get("native_png_sha256") != bound["sha256"]:
                problems.append(f"PNG hash differs at frame {bound['source_frame']}")
            values = review_frame.get("facts", [])
            try:
                fact_keys = [fact_key(f) for f in values]
            except (TypeError, KeyError):
                fact_keys = []
            if len(set(fact_keys)) != len(fact_keys) or set(fact_keys) != scope:
                problems.append(f"Incomplete or duplicate predicate scope at frame {bound['source_frame']}")
            if set(review_frame.get("visibility", {})) != objects:
                problems.append(f"Visibility object scope differs at frame {bound['source_frame']}")
            if decision == "accept_current_snapshot":
                proposed = {fact_key(f): f["value"] for f in annotation_frames[bound["source_frame"]]["facts"]}
                if any(type(f.get("value")) is not bool for f in values):
                    problems.append(f"Unresolved/nonboolean fact at frame {bound['source_frame']}")
                elif {fact_key(f): f["value"] for f in values} != proposed:
                    problems.append(f"Own facts disagree with current snapshot at frame {bound['source_frame']}; adjudication/new version required")
                if not all(value is True for value in review_frame.get("visibility", {}).values()):
                    problems.append(f"Object visibility unconfirmed at frame {bound['source_frame']}")
                if not review_frame.get("evidence_note", "").strip():
                    problems.append(f"Own image evidence missing at frame {bound['source_frame']}")
        transitions = worksheet.get("transitions", [])
        expected_pairs = list(zip(wanted_frames, wanted_frames[1:]))
        if [(t.get("from_frame"), t.get("to_frame")) for t in transitions] != expected_pairs:
            problems.append("Transition frame bindings missing or changed")
        if decision == "accept_current_snapshot":
            if set(worksheet.get("criteria", {})) != set(CRITERIA) or not all(v is True for v in worksheet["criteria"].values()):
                problems.append("Four acceptance criteria not all confirmed")
            if any(t.get("ego_decidable") is not True or not t.get("evidence_note", "").strip() for t in transitions):
                problems.append("A transition remains unconfirmed or lacks image evidence")
            if episode["episode"] == 1650 and 0 in wanted_frames:
                problems.append("Known 1650@f0 visibility blocker remains: separate adjudication/source revision required")
        complete = qualified and not problems
        outcomes.append({"episode_key": key, "decision": decision, "valid_complete_review_declaration": complete,
                         "accepted_current_snapshot": complete and decision == "accept_current_snapshot", "errors": problems})
    reviewed = sum(o["valid_complete_review_declaration"] for o in outcomes)
    accepted = sum(o["accepted_current_snapshot"] for o in outcomes)
    disposition_complete = reviewed == len(expected) and not errors
    return {"schema": "usim-human-review-validation/v1", "packet_version": packet["version"],
            "declared_reviewer_identity": identity, "identity_independently_authenticated": False,
            "reviewer_declaration_valid": qualified, "prior_answer_exposure": bundle.get("prior_answer_exposure"),
            "complete_review_declarations": reviewed, "accepted_current_snapshot_episodes": accepted,
            "all_dispositions_complete": disposition_complete,
            "all_current_snapshot_episodes_accepted": disposition_complete and accepted == len(expected),
            "candidate_rebuild_needed": any(o["decision"] in ("changes_required", "exclude") for o in outcomes),
            "episodes": outcomes, "errors": errors, "release_eligible": False,
            "final_execution_protocol_frozen": False, "model_api_calls": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    default = ROOT / "data/usim_enact/_review/test_reserve/acceptance_workpack_20261029_v2"
    parser.add_argument("--packet-dir", type=Path, default=default)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    packet_dir = args.packet_dir.resolve()
    manifest_path = packet_dir / "packet_manifest.json"
    packet = json.loads(manifest_path.read_text(encoding="utf-8"))
    reviews_path = args.reviews or packet_dir / "review_templates.json"
    reviews = json.loads(reviews_path.read_text(encoding="utf-8"))
    if (not isinstance(reviews, dict) or reviews.get("schema") != "usim-human-review-bundle/v1"
            or reviews.get("packet_manifest_sha256") != sha(manifest_path)
            or reviews.get("packet_version") != packet["version"]):
        raise ValueError("Reviews belong to a different packet version/hash")
    snapshot_path = WORKSPACE / packet["candidate_snapshot_path"]
    if sha(snapshot_path) != packet["candidate_snapshot_sha256"]:
        raise ValueError("Candidate snapshot changed")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    dataset = WORKSPACE / packet["dataset_root"]
    for name, digest in snapshot["files"].items():
        path = (dataset / name).resolve()
        if not path.is_relative_to(dataset.resolve()) or sha(path) != digest:
            raise ValueError(f"Candidate input differs: {name}")
    annotations = {}
    for episode in packet["episodes"]:
        path = WORKSPACE / episode["source_annotation_path"]
        if sha(path) != episode["source_annotation_sha256"]:
            raise ValueError("Source annotation changed")
        annotations[episode["episode_key"]] = json.loads(path.read_text(encoding="utf-8"))
        for frame in episode["frames"]:
            for asset in [frame] + frame["context"]:
                image = (packet_dir / asset["path"]).resolve()
                if not image.is_relative_to(packet_dir) or sha(image) != asset["sha256"]:
                    raise ValueError("Packet image/source binding changed")
    result = validate_bundle(packet, reviews, annotations)
    result.update({"packet_manifest_sha256": sha(manifest_path), "review_bundle_sha256": sha(reviews_path),
                   "candidate_snapshot_sha256": sha(snapshot_path)})
    output = args.out.resolve()
    if output.exists() or output in (reviews_path.resolve(), manifest_path):
        raise ValueError("Use a new validation report; do not overwrite review records")
    allowed = [(ROOT / "docs/WBW/evidence").resolve(), packet_dir]
    if not any(output.is_relative_to(parent) for parent in allowed):
        raise ValueError("Validation output must stay in the review packet or evidence directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("complete_review_declarations", "accepted_current_snapshot_episodes",
                     "all_dispositions_complete", "candidate_rebuild_needed", "release_eligible")}, ensure_ascii=False))
    raise SystemExit(0 if result["all_dispositions_complete"] else 2)


if __name__ == "__main__":
    main()
