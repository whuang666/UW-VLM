"""Turn completed review declarations into a selection and optional rebuilt QA.

No real model requests are made. Typed signatures are checked as declarations,
not cryptographically authenticated identities. All outputs remain candidates
until the final execution protocol and external identity checks are completed.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import itertools
import json
from pathlib import Path
import re
import shutil
import socket
import sys

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.usim import audit_qa_validity, evaluate, text_prior_baseline  # noqa: E402
from scripts.usim.build_conservative_balanced_qa import (  # noqa: E402
    balance_report, canonical, display_frames, remap_inverse, rendered,
    resolve_font_path, verify_bindings,
)
from scripts.usim.validate_acceptance_reviews import validate_bundle  # noqa: E402

ALGORITHM = "signed-review-balanced-presentation-v1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def workspace_path(workspace: Path, relative: str) -> Path:
    path = (workspace / relative).resolve()
    if not path.is_relative_to(workspace.resolve()):
        raise ValueError("Source path escaped the workspace")
    return path


@dataclass
class ReviewContext:
    workspace: Path
    packet_dir: Path
    packet: dict
    bundle: dict
    reviews_path: Path
    dataset: Path
    snapshot: dict
    annotations: dict
    validation: dict
    qa_records: list[dict]


def load_context(packet_dir: Path, reviews_path: Path, workspace: Path = WORKSPACE) -> ReviewContext:
    """Re-read all source bindings rather than trusting a saved validation flag."""
    packet_dir, workspace = packet_dir.resolve(), workspace.resolve()
    packet_path = packet_dir / "packet_manifest.json"
    packet, bundle = read(packet_path), read(reviews_path)
    if (not isinstance(bundle, dict) or bundle.get("schema") != "usim-human-review-bundle/v1"
            or bundle.get("packet_version") != packet["version"]
            or bundle.get("packet_manifest_sha256") != sha(packet_path)):
        raise ValueError("Review bundle does not bind this packet/version/hash")
    snapshot_path = workspace_path(workspace, packet["candidate_snapshot_path"])
    if sha(snapshot_path) != packet["candidate_snapshot_sha256"]:
        raise ValueError("Review packet binds a different candidate snapshot")
    snapshot = read(snapshot_path)
    payload = dict(snapshot)
    payload_hash = payload.pop("payload_sha256")
    if hashlib.sha256(canonical(payload)).hexdigest() != payload_hash:
        raise ValueError("Candidate snapshot payload hash differs")
    dataset = workspace_path(workspace, packet["dataset_root"])
    actual = {p.relative_to(dataset).as_posix() for p in dataset.rglob('*') if p.is_file()}
    if actual != set(snapshot["files"]) | {snapshot_path.relative_to(dataset).as_posix()}:
        raise ValueError("Candidate file set differs from the reviewed snapshot")
    for relative, digest in snapshot["files"].items():
        if sha(workspace_path(dataset, relative)) != digest:
            raise ValueError(f"Reviewed input asset changed: {relative}")
    annotations = {}
    for episode in packet["episodes"]:
        annotation_path = workspace_path(workspace, episode["source_annotation_path"])
        if sha(annotation_path) != episode["source_annotation_sha256"]:
            raise ValueError("Reviewed annotation changed")
        annotations[episode["episode_key"]] = read(annotation_path)
        for frame in episode["frames"]:
            for asset in [frame] + frame["context"]:
                if sha(workspace_path(packet_dir, asset["path"])) != asset["sha256"]:
                    raise ValueError("Review packet image changed")
    validation = validate_bundle(packet, bundle, annotations)
    validation.update({"packet_manifest_sha256": sha(packet_path), "review_bundle_sha256": sha(reviews_path),
                       "candidate_snapshot_sha256": sha(snapshot_path)})
    qa = evaluate.load_jsonl(dataset / snapshot["qa"])
    return ReviewContext(workspace, packet_dir, packet, bundle, reviews_path, dataset, snapshot, annotations, validation, qa)


def selection_plan(context: ReviewContext, qa_version: str, seed: int) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,100}", qa_version):
        raise ValueError("Use an explicit safe new QA version")
    if qa_version == context.packet["candidate_qa_version"]:
        raise ValueError("Reviewed QA must use a version distinct from its parent")
    report = context.validation
    complete = report["all_dispositions_complete"]
    outcomes = {r["episode_key"]: r for r in report["episodes"]}
    selected, excluded, changes, unresolved = [], [], [], []
    raw_worksheets = context.bundle.get("worksheets")
    worksheets = {w.get("episode_key"): w for w in raw_worksheets if isinstance(w, dict)} if isinstance(raw_worksheets, list) else {}
    for episode in context.packet["episodes"]:
        key = episode["episode_key"]
        outcome = outcomes.get(key, {})
        worksheet = worksheets.get(key, {})
        disposition = {"episode_key": key, "decision": outcome.get("decision"),
                       "decision_reason": worksheet.get("decision_reason", ""),
                       "review_errors": outcome.get("errors", []),
                       "source_annotation_path": episode["source_annotation_path"],
                       "source_annotation_sha256": episode["source_annotation_sha256"]}
        if not complete or not outcome.get("valid_complete_review_declaration"):
            unresolved.append(disposition)
        elif outcome["decision"] == "exclude":
            excluded.append(disposition)
        elif outcome["decision"] == "changes_required":
            changes.append(disposition)
        elif outcome["accepted_current_snapshot"]:
            frames = [f["source_frame"] for f in episode["frames"]]
            records = [r for r in context.qa_records if r["task_name"] == key]
            directions = ["forward" if "forward" in r["type"] else "inverse" for r in records]
            if sorted(directions) != ["forward", "inverse"] or any(list(map(int, r["key_frame_ids"])) != frames for r in records):
                raise ValueError("Expected one complete chain per accepted episode/direction")
            selected.append({**disposition, "family": episode["family"], "frames": frames,
                             "scope": episode["scope"], "directions": directions, "question_count": len(records),
                             "perm_len": len(frames) - 1, "source_qa_ids": [r["id"] for r in records],
                             "effective_review_state": "accepted_by_signed_declaration"})
    n = sum(e["question_count"] for e in selected)
    chance = (sum((Fraction(e["question_count"], 1) / factorial(e["perm_len"]) for e in selected), Fraction()) / n) if n else None
    ready = complete and bool(selected) and not changes and not unresolved
    if not complete:
        blocked = "incomplete_or_unqualified_review_declarations"
    elif changes:
        blocked = "frame_or_scope_changes_require_new_candidate_and_review"
    elif not selected:
        blocked = "no_accepted_episode"
    else:
        blocked = None
    return {"schema": "usim-signed-selection-plan/v1", "qa_version": qa_version, "algorithm": ALGORITHM, "seed": seed,
            "parent_qa_version": context.packet["candidate_qa_version"],
            "packet_version": context.packet["version"],
            "packet_manifest_sha256": context.validation["packet_manifest_sha256"],
            "review_bundle_sha256": context.validation["review_bundle_sha256"],
            "candidate_snapshot_sha256": context.validation["candidate_snapshot_sha256"],
            "identity_independently_authenticated": False, "reviewer_identity": context.validation["declared_reviewer_identity"],
            "all_dispositions_complete": complete, "selected": selected, "excluded": excluded,
            "changes_required": changes, "unresolved": unresolved,
            "episode_count": len(selected), "question_count": n,
            "uniform_random_EM_exact": str(chance) if chance is not None else None,
            "uniform_random_EM": float(chance) if chance is not None else None,
            "ready_for_qa_rebuild": ready, "blocked_reason": blocked,
            "release_eligible": False, "final_execution_protocol_frozen": False,
            "model_api_calls": 0}


def factorial(k: int) -> int:
    value = 1
    for i in range(2, k + 1):
        value *= i
    return value


def balanced_mapping(records: list[dict], qa_version: str, seed: int) -> list[dict]:
    def rank(value):
        return hashlib.sha256(canonical([ALGORITHM, qa_version, seed, value])).hexdigest()
    rows = []
    for k in sorted({len(r["gt_answer"]) for r in records}):
        ring = sorted(itertools.permutations(range(1, k + 1)), key=lambda p: rank(["permutation", k, p]))
        offset = 0
        for direction in ("forward", "inverse"):
            cell = [r for r in records if len(r["gt_answer"]) == k and direction in r["type"]]
            cell.sort(key=lambda r: rank(["episode", direction, k, r["task_name"], r["key_frame_ids"]]))
            for index, record in enumerate(cell):
                answer = list(ring[(offset + index) % len(ring)])
                rows.append({"parent_id": record["id"], "episode_key": record["task_name"], "direction": direction,
                             "chronological_frame_ids": record["key_frame_ids"], "proposed_gt": answer})
            offset += len(cell)
    return rows


def build_selected_qa(context: ReviewContext, plan: dict, dataset: Path, evidence: Path) -> dict:
    """Rebuild accepted unchanged chains and run actual-input gates, offline."""
    if not plan["ready_for_qa_rebuild"]:
        raise ValueError("A complete signed disposition with no pending changes is required")
    if dataset.exists():
        raise FileExistsError("Use a fresh dataset directory")
    font_name = resolve_font_path()
    if not font_name:
        raise ValueError("No real label font is available")
    font = Path(font_name)
    selected = {row["episode_key"]: row for row in plan["selected"]}
    parents = {r["id"]: r for r in context.qa_records if r["task_name"] in selected}
    mapping = balanced_mapping(list(parents.values()), plan["qa_version"], plan["seed"])
    if len(mapping) != plan["question_count"]:
        raise ValueError("Selection and parent QA count differ")
    dataset.mkdir(parents=True)
    annotations = dataset / "annotations/episodes"
    annotations.mkdir(parents=True)
    old_manifest = read(context.dataset / "manifest.json")
    entries = []
    for entry in old_manifest["episodes"]:
        key = entry["episode_key"]
        if key not in selected:
            continue
        source = workspace_path(context.workspace, selected[key]["source_annotation_path"])
        shutil.copyfile(source, annotations / source.name)
        for branch in ("replayed_activities", "segmented_activities"):
            shutil.copytree(context.dataset / branch / key, dataset / branch / key)
        entries.append(entry)
    if {e["episode_key"] for e in entries} != set(selected):
        raise ValueError("Dataset manifest and signed selection coverage differ")
    for copied in dataset.rglob('*'):
        if copied.is_file():
            expected_hash = context.snapshot["files"].get(copied.relative_to(dataset).as_posix())
            if expected_hash is None or sha(copied) != expected_hash:
                raise ValueError("Copied annotation, scene graph or native frame differs from the reviewed input")
    manifest = {**old_manifest, "protocol_version": plan["qa_version"], "qa_version": plan["qa_version"],
                "parent_qa_version": plan["parent_qa_version"], "episodes": entries,
                "annotation_sha256": {p.name: sha(p) for p in annotations.glob('*.json')},
                "annotations_dir": str(annotations), "counts": {"episodes": len(entries),
                    "key_frames": sum(len(e["key_frame_ids"]) for e in entries),
                    "transitions": sum(len(e["key_frame_ids"]) - 1 for e in entries),
                    "visible_transitions": sum(e["valid_transitions"] for e in entries)},
                "source_frame_verification": "raw/segmented bytes copied from the fully hash-verified reviewed snapshot",
                "review_bundle_sha256": plan["review_bundle_sha256"], "release_eligible": False,
                "identity_independently_authenticated": False, "final_execution_protocol_frozen": False}
    save(dataset / "manifest.json", manifest)
    records, binding_plan = [], {}
    for row in mapping:
        parent = parents[row["parent_id"]]
        gt, direction = row["proposed_gt"], row["direction"]
        qid_hash = hashlib.sha256(canonical([plan["qa_version"], plan["review_bundle_sha256"], parent["id"], gt])).hexdigest()[:24]
        qid = f"reviewed_{qid_hash}"
        question = parent["question"] if direction == "forward" else remap_inverse(parent["question"], parent["gt_answer"], gt)
        shown = display_frames(direction, parent["key_frame_ids"], gt)
        images = []
        for slot, frame in enumerate(shown):
            source = dataset / "replayed_activities" / parent["task_name"] / "external_sensor1" / f"{int(frame):05d}.png"
            target = dataset / "QA/images" / parent["type"] / parent["task_name"] / f"{qid}_slot_{slot:02d}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            picture, _ = rendered(source, "Current State" if slot == 0 else f"Next State {slot}", font)
            picture.save(target)
            images.append(target.relative_to(dataset).as_posix())
        records.append({**parent, "id": qid, "parent_diagnostic_id": parent["id"], "parent_qa_id": parent["id"],
                        "qa_version": plan["qa_version"], "images": images, "question": question, "gt_answer": gt,
                        "review_bundle_sha256": plan["review_bundle_sha256"]})
        binding_plan[parent["id"]] = row
    if len({r["id"] for r in records}) != len(records) or set(r["id"] for r in records) & set(parents):
        raise ValueError("New QA ID collision")
    qa = dataset / "QA/candidate/enact_ordering_reviewed.jsonl"
    qa.parent.mkdir(parents=True, exist_ok=True)
    qa.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    save(evidence / "mapping.json", {"algorithm": ALGORITHM, "seed": plan["seed"], "rows": mapping})
    binding = verify_bindings(dataset, records, parents, binding_plan, font)
    binding.update({"qa_version": plan["qa_version"], "independent_visual_acceptance": "accepted source frames by signed declarations; identity not authenticated",
                    "review_bundle_sha256": plan["review_bundle_sha256"]})
    save(evidence / "image_bindings.json", binding)
    distribution = balance_report(records)
    if distribution["uniform_random_EM"] != plan["uniform_random_EM_exact"]:
        raise ValueError("Rebuilt chance differs from selected episode composition")
    save(evidence / "answer_distribution.json", distribution)
    argv = ["--data-root", str(dataset), "--qa", str(qa)]
    if audit_qa_validity.main(argv + ["--out", str(evidence / "permutation_audit.json"), "--skip-synthetic-baselines"]) != 0:
        raise RuntimeError("Rebuilt QA permutation audit failed")
    audit = read(evidence / "permutation_audit.json")
    if not all(r["accepted_count"] == 1 and r["gt_accepted"] and not r["empty_reference_transitions"] for r in audit["questions"]):
        raise ValueError("Rebuilt actual-QA uniqueness gate failed")
    if evaluate.main(argv + ["--synthetic", "oracle", "--out", str(evidence / "oracle.json")]) != 0:
        raise RuntimeError("Oracle failed")
    oracle = read(evidence / "oracle.json")
    if not all(oracle["overall"][m] == 1 for m in ("EM", "TA", "PA_item_mean", "PA_transition_micro")):
        raise ValueError("Oracle metrics are not all one")
    program_baselines = {}
    for mode in ("identity", "reverse"):
        if evaluate.main(argv + ["--synthetic", mode, "--out", str(evidence / f"baseline_{mode}.json")]) != 0:
            raise RuntimeError(f"Fixed {mode} baseline failed")
        program_baselines[mode] = read(evidence / f"baseline_{mode}.json")["overall"]
    evaluator = evaluate.USIMEvaluator(dataset)
    for grouping in ("length", "direction_length"):
        groups = defaultdict(list)
        for record in records:
            direction = "forward" if "forward" in record["type"] else "inverse"
            groups[(direction if grouping == "direction_length" else "", len(record["gt_answer"]))].append(record)
        answers = {}
        for rows in groups.values():
            counts = Counter(tuple(r["gt_answer"]) for r in rows)
            chosen = min(counts, key=lambda p: (-counts[p], p))
            answers.update({r["id"]: list(chosen) for r in rows})
        scored = evaluator.evaluate(records, answers)
        score = evaluator.summarise([item for cell in scored["items"].values() for item in cell])
        expected = round(float(Fraction(distribution[grouping]["best_constant_overall_EM"])), 4)
        if score["EM"] != expected or score["TA"] != expected:
            raise ValueError("Scored best constant differs from the finite sample bound")
        program_baselines[f"best_{grouping}_constant"] = score
    save(evidence / "program_baselines.json", {"posthoc_best_constants_are_distribution_audits": True,
                                               "baselines": program_baselines})
    if text_prior_baseline.main(argv + ["--out", str(evidence / "text_baseline.json"),
                                      "--predictions-out", str(evidence / "text_baseline_answers.jsonl")]) != 0:
        raise RuntimeError("Text baseline failed")
    checks = {"schema": "usim-reviewed-rebuild-gates/v1", "qa_version": plan["qa_version"],
              "questions": len(records), "episodes": len(selected), "uniform_random_EM_exact": distribution["uniform_random_EM"],
              "best_length_constant_EM": distribution["length"]["best_constant_overall_EM"],
              "best_direction_length_constant_EM": distribution["direction_length"]["best_constant_overall_EM"],
              "program_baselines": program_baselines,
              "unique_gate_passed": True, "oracle": oracle["overall"], "bound_presented_images": binding["presented_images"],
              "text_baseline": read(evidence / "text_baseline.json")["metrics"], "release_eligible": False,
              "identity_independently_authenticated": False, "final_execution_protocol_frozen": False, "model_api_calls": 0}
    save(evidence / "rebuild_gates.json", checks)
    save(dataset / "signed_selection.json", plan)
    snapshot = {"schema": "usim-reviewed-candidate-snapshot/v1", "qa_version": plan["qa_version"],
                "review_bundle_sha256": plan["review_bundle_sha256"], "source_candidate_snapshot_sha256": plan["candidate_snapshot_sha256"],
                "font_sha256": sha(font), "builder_sha256": sha(Path(__file__)), "qa": qa.relative_to(dataset).as_posix(),
                "flow_input_manifest_sha256": sha(evidence / "flow_input_manifest.json"),
                "review_validation_sha256": sha(evidence / "review_validation.json"),
                "selection_plan_sha256": sha(evidence / "selection_plan.json"),
                "qa_sha256": sha(qa), "files": {p.relative_to(dataset).as_posix(): sha(p) for p in sorted(dataset.rglob('*')) if p.is_file()},
                "rebuild_gates_sha256": sha(evidence / "rebuild_gates.json"), "release_eligible": False,
                "identity_independently_authenticated": False, "final_execution_protocol_frozen": False}
    snapshot["payload_sha256"] = hashlib.sha256(canonical(snapshot)).hexdigest()
    save(dataset / "candidate_input_snapshot.json", snapshot)
    save(evidence / "candidate_input_snapshot.json", snapshot)
    return checks


def run_flow(packet_dir: Path, reviews: Path, out: Path, qa_version: str, seed: int,
             build_dataset: Path | None = None, workspace: Path = WORKSPACE) -> dict:
    context = load_context(packet_dir, reviews, workspace)
    plan = selection_plan(context, qa_version, seed)
    if out.exists():
        raise FileExistsError("Use a fresh evidence/output directory")
    if build_dataset is not None and build_dataset.exists():
        raise FileExistsError("Use a fresh dataset directory")
    out.mkdir(parents=True)
    shutil.copyfile(reviews, out / "review_bundle.json")
    shutil.copyfile(packet_dir / "packet_manifest.json", out / "packet_manifest.json")
    save(out / "flow_input_manifest.json", {
        "qa_version": qa_version, "review_bundle_sha256": sha(reviews),
        "packet_manifest_sha256": sha(packet_dir / "packet_manifest.json"),
        "source_candidate_snapshot_sha256": context.packet["candidate_snapshot_sha256"],
        "code_sha256": {p.relative_to(WORKSPACE).as_posix(): sha(p) for p in [
            Path(__file__), ROOT / "scripts/usim/validate_acceptance_reviews.py",
            ROOT / "scripts/usim/build_conservative_balanced_qa.py", ROOT / "scripts/usim/evaluate.py",
            ROOT / "scripts/usim/audit_qa_validity.py", ROOT / "scripts/usim/text_prior_baseline.py",
            ROOT / "enact/core/evaluators.py"]},
        "typed_signature_is_identity_authentication": False, "release_eligible": False})
    save(out / "review_validation.json", context.validation)
    save(out / "selection_plan.json", plan)
    save(out / "review_dispositions.json", {key: plan[key] for key in ("selected", "excluded", "changes_required", "unresolved")})
    result = {"qa_version": qa_version, "ready_for_qa_rebuild": plan["ready_for_qa_rebuild"],
              "blocked_reason": plan["blocked_reason"], "selected_episodes": plan["episode_count"],
              "planned_questions": plan["question_count"], "uniform_random_EM_exact": plan["uniform_random_EM_exact"],
              "qa_built": False, "release_eligible": False, "model_api_calls": 0}
    if build_dataset is not None and plan["ready_for_qa_rebuild"]:
        attempts = []

        def deny(*a, **kw):
            attempts.append("socket connection")
            raise RuntimeError("Network disabled during signed-review rebuild")

        old_connect, old_connect_ex = socket.socket.connect, socket.socket.connect_ex
        socket.socket.connect, socket.socket.connect_ex = deny, deny
        try:
            with (out / "execution.txt").open("w", encoding="utf-8", newline="\n") as log, redirect_stdout(log), redirect_stderr(log):
                gates = build_selected_qa(context, plan, build_dataset, out)
        except Exception as error:
            result.update({"qa_built": False, "blocked_reason": "rebuild_or_mechanical_gate_failed",
                           "error_type": type(error).__name__, "error": str(error)})
            save(out / "summary.json", result)
            raise
        finally:
            socket.socket.connect, socket.socket.connect_ex = old_connect, old_connect_ex
            save(out / "network_receipt.json", {"socket_attempts": len(attempts), "model_api_calls": 0})
        if attempts:
            raise RuntimeError("Unexpected network attempt")
        result.update({"qa_built": True, "built_dataset": str(build_dataset), "rebuild_gates": gates})
    save(out / "summary.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet-dir", type=Path, default=ROOT / "data/usim_enact/_review/test_reserve/acceptance_workpack_20261029_v2")
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="fresh evidence or packet child")
    parser.add_argument("--qa-version", required=True)
    parser.add_argument("--seed", type=int, default=20261029)
    parser.add_argument("--build-dataset", type=Path, help="optional fresh reviewed dataset root; rebuilds when dispositions permit")
    args = parser.parse_args()
    out = args.out.resolve()
    allowed = [(ROOT / "docs/WBW/evidence").resolve(), (ROOT / "data/usim_enact/_review/test_reserve").resolve()]
    if not any(out != p and out.is_relative_to(p) for p in allowed):
        raise ValueError("Output must remain in fresh evidence or test review scope")
    dataset = args.build_dataset.resolve() if args.build_dataset else None
    if dataset is not None and (dataset.parent != (ROOT / "data/usim_enact").resolve()
                                or not dataset.name.startswith("usim-enact-v0.2-reviewed-")):
        raise ValueError("Use a new usim-enact-v0.2-reviewed-* dataset, preserving prior versions")
    result = run_flow(args.packet_dir, args.reviews, out, args.qa_version, args.seed, dataset)
    print(json.dumps({k: result[k] for k in ("ready_for_qa_rebuild", "blocked_reason", "selected_episodes",
                     "planned_questions", "uniform_random_EM_exact", "qa_built", "release_eligible", "model_api_calls")}, ensure_ascii=False))
    raise SystemExit(0 if result["ready_for_qa_rebuild"] else 2)


if __name__ == "__main__":
    main()
