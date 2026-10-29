"""Run actual blank-review rejection and a completely fictional happy path."""

from contextlib import redirect_stdout
import argparse
import io
import json
from pathlib import Path
import subprocess
import sys

WORKSPACE = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(WORKSPACE / "ENACT"))
sys.path.insert(0, str(WORKSPACE / "tools"))
from scripts.usim import advance_signed_candidates as flow
from test_signed_candidate_flow import fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", default="v1")
    args = parser.parse_args()
    if not args.case_id.isalnum():
        raise ValueError("Case ID must be alphanumeric")
    evidence = Path(__file__).resolve().parent
    actual = evidence / ("actual_unsigned_final_" + args.case_id)
    dataset = WORKSPACE / "ENACT/data/usim_enact/usim-enact-v0.2-reviewed-20261029-v1"
    assert not actual.exists() and not dataset.exists()
    command = [sys.executable, "-X", "utf8", str(WORKSPACE / "ENACT/scripts/usim/advance_signed_candidates.py"),
               "--reviews", str(WORKSPACE / "ENACT/data/usim_enact/_review/test_reserve/acceptance_workpack_20261029_v2/review_templates.json"),
               "--out", str(actual), "--qa-version", "test-reviewed-qa-20261029-v1", "--build-dataset", str(dataset)]
    process = subprocess.run(command, cwd=WORKSPACE, capture_output=True, text=True, encoding="utf-8")
    (evidence / ("actual_unsigned_final_stdout_" + args.case_id + ".txt")).write_text(process.stdout + process.stderr, encoding="utf-8")
    assert process.returncode == 2 and not dataset.exists()
    rejected = flow.read(actual / "summary.json")
    assert rejected["selected_episodes"] == 0 and rejected["qa_built"] is False
    work = WORKSPACE / ("ENACT/data/usim_enact/_review/test_reserve/signed_flow_smoke_20261029_" + args.case_id + "/tools_out")
    assert not work.exists()
    work.mkdir(parents=True)
    packet, reviews, _ = fixture(work)
    with redirect_stdout(io.StringIO()):
        result = flow.run_flow(packet, reviews, work / "evidence", "synthetic-reviewed-demo-v1", 20261029,
                               work / "rebuilt_dataset", work)
    gates = result["rebuild_gates"]
    assert gates["questions"] == 18 and gates["episodes"] == 9
    assert gates["uniform_random_EM_exact"] == "23/54" and gates["best_direction_length_constant_EM"] == "5/9"
    assert gates["bound_presented_images"] == 58 and not gates["release_eligible"]
    snapshot = flow.read(work / "rebuilt_dataset/candidate_input_snapshot.json")
    assert all(flow.sha(work / "rebuilt_dataset" / p) == h for p, h in snapshot["files"].items())
    audit = flow.read(work / "evidence/permutation_audit.json")
    receipt = {"schema": "usim-signed-flow-smoke/v1", "actual_unsigned_run_exit": process.returncode,
               "actual_selected_episodes": 0, "actual_new_dataset_created": False,
               "synthetic_only_positive_fixture": True, "synthetic_episodes": gates["episodes"],
               "synthetic_questions": gates["questions"], "synthetic_presented_images": gates["bound_presented_images"],
               "synthetic_accepted_permutations": audit["overall"]["accepted_count_histogram"],
               "synthetic_permutation_checks": sum(r["permutations_total"] for r in audit["questions"]),
               "synthetic_chance_exact": gates["uniform_random_EM_exact"],
               "synthetic_best_length_constant": gates["best_length_constant_EM"],
               "synthetic_best_direction_length_constant": gates["best_direction_length_constant_EM"],
               "synthetic_oracle": gates["oracle"], "synthetic_text_baseline": gates["text_baseline"],
               "synthetic_asset_file_count": len(snapshot["files"]),
               "synthetic_snapshot_file_hashes_match": True,
               "synthetic_work_dir": work.relative_to(WORKSPACE).as_posix(),
               "builder_sha256": flow.sha(WORKSPACE / "ENACT/scripts/usim/advance_signed_candidates.py"),
               "actual_independent_acceptance": "0/10", "model_api_calls": 0, "release_eligible": False}
    flow.save(evidence / ("smoke_receipt_" + args.case_id + ".json"), receipt)
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
