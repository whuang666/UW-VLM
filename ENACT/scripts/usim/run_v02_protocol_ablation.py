"""Versioned dual-protocol development matrix: prepare (default), execute, analyse, verify.

Only --execute may access credentials or HTTP. Execution runs eight compatibility
requests first, seals their evidence separately, then the 588 planned requests.
--execute --smoke-only stops after compatibility checks. Resuming requires --resume.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

ENACT = Path(__file__).resolve().parents[2]
WORKSPACE = ENACT.parent
for path in (ENACT, WORKSPACE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts.usim import protocol_ablation_v1 as contract
from tools.verify_protocol_ablation import verify

BASE = ENACT / "data/usim_enact"
DATA_ROOT = BASE / "usim-enact-v0.2"
SOURCE_RUN = BASE / "runs/qwen3.8-max/v02_dev_001"
DEFAULT_RUN = BASE / "runs/qwen3.8-max/v02_protocol_ablation2048_dev_v1"


def now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="milliseconds")


def prepare(bundle: Path) -> dict:
    if (bundle / "plan.json").exists():
        checked = verify(bundle, prepared_only=True)
        if not checked["ok"]:
            raise contract.IntegrityError(str(checked["errors"]))
        return contract.read_json(bundle / "plan.json")
    from scripts.usim.freeze_protocol import verify_manifest
    if SOURCE_RUN.resolve() == bundle.resolve() or SOURCE_RUN.resolve() in bundle.resolve().parents:
        raise contract.IntegrityError("output overlaps historical run")
    original_path = BASE / "_protocol/freeze_usim-enact-v0.2_20261027b.json"
    original_manifest = contract.read_json(original_path)
    original = verify_manifest(original_manifest, root_override=ENACT)
    if not original["ok"]:
        raise contract.IntegrityError(f"primary protocol verification failed: {original['errors']}")
    config = contract.read_json(SOURCE_RUN / "A_full_image/run_config.json")
    for relative, expected in config["code_sha256"].items():
        if contract.file_sha(ENACT / relative.replace("\\", "/")) != expected:
            raise contract.IntegrityError(f"primary dependency drift: {relative}")
    a = contract.read_rows(SOURCE_RUN / "inputs/dev.jsonl")
    b = contract.read_rows(SOURCE_RUN / "inputs/dev_B.jsonl")
    ids = {row["id"] for row in a}
    d = [row for row in contract.read_rows(BASE / "_protocol/conditions/D_no_action_text_v0.2/enact_ordering.jsonl") if row["id"] in ids]
    conditions = {"A": a, "B": b, "C": a, "D": sorted(d, key=lambda row: row["id"])}
    decode = {key: config[key] for key in ("api_url", "model_requested", "enable_thinking", "temperature", "stream", "system_prompt", "format_directive")}
    other = contract.read_json(SOURCE_RUN / "B_zoom/run_config.json")
    if any(other[key] != value for key, value in decode.items()):
        raise contract.IntegrityError("original A/B request policies differ")
    decode["max_completion_tokens"] = 2048
    episodes = {row["task_name"] for row in a}
    references = {}
    for group_name, group in original_manifest["groups"].items():
        for relative, expected in group["files"].items():
            if (group_name == "code" or relative == "data/usim_enact/usim-enact-v0.2/manifest.json"
                    or any(f"/{episode}/" in relative or relative.endswith(f"/{episode}.json") for episode in episodes)):
                references[f"ENACT/{relative}"] = expected
    for path in (original_path, SOURCE_RUN / "A_full_image/run_config.json", SOURCE_RUN / "B_zoom/run_config.json"):
        references[path.relative_to(WORKSPACE).as_posix()] = contract.file_sha(path)
    return contract.create_bundle(bundle, WORKSPACE, DATA_ROOT, conditions, decode, reference_files=references)


def resolve_key() -> str:
    value = os.environ.get("VLM_API_KEY", "").strip()
    if value:
        return value
    if os.name == "nt":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as handle:
                value, _ = winreg.QueryValueEx(handle, "VLM_API_KEY")
            if isinstance(value, str) and value.strip():
                return value
        except OSError:
            pass
    raise contract.IntegrityError("VLM_API_KEY is absent; no HTTP request sent")


def send_http(url: str, wire: bytes, key: str, timeout: int) -> dict:
    request = urllib.request.Request(url, data=wire, headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = response.status
            headers = response.headers
    except urllib.error.HTTPError as error:
        raw, status, headers = error.read(), error.code, error.headers
    except (OSError, TimeoutError) as error:
        return {"http_status": None, "payload": None, "response_wire_b64": None,
                "response_wire_sha256": None, "network_error": type(error).__name__, "headers": {}}
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        payload = None
    safe_headers = {name: headers.get(name) for name in ("x-request-id", "x-dashscope-request-id", "retry-after") if headers.get(name)}
    return {"http_status": status, "payload": payload, "response_wire_b64": base64.b64encode(raw).decode("ascii"),
            "response_wire_sha256": contract.sha(raw), "network_error": None, "headers": safe_headers}


def append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(contract.canonical(row) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())


def run_job(bundle: Path, plan: dict, record: dict, job: dict, stage: str, key: str,
            *, transport=send_http, sleeper=time.sleep) -> dict:
    body = contract.build_body(record, plan, job["protocol"], job["condition"])
    identity = contract.job_id(job)
    hashes = contract.body_hashes(body)
    if hashes != plan["request_hashes"][identity]:
        raise contract.IntegrityError("request body differs before dispatch")
    wire = json.dumps(body).encode("utf-8")
    directory = contract.cell_dir(bundle, job, stage)
    for number in range(1, plan["execution"]["max_attempts"] + 1):
        started = now()
        inflight = dict(job, job_id=identity, attempt=number, stage=stage, started_at=started, **hashes)
        (bundle / "inflight.json").write_bytes(contract.json_bytes(inflight))
        tick = time.monotonic()
        outcome = transport(plan["decode"]["api_url"], wire, key, plan["execution"]["timeout_seconds"])
        response = dict(inflight, finished_at=now(), elapsed_seconds=round(time.monotonic() - tick, 6), **outcome)
        # Check raw bytes/payload consistency before writing derived predictions.
        contract.decode_response_record(response)
        append(directory / "responses.jsonl", response)
        attempt = {field: response[field] for field in ("job_id", "attempt", "started_at", "finished_at", "elapsed_seconds",
                                                        "http_status", "body_object_sha256", "body_wire_sha256")}
        append(directory / "attempts.jsonl", attempt)
        status = outcome["http_status"]
        if status == 200 or status not in (None, *contract.RETRY_STATUSES) or number == plan["execution"]["max_attempts"]:
            break
        retry_after = (outcome.get("headers") or {}).get("retry-after")
        try:
            delay = min(30.0, max(0.0, float(retry_after))) if retry_after else min(8.0, 2.0 * number)
        except (ValueError, TypeError):
            delay = 2.0
        sleeper(delay)
    scored = contract.score_response(outcome, job["protocol"], len(record["key_frame_ids"]) - 1)
    payload = outcome.get("payload") if isinstance(outcome.get("payload"), dict) else {}
    headers = outcome.get("headers") or {}
    entry = dict(job, job_id=identity, type=record["type"], task_name=record["task_name"], num_states=len(record["key_frame_ids"]),
                 attempts=number, http_status=status, started_at=started, finished_at=response["finished_at"],
                 usage=payload.get("usage"), model_returned=payload.get("model"),
                 request_id=headers.get("x-request-id") or headers.get("x-dashscope-request-id") or payload.get("id"),
                 response_record_sha256=contract.sha(contract.canonical(response)), **hashes, **scored)
    append(directory / "predictions.jsonl", entry)
    (bundle / "inflight.json").unlink()
    return entry


def smoke_acceptance(plan: dict, report: dict) -> dict:
    reconstructed = report["request_reconstruction"]
    return {"schema": "usim-protocol-ablation-smoke/v1", "plan_sha256": plan["plan_sha256"],
            "expected": plan["expected_smoke_jobs"], "checked": reconstructed["bodies_checked"],
            "compatibility_passed": report["ok"] and reconstructed["complete"] and all(
                cell["compatibility_passed"] for cell in reconstructed["cells"].values()), "em_used": False}


def freeze_execution(bundle: Path, plan: dict, report: dict) -> None:
    acceptance = smoke_acceptance(plan, report)
    if not acceptance["compatibility_passed"]:
        raise contract.IntegrityError("compatibility checks did not pass; formal requests remain blocked")
    contract.write_once(bundle / "smoke/acceptance.json", contract.json_bytes(acceptance))
    paths = [bundle / "candidate.freeze.json", bundle / "smoke/acceptance.json", *sorted((bundle / "smoke").glob("*/*/*.jsonl"))]
    manifest = contract.seal({"schema": contract.FREEZE_SCHEMA, "stage": "execution",
                              "freeze_id": f"protocol_ablation2048_v1:{plan['plan_sha256'][:12]}:execution", "plan_sha256": plan["plan_sha256"],
                              "candidate_sha256": contract.file_sha(bundle / "candidate.freeze.json"),
                              "files": [{"root": "run", "path": path.relative_to(bundle).as_posix(), "sha256": contract.file_sha(path)} for path in paths]})
    contract.write_once(bundle / "execution.freeze.json", contract.json_bytes(manifest))


def execute(bundle: Path, *, resume: bool = False, smoke_only: bool = False, workspace: Path = WORKSPACE,
            transport=send_http, sleeper=time.sleep, key_reader=resolve_key) -> dict:
    checked = verify(bundle, workspace=workspace, prepared_only=True)
    if not checked["ok"]:
        raise contract.IntegrityError(str(checked["errors"]))
    plan = contract.read_json(bundle / "plan.json")
    evidence_exists = any(bundle.glob("*/*/predictions.jsonl")) or any((bundle / "smoke").glob("*/*/predictions.jsonl"))
    if evidence_exists and not resume:
        raise contract.IntegrityError("existing evidence requires --resume; terminal answers are never retried")
    # Existing partial evidence must be internally consistent before key access.
    for stage in ("smoke", "formal"):
        if stage == "formal" and not (bundle / "execution.freeze.json").exists():
            if any(bundle.glob("*/*/predictions.jsonl")):
                raise contract.IntegrityError("formal evidence exists without execution freeze")
            continue
        partial = verify(bundle, workspace=workspace, stage=stage, allow_partial=True)
        if not partial["ok"]:
            raise contract.IntegrityError(str(partial["errors"]))
    lock = bundle / "execution.lock"
    with lock.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps({"pid": os.getpid(), "started_at": now()}))
    try:
        conditions = {name: contract.unique(rows) for name, rows in contract.load_conditions(bundle, plan).items()}
        key = None
        for stage in ("smoke", "formal"):
            if stage == "formal" and smoke_only:
                break
            schedule = plan["smoke_schedule"] if stage == "smoke" else plan["schedule"]
            present = {}
            for protocol in contract.PROTOCOLS:
                for condition in contract.CONDITIONS:
                    path = contract.cell_dir(bundle, {"protocol": protocol, "condition": condition}, stage) / "predictions.jsonl"
                    present.update(contract.unique(contract.read_rows(path), "job_id") if path.exists() else {})
            for index, job in enumerate(schedule):
                if contract.job_id(job) in present:
                    continue
                if key is None:
                    key = key_reader()
                entry = run_job(bundle, plan, conditions[job["condition"]][job["id"]], job, stage, key,
                                transport=transport, sleeper=sleeper)
                print(f"{stage} {index + 1}/{len(schedule)} {job['protocol']}/{job['condition']} finish={entry['finish_reason']} strict={entry['strict_reason']}", flush=True)
                if entry["http_status"] in (400, 401, 403, 404, 422):
                    raise contract.IntegrityError(f"non-retryable HTTP {entry['http_status']}; stopping")
                sleeper(plan["execution"]["sleep_seconds"])
            report = verify(bundle, workspace=workspace, stage=stage)
            if not report["ok"]:
                raise contract.IntegrityError(str(report["errors"]))
            if stage == "smoke":
                freeze_execution(bundle, plan, report)
        return verify(bundle, workspace=workspace, stage="smoke" if smoke_only else "formal")
    finally:
        lock.unlink()


def analyse(bundle: Path, *, workspace: Path = WORKSPACE) -> dict:
    checked = verify(bundle, workspace=workspace)
    if not checked["ok"]:
        raise contract.IntegrityError(str(checked["errors"]))
    plan = contract.read_json(bundle / "plan.json")
    metrics = {}
    for protocol in contract.PROTOCOLS:
        for condition, label in contract.CONDITIONS.items():
            output = bundle / "analysis" / protocol / label
            output.mkdir(parents=True, exist_ok=True)
            command = [sys.executable, str(ENACT / "scripts/usim/evaluate.py"), "--data-root", plan["data_root"],
                       "--qa", str(bundle / plan["conditions"][condition]["qa_file"]),
                       "--predictions", str(contract.cell_dir(bundle, {"protocol": protocol, "condition": condition}) / "predictions.jsonl"),
                       "--out", str(output / "report.json")]
            completed = subprocess.run(command, cwd=ENACT, capture_output=True)
            (output / "evaluator_console.txt").write_bytes(completed.stdout + completed.stderr)
            if completed.returncode:
                raise contract.IntegrityError(f"stock evaluator failed for {protocol}/{condition}")
            report = contract.read_json(output / "report.json")
            records = contract.unique(contract.read_rows(bundle / plan["conditions"][condition]["qa_file"]))
            predictions = contract.read_rows(contract.cell_dir(bundle, {"protocol": protocol, "condition": condition}) / "predictions.jsonl")
            correct = sum(row["extract_status"] == "ok" and row["extract_permutation"] == records[row["id"]]["gt_answer"] for row in predictions)
            metrics[f"{protocol}/{condition}"] = {"primary": report["overall"], "secondary_correct": correct,
                                                  "secondary_EM": correct / len(records), "N": len(records)}
    summary = {"schema": "usim-protocol-ablation-analysis/v1", "plan_sha256": plan["plan_sha256"],
               "scope": "development; not final test", "metrics": metrics, "em_used_for_format_gate": False}
    (bundle / "analysis/summary.json").write_bytes(contract.json_bytes(summary))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    for name in ("prepare", "execute", "analyse", "verify"):
        mode.add_argument(f"--{name}", action="store_true")
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--smoke-only", action="store_true")
    parser.add_argument("--prepared-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        if (args.resume or args.smoke_only) and not args.execute:
            raise contract.IntegrityError("--resume/--smoke-only require --execute")
        if args.prepared_only and not args.verify:
            raise contract.IntegrityError("--prepared-only requires --verify")
        bundle = args.run_dir.resolve()
        if args.execute:
            if contract.read_json(bundle / "plan.json")["scope"] != "dev":
                raise contract.IntegrityError("CLI execution requires the production dev scope; fixtures are offline tests only")
            report = execute(bundle, resume=args.resume, smoke_only=args.smoke_only)
        elif args.analyse:
            report = analyse(bundle)
        elif args.verify:
            report = verify(bundle, prepared_only=args.prepared_only)
        else:
            plan = prepare(bundle)
            report = {"state": "prepared", "expected_formal_jobs": plan["expected_jobs"], "expected_smoke_jobs": 8,
                      "plan_sha256": plan["plan_sha256"], "authenticated_api_called": False, "execution_verified": False}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if report.get("ok") is False:
            return 2
        if args.execute and not args.smoke_only:
            cells = report["request_reconstruction"]["cells"]
            if not all(value["format_gate_passed"] for key, value in cells.items() if key.startswith("prefill/")):
                return 3
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
