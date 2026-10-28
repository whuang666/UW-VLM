"""Offline definitions for the versioned no-prefill/prefill development matrix.

This module has no HTTP or credential code. The runner and the independent
verifier share these fixed definitions and delegate parsing to the frozen scorer.
"""

from __future__ import annotations

import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import sys
from types import SimpleNamespace
from typing import Any

ENACT = Path(__file__).resolve().parents[2]
WORKSPACE = ENACT.parent
if str(ENACT) not in sys.path:
    sys.path.insert(0, str(ENACT))

PLAN_SCHEMA = "usim-protocol-ablation-plan/v1"
FREEZE_SCHEMA = "usim-protocol-ablation-freeze/v1"
PROTOCOLS = ("no_prefill", "prefill")
CONDITIONS = {"A": "A_full_image", "B": "B_zoom", "C": "C_text_only", "D": "D_no_action_text"}
PREFIX = "["
RETRY_STATUSES = (408, 409, 425, 429, 500, 502, 503, 504)
SOURCE_FILES = (
    "ENACT/scripts/usim/protocol_ablation_v1.py",
    "ENACT/scripts/usim/run_v02_protocol_ablation.py",
    "tools/verify_protocol_ablation.py",
    "tools/test_protocol_ablation_v1.py",
    "ENACT/scripts/usim/run_inference.py",
    "ENACT/scripts/usim/evaluate.py",
    "ENACT/scripts/usim/extractable_v1.py",
    "ENACT/docs/protocols/protocol_ablation2048_v1.md",
)


