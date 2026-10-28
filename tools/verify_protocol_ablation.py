"""Independent, offline verification for the versioned dual-protocol matrix.

Default scope requires the entire formal run. --prepared-only checks inputs and
source freezing, and explicitly does not attest any executed request.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE / "ENACT") not in sys.path:
    sys.path.insert(0, str(WORKSPACE / "ENACT"))

from scripts.usim import protocol_ablation_v1 as contract


def verify_freeze(path: Path, bundle: Path, workspace: Path, data_root: Path) -> dict:
    report = {"ok": False, "changed": [], "missing": [], "errors": []}
    try:
        manifest = contract.read_json(path)
        contract.check_seal(manifest)
        if manifest["schema"] != contract.FREEZE_SCHEMA or not manifest["files"]:
            raise contract.IntegrityError("unsupported or empty freeze inventory")
        if manifest.get("freeze_id") != f"protocol_ablation2048_v1:{manifest['plan_sha256'][:12]}:{manifest['stage']}":
            raise contract.IntegrityError("freeze identity differs from plan/stage")
        indexed = {}
        roots = {"workspace": workspace, "run": bundle, "data": data_root}
        for item in manifest["files"]:
            identity = (item["root"], item["path"])
            if identity in indexed:
                raise contract.IntegrityError("duplicate frozen file")
            indexed[identity] = item
            actual = contract.within(roots[item["root"]], item["path"])
            if not actual.is_file():
                report["missing"].append(f"{identity[0]}:{identity[1]}")
            elif contract.file_sha(actual) != item["sha256"]:
                report["changed"].append(f"{identity[0]}:{identity[1]}")
        report["manifest"] = manifest
    except (OSError, ValueError, KeyError, TypeError) as error:
        report["errors"].append(str(error))
    report["ok"] = not (report["errors"] or report["changed"] or report["missing"])
    return report


def _stage(bundle: Path, plan: dict, records: dict, stage: str, *, complete: bool) -> dict:
    schedule = plan["smoke_schedule"] if stage == "smoke" else plan["schedule"]
    expected = {contract.job_id(job): job for job in schedule}
    result = {"expected": len(expected), "predictions": 0, "bodies_checked": 0, "complete": False,
              "errors": [], "cells": {}}
    for protocol in contract.PROTOCOLS:
        for condition in contract.CONDITIONS:
            job = {"protocol": protocol, "condition": condition}
            directory = contract.cell_dir(bundle, job, stage)
            wanted = {key: value for key, value in expected.items() if value["protocol"] == protocol and value["condition"] == condition}
            predictions_path = directory / "predictions.jsonl"
            predictions = contract.read_rows(predictions_path) if predictions_path.exists() else []
            pred = contract.unique(predictions, "job_id")
            if set(pred) - set(wanted):
                raise contract.IntegrityError("unknown prediction job/ID")
            if complete and set(pred) != set(wanted):
                result["errors"].append(f"{protocol}/{condition}: incomplete ID coverage")
            attempts_path = directory / "attempts.jsonl"
            responses_path = directory / "responses.jsonl"
            attempts = contract.read_rows(attempts_path) if attempts_path.exists() else []
            responses = contract.read_rows(responses_path) if responses_path.exists() else []
            attempt_map = {}
            response_map = {}
            for collection, target in ((attempts, attempt_map), (responses, response_map)):
                for row in collection:
                    identity = (row["job_id"], row["attempt"])
                    if row["job_id"] not in wanted or identity in target:
                        raise contract.IntegrityError("unknown or duplicate attempt/response")
                    target[identity] = row
            if set(attempt_map) != set(response_map):
                raise contract.IntegrityError("attempt/response inventory differs")
            if {key[0] for key in attempt_map} != set(pred):
                raise contract.IntegrityError("orphan attempt/response without a final prediction")
            cell = {"expected": len(wanted), "present": len(pred), "strict_valid": 0, "truncated": 0,
                    "failed": 0, "extractable": 0, "format_gate_passed": False}
            for identity, entry in pred.items():
                definition = wanted[identity]
                if any(entry.get(key) != definition[key] for key in ("id", "protocol", "condition")):
                    raise contract.IntegrityError("prediction identity conflicts with plan")
                record = records[condition][definition["id"]]
                body = contract.build_body(record, plan, protocol, condition)
                hashes = contract.body_hashes(body)
                if plan["request_hashes"][identity] != hashes:
                    raise contract.IntegrityError("planned request body cannot be reconstructed")
                if any(entry.get(key) != value for key, value in hashes.items()):
                    raise contract.IntegrityError("prediction request hash differs")
                count = entry["attempts"]
                if type(count) is not int or not 1 <= count <= plan["execution"]["max_attempts"]:
                    raise contract.IntegrityError("attempt count outside frozen bounds")
                seen = sorted(number for jid, number in attempt_map if jid == identity)
                if seen != list(range(1, count + 1)):
                    raise contract.IntegrityError("attempt sequence differs from final prediction")
                for number in seen:
                    attempt = attempt_map[(identity, number)]
                    response = response_map[(identity, number)]
                    if any(attempt.get(key) != value or response.get(key) != value for key, value in hashes.items()):
                        raise contract.IntegrityError("attempt/response request hash differs")
                    outcome = contract.decode_response_record(response)
                    if outcome["http_status"] != attempt["http_status"]:
                        raise contract.IntegrityError("attempt HTTP status conflicts with response")
                    if number < count and outcome["http_status"] not in (None, *contract.RETRY_STATUSES):
                        raise contract.IntegrityError("non-retryable response was retried")
                response = response_map[(identity, count)]
                outcome = contract.decode_response_record(response)
                rescored = contract.score_response(outcome, protocol, len(record["key_frame_ids"]) - 1)
                if any(entry.get(key) != value for key, value in rescored.items()):
                    raise contract.IntegrityError("assembly or response reparsing differs")
                if entry.get("response_record_sha256") != contract.sha(contract.canonical(response)) or entry.get("http_status") != outcome["http_status"]:
                    raise contract.IntegrityError("prediction is not bound to its recorded response")
                payload = outcome["payload"] if isinstance(outcome["payload"], dict) else {}
                headers = response.get("headers") or {}
                metadata = {"usage": payload.get("usage"), "model_returned": payload.get("model"),
                            "request_id": headers.get("x-request-id") or headers.get("x-dashscope-request-id") or payload.get("id"),
                            "type": record["type"], "task_name": record["task_name"], "num_states": len(record["key_frame_ids"])}
                if any(entry.get(key) != value for key, value in metadata.items()):
                    raise contract.IntegrityError("prediction metadata conflicts with response/QA")
                cell["strict_valid"] += rescored["strict_permutation"] is not None
                cell["truncated"] += rescored["finish_reason"] == "length"
                cell["failed"] += rescored["status"] in ("failed", "invalid")
                cell["extractable"] += rescored["extract_status"] == "ok"
                result["bodies_checked"] += 1
            cell["format_gate_passed"] = (cell["present"] == cell["expected"] and cell["strict_valid"] == cell["expected"]
                                           and cell["truncated"] == 0 and cell["failed"] == 0)
            if stage == "smoke" and protocol == "no_prefill":
                # Format errors are the control's measured behavior, not an API incompatibility.
                cell["compatibility_passed"] = len(pred) == len(wanted) and all(
                    row["http_status"] == 200 and row.get("raw_completion") for row in pred.values())
            else:
                cell["compatibility_passed"] = cell["format_gate_passed"] and all(not row["prefix_echo"] for row in pred.values())
            result["cells"][f"{protocol}/{condition}"] = cell
            result["predictions"] += len(pred)
    result["complete"] = result["predictions"] == len(expected) and result["bodies_checked"] == len(expected) and bool(expected)
    if complete and not result["complete"]:
        result["errors"].append("reconstructed request count does not equal the full schedule")
    return result


def verify(bundle: Path, *, workspace: Path = WORKSPACE, prepared_only: bool = False,
           stage: str = "formal", allow_partial: bool = False) -> dict:
    result = {"ok": False, "scope": "prepared_inputs" if prepared_only else ("partial_evidence" if allow_partial else "complete_run"),
              "execution_verified": False, "errors": [], "file_freeze": {}, "request_reconstruction": {}}
    try:
        plan = contract.read_json(bundle / "plan.json")
        conditions = contract.validate_plan(bundle, plan)
        records = {key: contract.unique(rows) for key, rows in conditions.items()}
        data_root = Path(plan["data_root"])
        frozen = verify_freeze(bundle / "candidate.freeze.json", bundle, workspace, data_root)
        result["file_freeze"] = {key: value for key, value in frozen.items() if key != "manifest"}
        if not frozen["ok"]:
            raise contract.IntegrityError("candidate file freeze failed")
        manifest = frozen["manifest"]
        expected_files = {("workspace", path) for path in contract.SOURCE_FILES}
        expected_files |= {("workspace", path) for path in plan["reference_files_sha256"]}
        expected_files |= {("run", "plan.json"), *(("run", f"inputs/{key}.jsonl") for key in contract.CONDITIONS)}
        expected_files |= {("run", f"{protocol}/{label}/run_config.json") for protocol in contract.PROTOCOLS for label in contract.CONDITIONS.values()}
        expected_files |= {("data", path) for path in plan["images_sha256"]}
        if {(item["root"], item["path"]) for item in manifest["files"]} != expected_files or manifest["plan_sha256"] != plan["plan_sha256"]:
            raise contract.IntegrityError("freeze inventory/plan reference differs")
        if manifest.get("stage") != "candidate" or any(item["sha256"] != plan["images_sha256"][item["path"]]
                                                       for item in manifest["files"] if item["root"] == "data"):
            raise contract.IntegrityError("freeze stage/image references differ")
        if any(item["sha256"] != plan["reference_files_sha256"][item["path"]] for item in manifest["files"]
               if item["root"] == "workspace" and item["path"] in plan["reference_files_sha256"]):
            raise contract.IntegrityError("scoring/data reference hash differs")
        for condition, rows in conditions.items():
            for row in rows:
                body0 = contract.build_body(row, plan, "no_prefill", condition)
                body1 = contract.build_body(row, plan, "prefill", condition)
                if body1 != dict(body0, messages=body0["messages"] + [{"role": "assistant", "content": "[", "partial": True}]):
                    raise contract.IntegrityError("protocol difference is not confined to the declared prefix")
                for protocol, body in (("no_prefill", body0), ("prefill", body1)):
                    identity = contract.job_id({"protocol": protocol, "condition": condition, "id": row["id"]})
                    if contract.body_hashes(body) != plan["request_hashes"][identity]:
                        raise contract.IntegrityError("input/decode/request body drift")
            for protocol in contract.PROTOCOLS:
                actual = contract.read_json(contract.cell_dir(bundle, {"protocol": protocol, "condition": condition}) / "run_config.json")
                if actual != contract.expected_config(plan, protocol, condition):
                    raise contract.IntegrityError("cell config differs from frozen plan")
        if (bundle / "inflight.json").exists():
            raise contract.IntegrityError("unresolved in-flight request; do not automatically resend")
        if not prepared_only:
            if stage == "formal":
                execution = verify_freeze(bundle / "execution.freeze.json", bundle, workspace, data_root)
                result["execution_freeze"] = {key: value for key, value in execution.items() if key != "manifest"}
                if not execution["ok"]:
                    raise contract.IntegrityError("execution freeze failed")
                executed = execution["manifest"]
                expected_execution_files = {("run", "candidate.freeze.json"), ("run", "smoke/acceptance.json")}
                expected_execution_files |= {("run", f"smoke/{protocol}/{label}/{filename}")
                                             for protocol in contract.PROTOCOLS for label in contract.CONDITIONS.values()
                                             for filename in ("predictions.jsonl", "attempts.jsonl", "responses.jsonl")}
                if (executed.get("stage") != "execution" or executed.get("plan_sha256") != plan["plan_sha256"]
                        or executed.get("candidate_sha256") != contract.file_sha(bundle / "candidate.freeze.json")
                        or {(item["root"], item["path"]) for item in executed["files"]} != expected_execution_files):
                    raise contract.IntegrityError("execution freeze plan/evidence inventory differs")
                smoke = _stage(bundle, plan, records, "smoke", complete=True)
                acceptance = {"schema": "usim-protocol-ablation-smoke/v1", "plan_sha256": plan["plan_sha256"],
                              "expected": 8, "checked": smoke["bodies_checked"],
                              "compatibility_passed": smoke["complete"] and not smoke["errors"] and all(
                                  cell["compatibility_passed"] for cell in smoke["cells"].values()), "em_used": False}
                if not acceptance["compatibility_passed"] or contract.read_json(bundle / "smoke/acceptance.json") != acceptance:
                    raise contract.IntegrityError("smoke compatibility evidence does not pass")
            result["request_reconstruction"] = _stage(bundle, plan, records, stage, complete=not allow_partial)
            result["errors"].extend(result["request_reconstruction"]["errors"])
            result["execution_verified"] = result["request_reconstruction"]["complete"] and not result["errors"]
        result["ok"] = not result["errors"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        result["errors"].append(str(error))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--prepared-only", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args(argv)
    report = verify(args.run_dir.resolve(), prepared_only=args.prepared_only, stage="smoke" if args.smoke else "formal")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
