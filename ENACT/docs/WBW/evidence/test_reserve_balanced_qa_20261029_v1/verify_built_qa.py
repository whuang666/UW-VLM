"""Read-only replay of the built candidate snapshot, mappings and image labels."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile

import numpy as np
from PIL import Image

WORKSPACE = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(WORKSPACE / "ENACT"))
from enact.adapters.usim_visual_prompt import render_label  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    evidence = Path(__file__).resolve().parent
    summary = read(evidence / "summary.json")
    root = WORKSPACE / summary["dataset"]
    snapshot = read(root / "candidate_input_snapshot.json")
    payload = dict(snapshot)
    expected_payload = payload.pop("payload_sha256")
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    assert hashlib.sha256(canonical).hexdigest() == expected_payload
    assert sha(root / "candidate_input_snapshot.json") == summary["candidate_snapshot_sha256"]
    actual_files = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    assert actual_files == set(snapshot["files"]) | {"candidate_input_snapshot.json"}
    for relative, digest in snapshot["files"].items():
        path = (root / relative).resolve()
        assert path.is_relative_to(root.resolve()) and sha(path) == digest
    plan = read(evidence / "build_plan.json")
    assert sha(evidence / "build_plan.json") == snapshot["build_plan_sha256"]
    assert sha(Path(plan["renderer"]["font_path"])) == plan["renderer"]["font_sha256"]
    for relative, digest in plan["code_sha256"].items():
        assert sha(WORKSPACE / relative) == digest
    parents_dir = WORKSPACE / "ENACT/docs/WBW/evidence/test_reserve_conservative_semantic_20261029_v1"
    parents = {r["id"]: r for r in map(json.loads, (parents_dir / "diagnostic_full_chain_qa.jsonl").read_text(encoding="utf-8").splitlines())}
    mappings_path = WORKSPACE / "ENACT/docs/WBW/evidence/test_reserve_permutation_strategy_20261029_v1/strategy_preview.json"
    assert sha(mappings_path) == plan["mapping_sha256"]
    mapped = {r["parent_diagnostic_id"]: r for r in read(mappings_path)["schedule"]}
    old_manifest = read(parents_dir / "compiled_dataset_manifest.json")
    old_entries = {r["episode_key"]: r for r in old_manifest["episodes"]}
    records = [json.loads(line) for line in (root / snapshot["qa"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(records) == 20 and len({r["id"] for r in records}) == 20
    assert not set(r["id"] for r in records) & set(parents)
    assert sha(root / snapshot["qa"]) == sha(evidence / "enact_ordering_balanced.jsonl") == snapshot["qa_sha256"]
    action_pattern = re.compile(r"^\[Action (\d+)\] ([^\r\n]*)$", re.MULTILINE)
    images_checked = 0
    with tempfile.TemporaryDirectory() as tmp:
        expected_image = Path(tmp) / "label.png"
        for record in records:
            parent = parents[record["parent_diagnostic_id"]]
            mapping = mapped[parent["id"]]
            assert record["key_frame_ids"] == parent["key_frame_ids"] == mapping["chronological_frame_ids"]
            assert record["gt_answer"] == mapping["proposed_gt"]
            gt = record["gt_answer"]
            frames = record["key_frame_ids"]
            is_forward = "forward" in record["type"]
            assert is_forward == (mapping["direction"] == "forward")
            if is_forward:
                assert record["question"] == parent["question"]
                order = [0] + [gt.index(label) + 1 for label in range(1, len(frames))]
            else:
                old_actions = {int(label): text for label, text in action_pattern.findall(parent["question"])}
                new_actions = {int(label): text for label, text in action_pattern.findall(record["question"])}
                assert len(new_actions) == len(gt)
                assert [new_actions[label] for label in gt] == [old_actions[label] for label in parent["gt_answer"]]
                assert action_pattern.sub("", record["question"]) == action_pattern.sub("", parent["question"])
                order = list(range(len(frames)))
            assert len(record["images"]) == len(order)
            for slot, chronological_index in enumerate(order):
                frame_id = frames[chronological_index]
                native = root / "replayed_activities" / record["task_name"] / "external_sensor1" / f"{int(frame_id):05d}.png"
                assert sha(native) == old_entries[record["task_name"]]["frames"][frame_id]["sha256"]
                # Use the existing stock label renderer, rather than the new
                # builder's rendering and mapping helper implementations.
                render_label(str(native), "Current State" if slot == 0 else f"Next State {slot}", str(expected_image))
                with Image.open(root / record["images"][slot]) as shown, Image.open(expected_image) as expected:
                    assert np.array_equal(np.asarray(shown.convert("RGB")), np.asarray(expected.convert("RGB")))
                images_checked += 1
    result = {"qa_version": summary["qa_version"], "snapshot_payload_and_file_set_match": True,
              "snapshot_files_checked": len(snapshot["files"]), "new_ids_disjoint_from_diagnostics": True,
              "agreed_mappings_checked": len(records), "stock_rerendered_images_match": images_checked,
              "native_frames_match_parent_audit": True, "inverse_chronological_action_content_preserved": True,
              "independent_human_review": False, "model_api_calls": 0}
    (evidence / "independent_verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