class IntegrityError(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha(path: Path) -> str:
    return sha(path.read_bytes())


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def unique(rows: list[dict], key: str = "id") -> dict[str, dict]:
    result = {}
    for row in rows:
        value = row[key]
        if value in result:
            raise IntegrityError(f"duplicate {key}: {value}")
        result[value] = row
    return result


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def rows_bytes(rows: list[dict]) -> bytes:
    return b"".join(canonical(row) + b"\n" for row in rows)


def write_once(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise IntegrityError(f"immutable file differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)


def within(root: Path, relative: str) -> Path:
    path = (root / relative.replace("\\", "/")).resolve()
    if Path(relative).is_absolute() or root.resolve() not in path.parents:
        raise IntegrityError(f"unsafe relative path: {relative}")
    return path


def seal(value: dict, field: str = "payload_sha256") -> dict:
    result = dict(value)
    result.pop(field, None)
    result[field] = sha(canonical(result))
    return result


def check_seal(value: dict, field: str = "payload_sha256") -> None:
    if value.get(field) != seal(value, field)[field]:
        raise IntegrityError(f"{field} mismatch")


def job_id(job: dict) -> str:
    return f"{job['protocol']}|{job['condition']}|{job['id']}"


def cell_dir(bundle: Path, job: dict, stage: str = "formal") -> Path:
    root = bundle / "smoke" if stage == "smoke" else bundle
    return root / job["protocol"] / CONDITIONS[job["condition"]]


def validate_records(conditions: dict[str, list[dict]]) -> None:
    from scripts.usim.evaluate import USIMEvaluator

    if set(conditions) != set(CONDITIONS):
        raise IntegrityError("the matrix requires A/B/C/D")
    maps = {key: unique(rows) for key, rows in conditions.items()}
    if any(not value for value in maps.values()):
        raise IntegrityError("empty QA condition")
    if set(maps["A"]) != set(maps["B"]) or conditions["A"] != conditions["C"]:
        raise IntegrityError("A/B IDs or A/C source records differ")
    expected_d = {qid for qid, row in maps["A"].items() if "forward" in row["type"]}
    if set(maps["D"]) != expected_d:
        raise IntegrityError("D must equal A's complete forward subset")
    for key, rows in conditions.items():
        for row in rows:
            length = len(row["key_frame_ids"]) - 1
            if length < 1 or len(row["images"]) != length + 1:
                raise IntegrityError("state/image count conflict")
            if USIMEvaluator.parse_strict(row["gt_answer"], length)[0] is None:
                raise IntegrityError("invalid reference permutation")
            if key != "A":
                original = maps["A"][row["id"]]
                fields = ("type", "task_name", "key_frame_ids", "gt_answer")
                if any(row[field] != original[field] for field in fields):
                    raise IntegrityError("cross-condition reference conflict")
                if key == "B" and (row["question"] != original["question"] or row.get("source_images") != original["images"]):
                    raise IntegrityError("B must retain A's question and source image order")
                if key == "D" and row["images"] != original["images"]:
                    raise IntegrityError("D must retain A's display images")
                if key == "D" and row["question"] == original["question"]:
                    raise IntegrityError("D action text was not removed")


def build_body(record: dict, plan: dict, protocol: str, condition: str) -> dict:
    from scripts.usim import run_inference

    if protocol not in PROTOCOLS or condition not in CONDITIONS:
        raise IntegrityError("unknown protocol/condition")
    data_root = Path(plan["data_root"])
    for relative in record["images"]:
        within(data_root, relative)
    payload = run_inference.whitelist_payload(record, data_root)
    decode = plan["decode"]
    args = SimpleNamespace(temperature=decode["temperature"], max_completion_tokens=decode["max_completion_tokens"],
                           enable_thinking=decode["enable_thinking"], drop_images=condition == "C")
    body = run_inference.build_body(decode["model_requested"], payload["question"], payload["images"], args,
                                    decode.get("system_prompt") or "", decode["format_directive"])
    if protocol == "prefill":
        body["messages"].append({"role": "assistant", "content": PREFIX, "partial": True})
    return body


def body_hashes(body: dict) -> dict:
    return {"body_object_sha256": sha(canonical(body)), "body_wire_sha256": sha(json.dumps(body).encode("utf-8"))}


def make_plan(data_root: Path, conditions: dict[str, list[dict]], decode: dict, seed: int = 20261028,
              scope: str = "dev", reference_files: dict | None = None) -> dict:
    validate_records(conditions)
    if scope not in ("dev", "fixture"):
        raise IntegrityError("unsupported matrix scope")
    if (decode["max_completion_tokens"] != 2048 or decode["enable_thinking"] is not False
            or decode["temperature"] != 0 or decode["stream"] is not False):
        raise IntegrityError("this version fixes 2048 tokens, thinking=false and temperature=0")
    units = [(condition, row["id"]) for condition, rows in conditions.items() for row in rows]
    random.Random(seed).shuffle(units)
    jobs = []
    for index, (condition, qid) in enumerate(units):
        order = PROTOCOLS if index % 2 == 0 else tuple(reversed(PROTOCOLS))
        jobs.extend({"protocol": protocol, "condition": condition, "id": qid} for protocol in order)
    smoke = []
    for condition, rows in conditions.items():
        candidates = [row for row in rows if "forward" in row["type"] and len(row["key_frame_ids"]) == 4]
        target = sorted(candidates or rows, key=lambda row: row["id"])[0]
        smoke.extend({"protocol": protocol, "condition": condition, "id": target["id"]} for protocol in PROTOCOLS)
    images = {}
    for rows in conditions.values():
        for row in rows:
            for relative in row["images"]:
                path = within(data_root, relative)
                images[relative.replace("\\", "/")] = file_sha(path)
    plan = {
        "schema": PLAN_SCHEMA, "scope": scope, "data_root": str(data_root.resolve()), "seed": seed,
        "protocols": list(PROTOCOLS), "prefix": PREFIX, "concat_rule": 'completed_answer = "[" + raw_completion; no repair',
        "decode": decode,
        "execution": {"max_attempts": 3, "timeout_seconds": 180, "sleep_seconds": 1.0,
                      "retry_http_statuses": list(RETRY_STATUSES), "retry_format_errors": False},
        "conditions": {key: {"qa_file": f"inputs/{key}.jsonl", "qa_sha256": sha(rows_bytes(rows)),
                             "ids": [row["id"] for row in rows], "questions": len(rows)} for key, rows in conditions.items()},
        "images_sha256": images, "schedule": jobs, "smoke_schedule": smoke,
        "expected_jobs": len(jobs), "expected_smoke_jobs": len(smoke),
        "primary_metric": "usim_strict_v0.3", "secondary_metric": "extractable_permutation_v1", "em_used_for_gate": False,
        "reference_files_sha256": dict(reference_files or {}),
    }
    maps = {key: unique(rows) for key, rows in conditions.items()}
    plan["request_hashes"] = {job_id(job): body_hashes(build_body(maps[job["condition"]][job["id"]], plan,
                                                                  job["protocol"], job["condition"])) for job in jobs}
    return seal(plan, "plan_sha256")


def expected_config(plan: dict, protocol: str, condition: str) -> dict:
    return {"schema": "usim-protocol-ablation-config/v1", "plan_sha256": plan["plan_sha256"],
            "protocol": protocol, "condition": condition, "decode": plan["decode"], "execution": plan["execution"],
            "qa_sha256": plan["conditions"][condition]["qa_sha256"], "questions": plan["conditions"][condition]["questions"]}


def create_bundle(bundle: Path, workspace: Path, data_root: Path, conditions: dict, decode: dict,
                  *, scope: str = "dev", seed: int = 20261028, reference_files: dict | None = None) -> dict:
    if bundle.resolve() == data_root.resolve() or data_root.resolve() in bundle.resolve().parents:
        raise IntegrityError("output overlaps dataset")
    if bundle.exists() and any(bundle.iterdir()):
        raise IntegrityError("bundle already exists; verify it instead of overwriting")
    for path, expected in (reference_files or {}).items():
        if file_sha(within(workspace, path)) != expected:
            raise IntegrityError(f"frozen reference dependency differs: {path}")
    plan = make_plan(data_root, conditions, decode, seed, scope, reference_files)
    if scope == "dev" and ({key: len(value) for key, value in conditions.items()} != {"A": 84, "B": 84, "C": 84, "D": 42}
                            or plan["expected_jobs"] != 588):
        raise IntegrityError("production development scope must contain 588 jobs")
    bundle.mkdir(parents=True, exist_ok=True)
    write_once(bundle / "plan.json", json_bytes(plan))
    for key, rows in conditions.items():
        write_once(bundle / "inputs" / f"{key}.jsonl", rows_bytes(rows))
        for protocol in PROTOCOLS:
            write_once(cell_dir(bundle, {"protocol": protocol, "condition": key}) / "run_config.json",
                       json_bytes(expected_config(plan, protocol, key)))
    inventory = [{"root": "workspace", "path": path, "sha256": file_sha(within(workspace, path))} for path in SOURCE_FILES]
    inventory.extend({"root": "workspace", "path": path, "sha256": digest} for path, digest in plan["reference_files_sha256"].items()
                     if path not in SOURCE_FILES)
    for path in [bundle / "plan.json", *(bundle / "inputs").glob("*.jsonl"), *bundle.glob("*/*/run_config.json")]:
        inventory.append({"root": "run", "path": path.relative_to(bundle).as_posix(), "sha256": file_sha(path)})
    inventory.extend({"root": "data", "path": path, "sha256": digest} for path, digest in plan["images_sha256"].items())
    manifest = seal({"schema": FREEZE_SCHEMA, "stage": "candidate", "freeze_id": f"protocol_ablation2048_v1:{plan['plan_sha256'][:12]}:candidate",
                     "plan_sha256": plan["plan_sha256"], "files": inventory,
                     "primary_metric_unchanged": True, "unified_output_budget": None})
    write_once(bundle / "candidate.freeze.json", json_bytes(manifest))
    return plan


def load_conditions(bundle: Path, plan: dict) -> dict:
    return {key: read_rows(within(bundle, value["qa_file"])) for key, value in plan["conditions"].items()}


def validate_plan(bundle: Path, plan: dict) -> dict:
    check_seal(plan, "plan_sha256")
    if plan["schema"] != PLAN_SCHEMA or plan["protocols"] != list(PROTOCOLS) or plan["prefix"] != PREFIX:
        raise IntegrityError("unsupported plan/schema/protocol")
    if plan["concat_rule"] != 'completed_answer = "[" + raw_completion; no repair' or plan["em_used_for_gate"] is not False:
        raise IntegrityError("unsupported assembly or gate policy")
    expected_execution = {"max_attempts": 3, "timeout_seconds": 180, "sleep_seconds": 1.0,
                          "retry_http_statuses": list(RETRY_STATUSES), "retry_format_errors": False}
    if (plan["execution"] != expected_execution or plan["decode"]["max_completion_tokens"] != 2048
            or plan["decode"]["enable_thinking"] is not False or plan["decode"]["temperature"] != 0
            or plan["decode"]["stream"] is not False):
        raise IntegrityError("execution/decode policy drift")
    if plan["primary_metric"] != "usim_strict_v0.3" or plan["secondary_metric"] != "extractable_permutation_v1":
        raise IntegrityError("scoring version drift")
    conditions = load_conditions(bundle, plan)
    if plan["scope"] == "dev" and not plan["reference_files_sha256"]:
        raise IntegrityError("production scope requires frozen scoring/data dependencies")
    validate_records(conditions)
    expected = set()
    for key, rows in conditions.items():
        info = plan["conditions"][key]
        if info["questions"] != len(rows) or info["ids"] != [row["id"] for row in rows] or info["qa_sha256"] != sha(rows_bytes(rows)):
            raise IntegrityError("QA hash/ID/count drift")
        expected.update(f"{protocol}|{key}|{row['id']}" for protocol in PROTOCOLS for row in rows)
    scheduled = unique([dict(job, job_id=job_id(job)) for job in plan["schedule"]], "job_id")
    if set(scheduled) != expected or plan["expected_jobs"] != len(expected) or not expected:
        raise IntegrityError("schedule does not cover the complete matrix")
    smokes = unique([dict(job, job_id=job_id(job)) for job in plan["smoke_schedule"]], "job_id")
    if len(smokes) != 8 or plan["expected_smoke_jobs"] != 8 or any(qid not in expected for qid in smokes):
        raise IntegrityError("smoke schedule does not cover all eight cells")
    if Counter((job["protocol"], job["condition"]) for job in smokes.values()) != Counter((p, c) for p in PROTOCOLS for c in CONDITIONS):
        raise IntegrityError("smoke cell coverage differs")
    if set(plan["request_hashes"]) != expected:
        raise IntegrityError("planned body hash coverage differs")
    if set(plan["images_sha256"]) != {path.replace("\\", "/") for rows in conditions.values() for row in rows for path in row["images"]}:
        raise IntegrityError("image inventory differs from QA references")
    return conditions


def response_content(payload: Any) -> tuple[Any, Any]:
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None, None
    choice = choices[0]
    message = choice.get("message") or {}
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict) and isinstance(part.get("text"), str))
    return content if isinstance(content, str) else None, choice.get("finish_reason")


def score_response(outcome: dict, protocol: str, expected_length: int) -> dict:
    from scripts.usim.evaluate import USIMEvaluator
    from scripts.usim.extractable_v1 import extract

    raw, finish = response_content(outcome.get("payload"))
    completed = (PREFIX if protocol == "prefill" else "") + raw if raw else None
    if outcome.get("http_status") != 200:
        status = "failed"
    elif not raw or finish not in ("stop", "length"):
        status = "invalid"
    else:
        status = "truncated" if finish == "length" else "success"
    answer = completed if status not in ("failed", "invalid") else None
    parsed, reason = USIMEvaluator.parse_strict(answer, expected_length)
    secondary = extract(answer, finish, expected_length) if status == "success" else {
        "status": "zero", "permutation": None, "reason": f"response_not_success:{status}"}
    return {"raw_completion": raw, "completed_answer": completed, "answer": answer, "status": status,
            "finish_reason": finish, "expected_length": expected_length, "strict_permutation": parsed,
            "strict_reason": reason, "extract_status": secondary["status"], "extract_permutation": secondary["permutation"],
            "extract_reason": secondary["reason"], "prefix_echo": protocol == "prefill" and bool(raw and raw.startswith(PREFIX))}


def decode_response_record(response: dict) -> dict:
    encoded = response.get("response_wire_b64")
    if encoded is None:
        if response.get("http_status") is not None or not response.get("network_error"):
            raise IntegrityError("missing raw HTTP response")
        return {"http_status": None, "payload": None}
    raw = base64.b64decode(encoded, validate=True)
    if sha(raw) != response.get("response_wire_sha256"):
        raise IntegrityError("raw response hash differs")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        payload = None
    if payload != response.get("payload"):
        raise IntegrityError("stored response payload differs from raw HTTP bytes")
    return {"http_status": response["http_status"], "payload": payload}
